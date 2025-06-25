from flask_cors import CORS
app = Flask(__name__)
CORS(app)


# app.py
from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
from uuid import uuid4


app = Flask(__name__)
DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')
    fmt = data.get('format')

    if not url or fmt not in ['mp3', 'mp4']:
        return jsonify({'success': False, 'error': 'Datos inválidos'}), 400

    output_file = os.path.join(DOWNLOAD_FOLDER, f'{uuid4()}.%(ext)s')
    ydl_opts = {
        'outtmpl': output_file,
        'format': 'bestaudio/best' if fmt == 'mp3' else 'best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }] if fmt == 'mp3' else [],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.download([url])
        real_path = output_file.replace('%(ext)s', 'mp3' if fmt == 'mp3' else 'mp4')
        filename = os.path.basename(real_path)
        return jsonify({
            'success': True,
            'download_url': f'/file/{filename}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/file/<filename>')
def serve_file(filename):
    path = os.path.join(DOWNLOAD_FOLDER, filename)
    return send_file(path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
