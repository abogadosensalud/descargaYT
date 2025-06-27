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
import logging
import requests  # Importar requests para Telegram

# Inicialización de la App
app = Flask(__name__)

# --- CONFIGURACIÓN DE CORS MEJORADA ---
origins = [
    "https://abogadosensalud.github.io",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "null"
]
CORS(app, resources={r"/*": {"origins": origins}})

# Configurar logging
logging.basicConfig(level=logging.INFO)

# --- CONFIGURACIÓN GENERAL ---
DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# --- CONFIGURACIÓN DE TELEGRAM ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- CONFIGURACIÓN DE CREDENCIALES DE YOUTUBE (NUEVO MÉTODO) ---
YT_USER = os.getenv('YT_USER')
YT_PASS = os.getenv('YT_PASS')
if not YT_USER or not YT_PASS:
    app.logger.warning("Variables de entorno YT_USER o YT_PASS no encontradas. La descarga de videos restringidos podría fallar.")

# --- CONFIGURACIÓN DE CELERY ---
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

# --- FUNCIÓN DE AYUDA PARA TELEGRAM ---
def send_telegram_message(message):
    """Envía un mensaje a un chat de Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        app.logger.info("Token/ChatID de Telegram no configurados, omitiendo notificación.")
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    
    try:
        requests.post(api_url, json=payload, timeout=5)
        app.logger.info("Notificación de Telegram enviada.")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"No se pudo enviar la notificación de Telegram: {e}")


# --- TAREA DE CELERY (MODIFICADA) ---
@celery.task(bind=True, throws=(Exception,))
def download_video_task(self, url, fmt, filename_prefix):
    """Tarea asíncrona para descargar videos con notificaciones de Telegram."""
    try:
        # Notificación de inicio
        message_start = f"▶️ *Nueva conversión iniciada!*\n\n🔗 *URL:* `{url}`\n💿 *Formato:* `{fmt.upper()}`"
        send_telegram_message(message_start)

        self.update_state(state='PROGRESS', meta={'status': 'Iniciando descarga...'})
        
        output_template = os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.%(ext)s')
        
        ydl_opts = {
            'outtmpl': output_template,
            'noplaylist': True,
            'quiet': True,
            'extract_flat': False,
            'writethumbnail': False,
            'writeinfojson': False,
            'ignoreerrors': False,
            'source_address': '0.0.0.0',
        }

        # *** INICIO DEL CAMBIO IMPORTANTE ***
        # Usar usuario y contraseña de aplicación si están disponibles
        if YT_USER and YT_PASS:
            ydl_opts['username'] = YT_USER
            ydl_opts['password'] = YT_PASS
            app.logger.info(f"[Task {self.request.id}] Usando autenticación con usuario y contraseña.")
        else:
            app.logger.warning(f"[Task {self.request.id}] No se encontraron credenciales. Procediendo sin autenticación.")
        # *** FIN DEL CAMBIO IMPORTANTE ***
        
        if fmt == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'}]
            self.update_state(state='PROGRESS', meta={'status': 'Descargando y convirtiendo a MP3...'})
        else:
            ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
            ydl_opts['merge_output_format'] = 'mp4'
            self.update_state(state='PROGRESS', meta={'status': 'Descargando y uniendo a MP4...'})

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        self.update_state(state='PROGRESS', meta={'status': 'Buscando archivo final...'})
        
        final_file_path = None
        expected_ext = 'mp3' if fmt == 'mp3' else 'mp4'
        for _ in range(10):
            search_pattern = os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.{expected_ext}')
            found_files = glob.glob(search_pattern)
            if found_files:
                final_file_path = found_files[0]
                break
            
            search_pattern_any = os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.*')
            found_files_any = [f for f in glob.glob(search_pattern_any) if not f.endswith(('.part', '.ytdl'))]
            if found_files_any:
                final_file_path = found_files_any[0]
                break
            time.sleep(1)

        if not final_file_path:
            raise FileNotFoundError(f"Archivo final para {filename_prefix} no encontrado.")

        final_filename = os.path.basename(final_file_path)
        
        result_payload = {'status': 'SUCCESS', 'filename': final_filename}
        
        # Notificación de éxito
        message_success = f"✅ *¡Conversión completada!*\n\n📄 *Archivo:* `{final_filename}`\n🔗 *URL Original:* `{url}`"
        send_telegram_message(message_success)

        app.logger.info(f"[Task {self.request.id}] Tarea completada. Retornando: {result_payload}")
        return result_payload

    except Exception as e:
        # Notificación de error
        error_msg_telegram = f"❌ *¡FALLO en la conversión!*\n\n🔗 *URL:* `{url}`\n\n*Error:* `{str(e)}`"
        send_telegram_message(error_msg_telegram)
        
        app.logger.error(f"[Task {self.request.id}] ¡FALLO! Error: {e}", exc_info=True)
        raise

                                
# --- RUTAS DE FLASK ---
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
        else: # FAILURE
            error_msg = str(task.info) if task.info else 'Error desconocido en la tarea.'
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

# --- FUNCIÓN DE LIMPIEZA ---
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

# --- PUNTO DE ENTRADA ---
if __name__ == '__main__':
    cleanup_old_files()
    app.run(debug=False)
