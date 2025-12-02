import os
import io
import json
import time
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
import uuid
from app import app, socketio, logger
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
            result = process_validation_request(request, file_stream_for_processing, socketio=socketio, session_id=session_id)
            file_stream_for_processing.close()

        elif 'text' in request.form and request.form['text'].strip():
            result = process_validation_request(request, None, socketio=socketio, session_id=session_id)
        else:
            return jsonify({"error": "Tidak ada input yang diberikan."}), 400

        if "error" in result:
            return jsonify(result), 400
        
        # Simpan HASIL JSON ke file untuk semua input (file atau text)
        upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            
        results_filepath = os.path.abspath(os.path.join(upload_folder, f"{session_id}_results.json"))
        # Tambahkan input_filename ke result sebelum disimpan
        if input_filename:
            result['input_filename'] = input_filename
        
        with open(results_filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        # Simpan path file hasil di sesi (untuk text input dan file input)
        session['results_filepath'] = results_filepath
        session['session_id'] = session_id
        if input_filename:
            session['input_filename'] = input_filename
        
        # Tambahkan session_id dan metadata ke response untuk client
        result['session_id'] = session_id
        result['has_file'] = original_filepath is not None
        result['input_filename'] = input_filename  # Tambahkan ke response
        
        # Tidak generate PDF di background - langsung generate saat download
        result['pdf_status'] = 'on_demand'  # PDF akan dibuat saat user klik download
            
        logger.info(f"Validation successful for {result['summary']['total_references']} references.")
        return jsonify(result)

    except Exception as e:
        error_type = type(e).__name__
        logger.critical(f"Unhandled exception in /api/validate: {e}", exc_info=True)
        
        # Berikan pesan error yang lebih spesifik berdasarkan jenis error
        if "Memory" in error_type or "MemoryError" in str(e):
            error_msg = "File terlalu besar atau referensi terlalu banyak. Coba gunakan file dengan ukuran lebih kecil atau referensi lebih sedikit."
        elif "Timeout" in error_type or "timeout" in str(e).lower():
            error_msg = "Waktu pemrosesan habis. Server AI mungkin sedang sibuk. Mohon tunggu beberapa saat lalu coba lagi."
        elif "API" in str(e) or "quota" in str(e).lower():
            error_msg = "Terjadi masalah koneksi ke layanan AI. Mohon coba lagi dalam beberapa saat."
        elif "pdf" in str(e).lower() or "PDF" in str(e):
            error_msg = "Gagal membaca file PDF. Pastikan file tidak corrupt dan dapat dibuka dengan PDF reader."
        elif "docx" in str(e).lower() or "DOCX" in str(e):
            error_msg = "Gagal membaca file DOCX. Pastikan file tidak corrupt dan dapat dibuka dengan Microsoft Word."
        else:
            error_msg = f"Kesalahan sistem: {error_type}. Mohon coba lagi atau hubungi administrator jika masalah berlanjut."
        
        return jsonify({"error": error_msg}), 500


@app.route('/api/download_report', methods=['GET'])
def download_report_api():
    try:
        # Coba ambil session_id dari query parameter dulu, fallback ke session
        session_id = request.args.get('session_id')
        
        logger.info(f"Download report request - session_id: {session_id}")
        
        if session_id:
            # Mode query parameter (untuk Electron compatibility)
            upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
            results_filepath = os.path.abspath(os.path.join(upload_folder, f"{session_id}_results.json"))
            
            # Validasi file results existence
            if not os.path.exists(results_filepath):
                logger.error(f"Results file not found: {results_filepath}")
                return jsonify({"error": "Sesi tidak valid atau file sudah terhapus. Lakukan validasi ulang."}), 400
            
            # Cari file original dengan pattern matching (bisa .pdf, .docx, atau ekstensi lain)
            original_filepath = None
            for ext in ['.pdf', '.docx', '.PDF', '.DOCX']:
                potential_path = os.path.abspath(os.path.join(upload_folder, f"{session_id}_original{ext}"))
                if os.path.exists(potential_path):
                    original_filepath = potential_path
                    logger.info(f"Found original file: {original_filepath}")
                    break
            
            if not original_filepath:
                logger.error(f"Original file not found for session_id: {session_id}")
                return jsonify({
                    "error": "File asli tidak ditemukan. Download PDF hanya tersedia untuk file upload (PDF/DOCX)."
                }), 400
        else:
            # Mode session cookie (backward compatibility untuk web)
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

        # Generate PDF on-demand (langsung saat download)
        logger.info(f"[Download] Generating PDF on-demand for session {session_id or 'legacy'}")
        logger.info(f"[Download] Original filepath: {original_filepath}")
        logger.info(f"[Download] File exists: {os.path.exists(original_filepath)}")
        
        # Handle DOCX conversion (returns io.BytesIO)
        if original_filepath.lower().endswith('.docx'):
            logger.info(f"[Download] Converting DOCX to PDF first...")
            pdf_bytes_stream, error = convert_docx_to_pdf(original_filepath)
            if error: 
                logger.error(f"[Download] DOCX conversion error: {error}")
                return jsonify({"error": error}), 500
            
            # Save stream to temp file untuk annotasi
            temp_pdf_path = original_filepath.replace('.docx', '_temp.pdf')
            with open(temp_pdf_path, 'wb') as f:
                f.write(pdf_bytes_stream.getvalue())
            
            pdf_to_annotate_path = temp_pdf_path
            logger.info(f"[Download] DOCX converted, temp PDF: {pdf_to_annotate_path}")
        else:
            pdf_to_annotate_path = original_filepath

        logger.info(f"[Download] Creating annotated PDF...")
        annotated_pdf_bytes, error = create_annotated_pdf(
            pdf_to_annotate_path, 
            validation_results
        )
        
        # Cleanup temp PDF dari DOCX conversion
        if original_filepath.lower().endswith('.docx') and os.path.exists(pdf_to_annotate_path):
            os.remove(pdf_to_annotate_path)
        
        if error: 
            logger.error(f"[Download] Annotation error: {error}")
            return jsonify({"error": error}), 500

        logger.info(f"[Download] PDF created successfully, size: {len(annotated_pdf_bytes)} bytes")
        
        # Gunakan nama file asli dari validation results jika ada
        original_filename = validation_results.get('input_filename', os.path.basename(original_filepath))
        base_name, _ = os.path.splitext(original_filename)
        download_filename = f"annotated_{base_name}.pdf"

        logger.info(f"[Download] Sending PDF to client: {download_filename}")
        return send_file(
            io.BytesIO(annotated_pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=download_filename
        )

    except Exception as e:
        error_type = type(e).__name__
        logger.critical(f"Unhandled exception in /api/download_report: {e}", exc_info=True)
        
        # Berikan pesan error spesifik
        if "Memory" in error_type:
            error_msg = "File terlalu besar untuk diproses. Coba validasi ulang dengan file lebih kecil."
        elif "pdf" in str(e).lower() or "PDF" in str(e):
            error_msg = "Gagal membuat PDF beranotasi. File PDF mungkin memiliki format yang tidak didukung."
        elif "FileNotFoundError" in error_type:
            error_msg = "File tidak ditemukan. Mohon lakukan validasi ulang terlebih dahulu."
        else:
            error_msg = f"Gagal membuat laporan PDF: {error_type}. Mohon coba validasi ulang atau hubungi administrator."
        
        return jsonify({"error": error_msg}), 500


@app.route('/api/download_bibtex/<int:ref_number>', methods=['GET'])
def download_bibtex_api(ref_number):
    """
    Download BibTeX file untuk referensi tertentu (on-the-fly generation).
    
    Args:
        ref_number: Nomor referensi (1-indexed)
    """
    try:
        # Coba ambil session_id dari query parameter dulu, fallback ke session
        session_id = request.args.get('session_id')
        
        if session_id:
            # Mode query parameter (untuk Electron compatibility)
            upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
            results_filepath = os.path.join(upload_folder, f"{session_id}_results.json")
        else:
            # Mode session cookie (backward compatibility untuk web)
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
        return jsonify({"error": "Maaf, terjadi kesalahan saat mengunduh file BibTeX. Mohon coba lagi."}), 500

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