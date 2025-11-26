import os
import io
import json
import time
import threading
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
import uuid
from app import app, socketio, logger
from app.services.validation_service import process_validation_request
from app.services.pdf_service import create_annotated_pdf
from app.services.docx_service import convert_docx_to_pdf
from config import Config

# Global dict untuk track status PDF generation
# Format: {session_id: {'status': 'processing'|'ready'|'error', 'filepath': '...', 'error_msg': '...'}}
pdf_generation_status = {}

def _generate_pdf_background(session_id, results_filepath, original_filepath, input_filename):
    """
    Generate PDF di background thread setelah validasi selesai.
    Update status ke pdf_generation_status dict.
    """
    try:
        logger.info(f"[Background PDF] Starting generation for session {session_id}")
        pdf_generation_status[session_id] = {'status': 'processing', 'filepath': None, 'error_msg': None}
        
        # Emit progress via SocketIO
        socketio.emit('pdf_generation_progress', {
            'status': 'processing',
            'message': 'Sedang menyiapkan PDF beranotasi...',
            'session_id': session_id
        })
        
        # Load hasil validasi
        with open(results_filepath, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
        pdf_filepath = None
        
        # Buat annotated PDF jika ada file asli
        if original_filepath and os.path.exists(original_filepath):
            if input_filename.lower().endswith('.docx'):
                # Convert DOCX to PDF dulu
                base_pdf_stream, error = convert_docx_to_pdf(original_filepath)
                if error:
                    raise Exception(error)
                
                # Annotate PDF
                annotated_pdf_stream, error = create_annotated_pdf(
                    base_pdf_stream,
                    result.get('detailed_results', []),
                    result.get('year_range', 10)
                )
                if error:
                    raise Exception(error)
                
                # Save to file
                pdf_filepath = os.path.abspath(os.path.join(upload_folder, f"{session_id}_annotated.pdf"))
                with open(pdf_filepath, 'wb') as f:
                    f.write(annotated_pdf_stream.getvalue())
                    
            elif input_filename.lower().endswith('.pdf'):
                # Direct PDF annotation
                annotated_pdf_stream, error = create_annotated_pdf(
                    original_filepath,
                    result.get('detailed_results', []),
                    result.get('year_range', 10)
                )
                if error:
                    raise Exception(error)
                
                # Save to file
                pdf_filepath = os.path.abspath(os.path.join(upload_folder, f"{session_id}_annotated.pdf"))
                with open(pdf_filepath, 'wb') as f:
                    f.write(annotated_pdf_stream.getvalue())
        
        # Update status ke ready
        pdf_generation_status[session_id] = {
            'status': 'ready',
            'filepath': pdf_filepath,
            'error_msg': None
        }
        
        # Emit success via SocketIO
        socketio.emit('pdf_generation_progress', {
            'status': 'ready',
            'message': 'PDF beranotasi siap diunduh!',
            'session_id': session_id
        })
        
        logger.info(f"[Background PDF] Generation completed for session {session_id}")
        
    except Exception as e:
        logger.error(f"[Background PDF] Error generating PDF for session {session_id}: {e}", exc_info=True)
        pdf_generation_status[session_id] = {
            'status': 'error',
            'filepath': None,
            'error_msg': str(e)
        }
        
        # Emit error via SocketIO
        socketio.emit('pdf_generation_progress', {
            'status': 'error',
            'message': 'Gagal menyiapkan PDF. Download akan dibuat saat Anda klik tombol.',
            'session_id': session_id
        })


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
        with open(results_filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        # Simpan path file hasil di sesi (untuk text input dan file input)
        session['results_filepath'] = results_filepath
        session['session_id'] = session_id
        
        # Tambahkan session_id dan metadata ke response untuk client
        result['session_id'] = session_id
        result['has_file'] = original_filepath is not None
        
        # HYBRID: Start background PDF generation jika ada file
        if original_filepath and os.path.exists(original_filepath):
            background_thread = threading.Thread(
                target=_generate_pdf_background,
                args=(session_id, results_filepath, original_filepath, input_filename)
            )
            background_thread.daemon = True
            background_thread.start()
            logger.info(f"[Background PDF] Thread started for session {session_id}")
            result['pdf_status'] = 'processing'  # Info untuk frontend
        else:
            result['pdf_status'] = 'not_available'  # Text input tidak ada PDF
            
        logger.info(f"Validation successful for {result['summary']['total_references']} references.")
        return jsonify(result)

    except Exception as e:
        logger.critical(f"Unhandled exception in /api/validate: {e}", exc_info=True)
        return jsonify({"error": "Terjadi kesalahan internal tak terduga."}), 500


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

        # HYBRID: Check apakah PDF sudah di-generate di background
        pdf_ready = False
        annotated_pdf_path = None
        
        if session_id and session_id in pdf_generation_status:
            status_info = pdf_generation_status[session_id]
            if status_info['status'] == 'ready' and status_info['filepath'] and os.path.exists(status_info['filepath']):
                # PDF sudah ready dari background generation
                annotated_pdf_path = status_info['filepath']
                pdf_ready = True
                logger.info(f"[Download] Using pre-generated PDF from background for session {session_id}")
        
        # Jika PDF belum ready, generate on-the-fly (fallback)
        if not pdf_ready:
            logger.info(f"[Download] Generating PDF on-the-fly for session {session_id or 'legacy'}")
            pdf_to_annotate_path = original_filepath
            is_temp_pdf = False

            if original_filepath.lower().endswith('.docx'):
                pdf_path, error = convert_docx_to_pdf(original_filepath)
                if error: return jsonify({"error": error}), 500
                pdf_to_annotate_path = pdf_path
                is_temp_pdf = True

            annotated_pdf_stream, error = create_annotated_pdf(
                pdf_to_annotate_path, 
                validation_results.get('detailed_results', []),
                validation_results.get('year_range', 10)
            )
            
            if is_temp_pdf and os.path.exists(pdf_to_annotate_path):
                os.remove(pdf_to_annotate_path)
            
            if error: return jsonify({"error": error}), 500

            base_name, _ = os.path.splitext(os.path.basename(original_filepath))
            download_filename = f"annotated_{base_name}.pdf"

            return send_file(
                annotated_pdf_stream,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=download_filename
            )
        else:
            # Send pre-generated PDF file
            base_name, _ = os.path.splitext(os.path.basename(original_filepath))
            download_filename = f"annotated_{base_name}.pdf"

            return send_file(
                annotated_pdf_path,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=download_filename
            )

    except Exception as e:
        logger.critical(f"Unhandled exception in /api/download_report: {e}", exc_info=True)
        return jsonify({"error": "Gagal membuat laporan PDF karena kesalahan server."}), 500


@app.route('/api/pdf_status', methods=['GET'])
def check_pdf_status():
    """
    Check status PDF generation di background.
    Returns: {'status': 'processing'|'ready'|'error'|'not_found', 'message': '...'}
    """
    try:
        session_id = request.args.get('session_id')
        if not session_id:
            return jsonify({"error": "session_id diperlukan"}), 400
        
        if session_id not in pdf_generation_status:
            return jsonify({
                "status": "not_found",
                "message": "Belum ada proses PDF generation untuk sesi ini"
            })
        
        status_info = pdf_generation_status[session_id]
        response = {
            "status": status_info['status']
        }
        
        if status_info['status'] == 'processing':
            response['message'] = 'PDF sedang disiapkan di background...'
        elif status_info['status'] == 'ready':
            response['message'] = 'PDF siap diunduh!'
        elif status_info['status'] == 'error':
            response['message'] = 'Gagal menyiapkan PDF. Download akan dibuat saat Anda klik tombol.'
            response['error_detail'] = status_info.get('error_msg', 'Unknown error')
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error checking PDF status: {e}", exc_info=True)
        return jsonify({"error": "Gagal mengecek status PDF"}), 500


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