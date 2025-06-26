# app.py

from flask import Flask, request, jsonify, send_file, url_for
from flask_cors import CORS
import yt_dlp
import os
from uuid import uuid4
import glob
import tempfile
from celery import Celery
import redis
import time

# Inicialización de la App
app = Flask(__name__)
CORS(app)

# --- CONFIGURACIÓN ---
DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Configuración mejorada de Celery
app.config['CELERY_BROKER_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
app.config['CELERY_RESULT_BACKEND'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Configuraciones adicionales para evitar errores de serialización
app.config['CELERY_TASK_SERIALIZER'] = 'json'
app.config['CELERY_RESULT_SERIALIZER'] = 'json'
app.config['CELERY_ACCEPT_CONTENT'] = ['json']
app.config['CELERY_TIMEZONE'] = 'UTC'
app.config['CELERY_ENABLE_UTC'] = True

# Configurar resultado backend para manejar excepciones correctamente
app.config['CELERY_RESULT_EXPIRES'] = 3600  # 1 hora
app.config['CELERY_TASK_RESULT_EXPIRES'] = 3600

def make_celery(app):
    """Factory para crear instancia de Celery con contexto de Flask"""
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        """Make celery tasks work with Flask app context."""
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

# Inicializar Celery con contexto
celery = make_celery(app)

# Cliente Redis para estado de tareas
redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

# --- COOKIES ---
cookie_env = os.getenv('COOKIE_STRING')
COOKIE_FILE_PATH = None

if cookie_env:
    COOKIE_FILE_PATH = os.path.join(tempfile.gettempdir(), 'cookies.txt')
    with open(COOKIE_FILE_PATH, 'w') as f:
        f.write(cookie_env)

@celery.task(bind=True)
def download_video_task(self, url, fmt, filename_prefix):
    """Tarea asíncrona para descargar videos"""
    try:
        # Actualizar estado: iniciando
        self.update_state(state='PROGRESS', meta={'status': 'Iniciando descarga...'})
        
        output_template = os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.%(ext)s')
        
        # Configuración optimizada para yt-dlp
        ydl_opts = {
            'outtmpl': output_template,
            'noplaylist': True,
            'no_warnings': True,
            'quiet': True,  # Reduce logs
            'extract_flat': False,
            'writethumbnail': False,  # No descargar thumbnails
            'writeinfojson': False,   # No crear archivos JSON
        }

        # Añadir cookies si existen
        if COOKIE_FILE_PATH and os.path.exists(COOKIE_FILE_PATH):
            ydl_opts['cookiefile'] = COOKIE_FILE_PATH

        if fmt == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',  # Reducido de 192 a 128 para mayor velocidad
            }]
            self.update_state(state='PROGRESS', meta={'status': 'Descargando audio...'})
        else:  # mp4
            # Formato más eficiente para video
            ydl_opts['format'] = 'best[height<=720]/best'  # Limitar calidad para velocidad
            self.update_state(state='PROGRESS', meta={'status': 'Descargando video...'})

        # Descargar
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        self.update_state(state='PROGRESS', meta={'status': 'Procesando archivo...'})

        # Buscar archivo descargado
        ext = 'mp3' if fmt == 'mp3' else 'mp4'
        downloaded_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.{ext}'))

        if not downloaded_files:
            all_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.*'))
            if not all_files:
                raise Exception('Archivo no encontrado después de la descarga')
            downloaded_files = all_files

        final_filename = os.path.basename(downloaded_files[0])
        
        return {
            'status': 'SUCCESS',
            'filename': final_filename
        }

    except Exception as e:
        # Mejorar el manejo de errores
        error_msg = str(e)
        self.update_state(
            state='FAILURE', 
            meta={
                'error': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': error_msg
            }
        )
        raise

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos JSON'}), 400

    url = data.get('url')
    fmt = data.get('format')

    if not url or fmt not in ['mp3', 'mp4']:
        return jsonify({'success': False, 'error': 'Parámetros inválidos'}), 400

    # Generar ID único para la tarea
    filename_prefix = str(uuid4())
    
    # Iniciar tarea asíncrona
    task = download_video_task.delay(url, fmt, filename_prefix)
    
    return jsonify({
        'success': True,
        'task_id': task.id,
        'status': 'PENDING'
    })

@app.route('/status/<task_id>')
def task_status(task_id):
    """Endpoint para verificar el estado de la descarga con manejo robusto de errores"""
    try:
        # Usar celery.AsyncResult en lugar de la tarea específica
        task = celery.AsyncResult(task_id)
        
        if task.state == 'PENDING':
            response = {
                'state': task.state,
                'status': 'Tarea en cola...'
            }
        elif task.state == 'PROGRESS':
            # Manejar casos donde task.info podría ser None
            info = task.info or {}
            response = {
                'state': task.state,
                'status': info.get('status', 'Procesando...')
            }
        elif task.state == 'SUCCESS':
            result = task.result or {}
            if isinstance(result, dict) and 'filename' in result:
                download_url = url_for('serve_file', filename=result['filename'], _external=True)
                response = {
                    'state': task.state,
                    'download_url': download_url
                }
            else:
                response = {
                    'state': 'FAILURE',
                    'error': 'Resultado de tarea inválido'
                }
        else:  # FAILURE u otros estados
            # Manejar información de error de manera más robusta
            error_info = task.info or {}
            if isinstance(error_info, dict):
                error_msg = error_info.get('error', error_info.get('exc_message', 'Error desconocido'))
            else:
                error_msg = str(error_info) if error_info else 'Error desconocido'
            
            response = {
                'state': task.state,
                'error': error_msg
            }
        
        return jsonify(response)
        
    except Exception as e:
        # Manejo de errores del propio endpoint
        app.logger.error(f'Error en task_status para task_id {task_id}: {str(e)}')
        return jsonify({
            'state': 'ERROR',
            'error': f'Error al consultar estado de la tarea: {str(e)}'
        }), 500

@app.route('/file/<path:filename>')
def serve_file(filename):
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return 'Archivo no encontrado', 404
    return send_file(path, as_attachment=True)

@app.route('/health')
def health_check():
    """Endpoint para keep-alive"""
    try:
        # Verificar conexión a Redis
        redis_client.ping()
        redis_status = 'connected'
    except:
        redis_status = 'disconnected'
    
    return jsonify({
        'status': 'healthy', 
        'timestamp': time.time(),
        'redis': redis_status
    })

# Limpieza de archivos antiguos al iniciar
def cleanup_old_files():
    """Elimina archivos más antiguos de 1 hora"""
    import time
    current_time = time.time()
    for filename in os.listdir(DOWNLOAD_FOLDER):
        filepath = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.isfile(filepath):
            if current_time - os.path.getctime(filepath) > 3600:  # 1 hora
                try:
                    os.remove(filepath)
                except:
                    pass

if __name__ == '__main__':
    cleanup_old_files()
    app.run(debug=False)