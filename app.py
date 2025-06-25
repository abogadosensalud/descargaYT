# app.py

from flask import Flask, request, jsonify, send_file, url_for
from flask_cors import CORS
import yt_dlp
import os
from uuid import uuid4
import glob

# Inicialización de la App
app = Flask(__name__)
CORS(app)

# --- CONFIGURACIÓN ---
DOWNLOAD_FOLDER = '/tmp/downloads'
# Ruta donde guardamos el archivo de cookies en Render
COOKIE_FILE_PATH = '/etc/secrets/cookies.txt' 
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos JSON'}), 400

    url = data.get('url')
    fmt = data.get('format')

    if not url or fmt not in ['mp3', 'mp4']:
        return jsonify({'success': False, 'error': 'Parámetros inválidos: se requiere URL y formato (mp3 o mp4)'}), 400

    filename_prefix = str(uuid4())
    output_template = os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.%(ext)s')

    # Configuración base para yt-dlp
    ydl_opts = {
        'outtmpl': output_template,
        'noplaylist': True,
    }

    # **CORRECCIÓN CLAVE**: Añadir el archivo de cookies si existe
    if os.path.exists(COOKIE_FILE_PATH):
        ydl_opts['cookiefile'] = COOKIE_FILE_PATH

    if fmt == 'mp3':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else: # mp4
        ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        ext = 'mp3' if fmt == 'mp3' else 'mp4'
        downloaded_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.{ext}'))
        
        if not downloaded_files:
            all_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.*'))
            if not all_files:
                 return jsonify({'success': False, 'error': 'Archivo no encontrado después de la descarga'}), 500
            downloaded_files = all_files

        final_filename = os.path.basename(downloaded_files[0])
        download_url = url_for('serve_file', filename=final_filename, _external=True)

        return jsonify({
            'success': True,
            'download_url': download_url
        })

    except yt_dlp.utils.DownloadError as e:
        # Esto capturará el error de "Sign in to confirm" y lo mostrará en el frontend.
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error inesperado: {str(e)}'}), 500


@app.route('/file/<path:filename>')
def serve_file(filename):
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return 'Archivo no encontrado', 404
    
    return send_file(path, as_attachment=True)
