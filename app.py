from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
from uuid import uuid4
import glob

app = Flask(__name__)
CORS(app)  # Habilita CORS global

DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

@app.route('/download', methods=['POST', 'OPTIONS'])
def download():
    if request.method == 'OPTIONS':
        return '', 200

    data = request.get_json()
    url = data.get('url')
    fmt = data.get('format')

    if not url or fmt not in ['mp3', 'mp4']:
        return jsonify({'success': False, 'error': 'Parámetros inválidos'}), 400

    filename_prefix = str(uuid4())
    output_template = os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.%(ext)s')

    ydl_opts = {
        'outtmpl': output_template,
        'format': 'bestaudio/best' if fmt == 'mp3' else 'best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }] if fmt == 'mp3' else [],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        ext = 'mp3' if fmt == 'mp3' else 'mp4'
        downloaded_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, f'{filename_prefix}.{ext}'))
        if not downloaded_files:
            return jsonify({'success': False, 'error': 'Archivo no encontrado'}), 500

        final_file = os.path.basename(downloaded_files[0])
        return jsonify({
            'success': True,
            'download_url': f'/file/{final_file}'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/file/<filename>')
def serve_file(filename):
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return 'Archivo no encontrado', 404
    return send_file(path, as_attachment=True)

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
