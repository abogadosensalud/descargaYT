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

# Configuración de Celery
app.config['CELERY_BROKER_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
app.config['CELERY_RESULT_BACKEND'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Inicializar Celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

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
        self.update_state(state='FAILURE', meta={'error': str(e)})
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
    """Endpoint para verificar el estado de la descarga"""
    task = download_video_task.AsyncResult(task_id)
    
    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'status': 'Tarea en cola...'
        }
    elif task.state == 'PROGRESS':
        response = {
            'state': task.state,
            'status': task.info.get('status', 'Procesando...')
        }
    elif task.state == 'SUCCESS':
        result = task.result
        download_url = url_for('serve_file', filename=result['filename'], _external=True)
        response = {
            'state': task.state,
            'download_url': download_url
        }
    else:  # FAILURE
        response = {
            'state': task.state,
            'error': str(task.info.get('error', 'Error desconocido'))
        }
    
    return jsonify(response)

@app.route('/file/<path:filename>')
def serve_file(filename):
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return 'Archivo no encontrado', 404
    return send_file(path, as_attachment=True)

@app.route('/health')
def health_check():
    """Endpoint para keep-alive"""
    return jsonify({'status': 'healthy', 'timestamp': time.time()})

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