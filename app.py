# app.py (Completo y corregido)

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
import logging

# Inicialización de la App
app = Flask(__name__)

# --- CONFIGURACIÓN DE CORS MEJORADA ---
# Lista de orígenes permitidos. Incluye tu dominio de GitHub Pages
# y 'null' para pruebas locales (abrir el archivo HTML directamente).
origins = [
    "https://abogadosensalud.github.io",
    "http://localhost:5500",  # Si usas Live Server en VSCode para pruebas
    "http://127.0.0.1:5500", # Alternativa para Live Server
    "null" # Para cuando abres el index.html localmente como file://
]

CORS(app, resources={r"/*": {"origins": origins}})


# Configurar logging
logging.basicConfig(level=logging.INFO)

# --- CONFIGURACIÓN ---
DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Configuración mejorada de Celery
app.config['CELERY_BROKER_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
app.config['CELERY_RESULT_BACKEND'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
app.config['CELERY_TASK_SERIALIZER'] = 'json'
app.config['CELERY_RESULT_SERIALIZER'] = 'json'
app.config['CELERY_ACCEPT_CONTENT'] = ['json']
app.config['CELERY_TIMEZONE'] = 'UTC'
app.config['CELERY_ENABLE_UTC'] = True
app.config['CELERY_RESULT_EXPIRES'] = 3600
app.config['CELERY_TASK_RESULT_EXPIRES'] = 3600

def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask
    return celery

celery = make_celery(app)
redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

# --- MANEJO DE COOKIES CON LOGGING MEJORADO ---
cookie_env = os.getenv('COOKIE_STRING')
COOKIE_FILE_PATH = None

if cookie_env:
    COOKIE_FILE_PATH = os.path.join(tempfile.gettempdir(), 'yt-cookies.txt')
    try:
        with open(COOKIE_FILE_PATH, 'w') as f:
            f.write(cookie_env)
        app.logger.info(f"Variable COOKIE_STRING encontrada. Archivo de cookies creado en: {COOKIE_FILE_PATH}")
        app.logger.info(f"Tamaño del archivo de cookies: {os.path.getsize(COOKIE_FILE_PATH)} bytes.")
    except Exception as e:
        app.logger.error(f"Error al escribir el archivo de cookies en {COOKIE_FILE_PATH}: {e}", exc_info=True)
        COOKIE_FILE_PATH = None
else:
    app.logger.warning("Variable de entorno COOKIE_STRING no encontrada. Las descargas pueden fallar por restricciones de YouTube.")

@celery.task(bind=True)
def download_video_task(self, url, fmt, filename_prefix):
    """Tarea asíncrona para descargar videos con logging de cookies"""
    try:
        self.update_state(state='PROGRESS', meta={'status': 'Iniciando descarga...'})
        
        output_template = os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.%(ext)s')
        
        ydl_opts = {
            'outtmpl': output_template,
            'noplaylist': True,
            'no_warnings': True,
            'quiet': True,
            'extract_flat': False,
            'writethumbnail': False,
            'writeinfojson': False,
        }

        if COOKIE_FILE_PATH:
            if os.path.exists(COOKIE_FILE_PATH):
                ydl_opts['cookiefile'] = COOKIE_FILE_PATH
                app.logger.info(f"[Task {self.request.id}] Usando archivo de cookies: {COOKIE_FILE_PATH}")
            else:
                app.logger.warning(f"[Task {self.request.id}] El archivo de cookies {COOKIE_FILE_PATH} fue definido pero no se encontró en el sistema de archivos.")
        else:
            app.logger.info(f"[Task {self.request.id}] No se está usando un archivo de cookies.")


        if fmt == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'}]
            self.update_state(state='PROGRESS', meta={'status': 'Descargando audio...'})
        else:
            ydl_opts['format'] = 'best[height<=720]/best'
            self.update_state(state='PROGRESS', meta={'status': 'Descargando video...'})

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        self.update_state(state='PROGRESS', meta={'status': 'Procesando archivo...'})

        ext = 'mp3' if fmt == 'mp3' else 'mp4'
        downloaded_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.{ext}'))

        if not downloaded_files:
            all_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.*'))
            if not all_files:
                raise Exception(f"Archivo no encontrado después de la descarga para el prefijo: {filename_prefix}")
            downloaded_files = all_files

        final_filename = os.path.basename(downloaded_files[0])
        
        return {'status': 'SUCCESS', 'filename': final_filename}

    except Exception as e:
        app.logger.error(f"Error en la tarea {self.request.id}: {e}", exc_info=True)
        error_msg = str(e)
        self.update_state(state='FAILURE', meta={'error': error_msg, 'exc_type': type(e).__name__})

# --- El resto del código no cambia ---
@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    if not data: return jsonify({'success': False, 'error': 'No se recibieron datos JSON'}), 400
    url = data.get('url')
    fmt = data.get('format')
    if not url or fmt not in ['mp3', 'mp4']: return jsonify({'success': False, 'error': 'Parámetros inválidos'}), 400
    filename_prefix = str(uuid4())
    task = download_video_task.delay(url, fmt, filename_prefix)
    return jsonify({'success': True, 'task_id': task.id, 'status': 'PENDING'})

@app.route('/status/<task_id>')
def task_status(task_id):
    try:
        task = celery.AsyncResult(task_id)
        if task.state == 'PENDING': response = {'state': task.state, 'status': 'Tarea en cola...'}
        elif task.state == 'PROGRESS':
            info = task.info or {}
            response = {'state': task.state, 'status': info.get('status', 'Procesando...')}
        elif task.state == 'SUCCESS':
            result = task.result or {}
            if isinstance(result, dict) and 'filename' in result:
                download_url = url_for('serve_file', filename=result['filename'], _external=True)
                response = {'state': task.state, 'download_url': download_url}
            else: response = {'state': 'FAILURE', 'error': 'Resultado de tarea inválido o la tarea falló silenciosamente.'}
        else:
            error_info = task.info or {}
            if isinstance(error_info, dict): error_msg = error_info.get('error', 'Error desconocido en la tarea.')
            else: error_msg = str(error_info) if error_info else 'Error desconocido en la tarea.'
            response = {'state': task.state, 'error': error_msg}
        return jsonify(response)
    except Exception as e:
        app.logger.error(f'Error en task_status para task_id {task_id}: {str(e)}', exc_info=True)
        return jsonify({'state': 'ERROR', 'error': f'Error interno al consultar estado de la tarea.'}), 500

@app.route('/file/<path:filename>')
def serve_file(filename):
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(path): return 'Archivo no encontrado', 404
    return send_file(path, as_attachment=True)

@app.route('/health')
def health_check():
    try:
        redis_client.ping()
        redis_status = 'connected'
    except: redis_status = 'disconnected'
    return jsonify({'status': 'healthy', 'timestamp': time.time(), 'redis': redis_status})

def cleanup_old_files():
    current_time = time.time()
    for filename in os.listdir(DOWNLOAD_FOLDER):
        filepath = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.isfile(filepath):
            if current_time - os.path.getctime(filepath) > 3600:
                try:
                    os.remove(filepath)
                    app.logger.info(f"Limpiando archivo antiguo: {filepath}")
                except Exception as e:
                    app.logger.error(f"Error limpiando archivo {filepath}: {e}")

if __name__ == '__main__':
    cleanup_old_files()
    app.run(debug=False)