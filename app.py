from flask import Flask, request, jsonify, send_file, url_for
from flask_cors import CORS
import yt_dlp
import os
from uuid import uuid4
import glob

# Inicialización de la App
app = Flask(__name__)
# Habilita CORS para todos los dominios. Puedes restringirlo si lo deseas.
# Ejemplo: CORS(app, resources={r"/*": {"origins": "https://tu-dominio-frontend.com"}})
CORS(app) 

# Carpeta para almacenar las descargas temporales
DOWNLOAD_FOLDER = '/tmp/downloads'
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

    # Genera un nombre de archivo único para evitar colisiones
    filename_prefix = str(uuid4())
    output_template = os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.%(ext)s')

    # Configuración para yt-dlp
    ydl_opts = {
        'outtmpl': output_template,
        'noplaylist': True, # Evita descargar playlists enteras por error
    }

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
        # Inicia la descarga
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Busca el archivo descargado
        # yt-dlp puede crear un .mp4 para el audio y luego convertirlo, así que buscamos el .mp3 final
        ext = 'mp3' if fmt == 'mp3' else 'mp4'
        downloaded_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.{ext}'))
        
        if not downloaded_files:
            # A veces, para video, la extensión final puede ser webm o mkv si mp4 no está disponible.
            # Podríamos buscar cualquier archivo si el primario falla.
            all_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.*'))
            if not all_files:
                 return jsonify({'success': False, 'error': 'Archivo no encontrado después de la descarga'}), 500
            downloaded_files = all_files

        # Obtiene el nombre del archivo final
        final_filename = os.path.basename(downloaded_files[0])
        
        # **CORRECCIÓN CLAVE**: Genera una URL absoluta para el archivo
        download_url = url_for('serve_file', filename=final_filename, _external=True)

        return jsonify({
            'success': True,
            'download_url': download_url
        })

    except yt_dlp.utils.DownloadError as e:
        # Captura errores específicos de descarga (ej. video privado, no encontrado)
        return jsonify({'success': False, 'error': f'Error de descarga: {e}'}), 500
    except Exception as e:
        # Captura cualquier otro error
        return jsonify({'success': False, 'error': f'Error inesperado: {str(e)}'}), 500


@app.route('/file/<path:filename>')
def serve_file(filename):
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return 'Archivo no encontrado', 404
    
    # as_attachment=True fuerza al navegador a mostrar el diálogo de "Guardar como..."
    return send_file(path, as_attachment=True)

# El bloque `if __name__ == '__main__':` se elimina.
# Gunicorn se encargará de iniciar el servidor en producción.
