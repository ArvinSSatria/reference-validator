# Ganti seluruh file ini di app/routes.py

import os
import io
import json # Tambahkan import json
from datetime import datetime
from flask import render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
import uuid # Untuk nama file unik

from app import app, logger
from app import services

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/validate', methods=['POST'])
def validate_references_api():
    try:
        # Hapus file-file dari sesi sebelumnya
        _cleanup_session_files()

        # Buat ID unik untuk sesi validasi ini
        session_id = str(uuid.uuid4())
        
        result = None
        file_stream_for_processing = None
        input_filename = None

        if 'file' in request.files and request.files['file'].filename:
            file = request.files['file']
            filename = secure_filename(file.filename)
            input_filename = filename
            
            upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            
            # Simpan file asli dengan nama berbasis ID sesi
            base_name, ext = os.path.splitext(filename)
            original_filepath = os.path.abspath(os.path.join(upload_folder, f"{session_id}_original{ext}"))
            file.save(original_filepath)
            
            # Simpan path file asli di sesi
            session['original_filepath'] = original_filepath
            
            # Buka kembali untuk diproses
            file_stream_for_processing = open(original_filepath, 'rb')
            result = services.process_validation_request(request, file_stream_for_processing)
            file_stream_for_processing.close()

        elif 'text' in request.form and request.form['text'].strip():
            result = services.process_validation_request(request, None)
        else:
            return jsonify({"error": "Tidak ada input yang diberikan."}), 400

        if "error" in result:
            return jsonify(result), 400
        
        # Simpan HASIL JSON ke file, bukan ke session cookie
        if input_filename: # Hanya simpan jika inputnya dari file
            results_filepath = os.path.abspath(os.path.join(upload_folder, f"{session_id}_results.json"))
            with open(results_filepath, 'w') as f:
                json.dump(result, f)
            # Simpan path file hasil di sesi
            session['results_filepath'] = results_filepath
            
        logger.info(f"Validation successful for {result['summary']['total_references']} references.")
        return jsonify(result)

    except Exception as e:
        logger.critical(f"Unhandled exception in /api/validate: {e}", exc_info=True)
        return jsonify({"error": "Terjadi kesalahan internal tak terduga."}), 500


@app.route('/api/download_report', methods=['GET'])
def download_report_api():
    try:
        original_filepath = session.get('original_filepath')
        results_filepath = session.get('results_filepath')
        
        if not original_filepath or not results_filepath:
            return jsonify({"error": "Sesi tidak valid atau file tidak ditemukan. Lakukan validasi ulang."}), 400

        # Baca hasil validasi dari file JSON
        with open(results_filepath, 'r') as f:
            validation_results = json.load(f)

        pdf_to_annotate_path = original_filepath
        is_temp_pdf = False

        if original_filepath.lower().endswith('.docx'):
            pdf_path, error = services.convert_docx_to_pdf(original_filepath)
            if error: return jsonify({"error": error}), 500
            pdf_to_annotate_path = pdf_path
            is_temp_pdf = True

        annotated_pdf_bytes, error = services.create_annotated_pdf_from_file(
            pdf_to_annotate_path, 
            validation_results
        )
        
        if is_temp_pdf and os.path.exists(pdf_to_annotate_path):
            os.remove(pdf_to_annotate_path)
        
        if error: return jsonify({"error": error}), 500

        base_name, _ = os.path.splitext(os.path.basename(original_filepath))
        download_filename = f"annotated_{base_name}.pdf"

        return send_file(
            io.BytesIO(annotated_pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=download_filename
        )

    except Exception as e:
        logger.critical(f"Unhandled exception in /api/download_report: {e}", exc_info=True)
        return jsonify({"error": "Gagal membuat laporan PDF karena kesalahan server."}), 500

def _cleanup_session_files():
    """Menghapus file-file sementara dari sesi sebelumnya."""
    paths_to_clean = ['original_filepath', 'results_filepath']
    for key in paths_to_clean:
        filepath = session.pop(key, None)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"File sesi lama dihapus: {filepath}")
            except Exception as e:
                logger.warning(f"Gagal menghapus file sesi lama {filepath}: {e}")

# ... (sisa file: health_check, error handlers tidak berubah) ...