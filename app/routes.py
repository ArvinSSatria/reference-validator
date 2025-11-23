import os
import io
import json
import time
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
import uuid
from app import app, logger
from app.services.validation_service import process_validation_request
from app.services.pdf_service import create_annotated_pdf
from app.services.docx_service import convert_docx_to_pdf
from config import Config

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/validate', methods=['POST'])
def validate_references_api():
    try:
        # Hapus file-file dari sesi sebelumnya
        _cleanup_session_files()
        
        # Auto-cleanup file lama (> 1 jam) dari folder uploads
        if Config.AUTO_CLEANUP_ENABLED:
            _cleanup_old_upload_files(max_age_hours=Config.AUTO_CLEANUP_MAX_AGE_HOURS)

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
            result = process_validation_request(request, file_stream_for_processing)
            file_stream_for_processing.close()

        elif 'text' in request.form and request.form['text'].strip():
            result = process_validation_request(request, None)
        else:
            return jsonify({"error": "Tidak ada input yang diberikan."}), 400

        if "error" in result:
            return jsonify(result), 400
        
        # Simpan HASIL JSON ke file untuk semua input (file atau text)
        upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            
        results_filepath = os.path.abspath(os.path.join(upload_folder, f"{session_id}_results.json"))
        with open(results_filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        # Simpan path file hasil di sesi (untuk text input dan file input)
        session['results_filepath'] = results_filepath
        session['session_id'] = session_id
            
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
        
        # Cek apakah results ada (untuk text input, hanya results_filepath yang ada)
        if not results_filepath:
            return jsonify({"error": "Sesi tidak valid. Lakukan validasi ulang."}), 400
        
        # Cek apakah ini dari text input atau file upload
        if not original_filepath:
            return jsonify({
                "error": "Download PDF hanya tersedia untuk file upload (PDF/DOCX). "
                        "Untuk text input, gunakan fitur download BibTeX pada setiap referensi."
            }), 400

        # Baca hasil validasi dari file JSON dengan encoding UTF-8
        with open(results_filepath, 'r', encoding='utf-8') as f:
            validation_results = json.load(f)

        pdf_to_annotate_path = original_filepath
        is_temp_pdf = False

        if original_filepath.lower().endswith('.docx'):
            pdf_path, error = convert_docx_to_pdf(original_filepath)
            if error: return jsonify({"error": error}), 500
            pdf_to_annotate_path = pdf_path
            is_temp_pdf = True

        annotated_pdf_bytes, error = create_annotated_pdf(
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


@app.route('/api/download_bibtex/<int:ref_number>', methods=['GET'])
def download_bibtex_api(ref_number):
    """
    Download BibTeX file untuk referensi tertentu (on-the-fly generation).
    
    Args:
        ref_number: Nomor referensi (1-indexed)
    """
    try:
        results_filepath = session.get('results_filepath')
        
        if not results_filepath or not os.path.exists(results_filepath):
            return jsonify({"error": "Sesi tidak valid. Lakukan validasi ulang."}), 400
        
        # Baca hasil validasi dari file JSON dengan encoding UTF-8
        with open(results_filepath, 'r', encoding='utf-8') as f:
            validation_results = json.load(f)
        
        detailed_results = validation_results.get('detailed_results', [])
        
        # Cari referensi berdasarkan reference_number
        target_ref = None
        for ref in detailed_results:
            if ref.get('reference_number') == ref_number:
                target_ref = ref
                break
        
        if not target_ref:
            return jsonify({"error": f"Referensi #{ref_number} tidak ditemukan."}), 404
        
        # Cek apakah BibTeX tersedia
        if not target_ref.get('bibtex_available', False):
            return jsonify({"error": f"BibTeX tidak tersedia untuk referensi #{ref_number}."}), 400
        
        bibtex_string = target_ref.get('bibtex_string')
        
        if not bibtex_string:
            return jsonify({"error": "BibTeX content tidak ditemukan."}), 500
        
        # Generate filename
        filename = f"reference_{ref_number}.bib"
        
        # Return as downloadable file
        return send_file(
            io.BytesIO(bibtex_string.encode('utf-8')),
            mimetype='text/plain',
            as_attachment=True,
            download_name=filename
        )
    
    except Exception as e:
        logger.error(f"Error downloading BibTeX for ref #{ref_number}: {e}", exc_info=True)
        return jsonify({"error": f"Gagal mengunduh BibTeX: {e}"}), 500

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


def _cleanup_old_upload_files(max_age_hours=1):
    try:
        upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.exists(upload_folder):
            return
        
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        deleted_count = 0
        
        for filename in os.listdir(upload_folder):
            filepath = os.path.join(upload_folder, filename)
            
            # Skip jika bukan file
            if not os.path.isfile(filepath):
                continue
            
            # Cek umur file
            file_age = current_time - os.path.getmtime(filepath)
            
            if file_age > max_age_seconds:
                try:
                    os.remove(filepath)
                    deleted_count += 1
                    logger.debug(f"Auto-deleted old file: {filename} (age: {file_age/3600:.1f}h)")
                except Exception as e:
                    logger.warning(f"Failed to delete old file {filename}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ Auto-cleanup: {deleted_count} old files deleted (older than {max_age_hours}h)")
    
    except Exception as e:
        logger.error(f"Error during auto-cleanup: {e}")