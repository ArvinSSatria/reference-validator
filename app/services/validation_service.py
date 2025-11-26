import logging
import re
from werkzeug.utils import secure_filename
from flask_socketio import emit
from config import Config
from app.services.ai_service import split_references_with_ai, analyze_references_with_ai
from app.services.scimago_service import search_journal_in_scimago
from app.services.scopus_service import search_journal_in_scopus
from app.services.pdf_service import extract_references_from_pdf
from app.services.docx_service import extract_references_from_docx
from app.services.bibtex_service import generate_bibtex, generate_correct_format_example
from app.utils.text_utils import find_references_section

logger = logging.getLogger(__name__)


def process_validation_request(request, saved_file_stream=None, socketio=None, session_id=None):
    """
    Process validation request with optional real-time progress updates via SocketIO.
    
    Args:
        request: Flask request object
        saved_file_stream: Optional file stream
        socketio: Optional SocketIO instance for progress updates
        session_id: Optional session ID for client identification
    """
    def emit_progress(step, message, progress):
        """Helper to emit progress if socketio is available"""
        if socketio and session_id:
            socketio.emit('validation_progress', {
                'step': step,
                'message': message,
                'progress': progress,
                'session_id': session_id
            })
            logger.info(f"Progress emit: {message} ({progress}%)")
    
    # Step 1: Extract references
    emit_progress('extract', 'Mengekstrak referensi dari dokumen...', 10)
    
    # Langkah 1: Dapatkan SELURUH BLOK TEKS daftar pustaka dari input
    references_block, error = _get_references_from_request(request, saved_file_stream)
    if error:
        return {"error": error}
    if not references_block:
        return {"error": "Maaf, tidak ada konten referensi yang dapat ditemukan dalam file atau teks yang Anda berikan. Mohon pastikan dokumen berisi bagian daftar pustaka/referensi."}
    
    emit_progress('extract', 'Berhasil mengekstrak teks referensi', 20)
    
    try:
        # Step 2: Split references with AI
        emit_progress('split', 'Memisahkan entri referensi dengan AI...', 30)
        
        # Langkah 2: AI Call #1 - Split references
        references_list, error = split_references_with_ai(references_block)
        if error:
            return {"error": error}
        
        if not references_list:
            return {"error": "Maaf, AI tidak dapat mengidentifikasi entri referensi individual dari teks yang diberikan. Mohon pastikan format daftar pustaka Anda jelas dan dapat dibaca."}

        total_refs = len(references_list)
        emit_progress('split', f'Berhasil memisahkan {total_refs} referensi', 40)
        
        # Langkah 3: Ambil parameter validasi dari request
        min_ref_count = request.form.get('min_ref_count', Config.MIN_REFERENCE_COUNT, type=int)
        
        # Validasi jumlah referensi
        count = len(references_list)
        count_valid = min_ref_count <= count <= Config.MAX_REFERENCE_COUNT
        count_message = f"Jumlah referensi ({count}) sudah sesuai standar."
        if count < min_ref_count:
            count_message = f"Jumlah referensi ({count}) kurang dari minimum ({min_ref_count})."
        elif count > Config.MAX_REFERENCE_COUNT:
            count_message = f"Jumlah referensi ({count}) melebihi maksimum ({Config.MAX_REFERENCE_COUNT})."
        
        count_validation = {
            "is_count_appropriate": count_valid,
            "count_message": count_message
        }
        
        # Ambil parameter dari form
        style = request.form.get('style', 'APA')
        year_range = request.form.get('year_range', Config.REFERENCE_YEAR_THRESHOLD, type=int)
        journal_percent_threshold = request.form.get(
            'journal_percent', 
            Config.JOURNAL_PROPORTION_THRESHOLD, 
            type=float
        )
        
        # Step 3: Analyze references with AI
        emit_progress('analyze', f'Menganalisis {total_refs} referensi dengan AI...', 50)
        
        # Langkah 4: AI Call #2 - Analyze references
        batch_results_json, detected_style, error = analyze_references_with_ai(references_list, style, year_range)
        if error:
            return {"error": error}
        
        emit_progress('analyze', f'Selesai analisis AI', 70)
        
        # Step 4: Process and match with database
        emit_progress('validate', 'Memvalidasi dengan database ScimagoJR & Scopus...', 80)
        
        # Langkah 5: Process AI response & match dengan Scimago
        detailed_results = _process_ai_response(batch_results_json, references_list, style, detected_style)
        
        emit_progress('validate', 'Validasi database selesai', 90)
        
        # Step 5: Generate summary
        emit_progress('finalize', 'Menyusun hasil dan rekomendasi...', 95)
        
        # Langkah 6: Generate summary & recommendations
        summary, recommendations = _generate_summary_and_recommendations(
            detailed_results,
            count_validation,
            detected_style,  # Gunakan detected_style instead of style
            journal_percent_threshold,
            min_ref_count
        )

        emit_progress('complete', 'Validasi selesai!', 100)
        
        # Sertakan year_range ke hasil agar PDF annotator dapat menggunakannya
        return {
            "success": True,
            "summary": summary,
            "detailed_results": detailed_results,
            "recommendations": recommendations,
            "year_range": year_range
        }

    except Exception as e:
        logger.error(f"Error kritis saat pemrosesan AI: {e}", exc_info=True)
        # User-friendly error message
        error_msg = "Maaf, terjadi kesalahan saat memproses validasi referensi. "
        
        if "timeout" in str(e).lower():
            error_msg += "Koneksi timeout. Mohon coba lagi."
        elif "memory" in str(e).lower() or "resource" in str(e).lower():
            error_msg += "Dokumen terlalu besar untuk diproses. Mohon coba dengan dokumen yang lebih kecil."
        elif "api" in str(e).lower() or "quota" in str(e).lower():
            error_msg += "Layanan AI sedang bermasalah. Mohon coba lagi nanti atau hubungi administrator."
        else:
            error_msg += "Mohon coba lagi atau hubungi administrator jika masalah berlanjut."
        
        return {"error": error_msg}


def _get_references_from_request(request, file_stream=None):
    if 'file' in request.files and request.files['file'].filename:
        original_file_object = request.files['file']
        filename = secure_filename(original_file_object.filename)
        stream_to_read = file_stream or original_file_object
        
        # Validasi ekstensi
        if not ('.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS):
            return None, f"Maaf, format file '{filename.rsplit('.', 1)[1].upper() if '.' in filename else 'unknown'}' tidak didukung. Mohon gunakan file PDF atau DOCX."

        # Panggil fungsi yang sesuai berdasarkan NAMA FILE
        if filename.lower().endswith('.docx'):
            return extract_references_from_docx(stream_to_read)
        elif filename.lower().endswith('.pdf'):
            return extract_references_from_pdf(stream_to_read)
            
    if 'text' in request.form and request.form['text'].strip():
        full_text = request.form['text'].strip()
        paragraphs = [p.strip() for p in full_text.split('\n') if p.strip()]
        return find_references_section(paragraphs)
        
    return None, "Maaf, tidak ada file atau teks yang diberikan. Mohon pilih file PDF/DOCX atau masukkan teks referensi secara manual."


def _process_ai_response(batch_results_json, references_list, original_style, detected_style):
    detailed_results = []
    
    ACCEPTED_SCIMAGO_TYPES = {'journal', 'book series', 'trade journal', 'conference and proceeding'}

    for result_json in batch_results_json:
        ref_num = result_json.get("reference_number", 0)
        ref_text = references_list[ref_num - 1] if 0 < ref_num <= len(references_list) else "Teks tidak ditemukan"
        
        # Ambil full_reference dari AI response (untuk highlighting), fallback ke reference_list
        full_ref_text = result_json.get('full_reference', ref_text)
        
        year_match = re.search(r'(\d{4})', str(result_json.get('parsed_year', '')))
        parsed_year = int(year_match.group(1)) if year_match else None
        overall_score = result_json.get('overall_score', 0)
        journal_name = result_json.get('parsed_journal')
        ref_type = result_json.get('reference_type', 'other')
        
        is_indexed_scimago = False
        is_indexed_scopus = False
        scimago_link = None
        scopus_link = None
        quartile = None
        scimago_info = None
        scopus_info = None
        
        # Search di Scimago database HANYA untuk tipe journal/conference
        # SKIP untuk website, report, atau organisasi
        should_check_databases = journal_name and ref_type in {'journal', 'conference', 'book series'}
        
        if should_check_databases:
            # Check Scimago
            is_indexed_scimago, scimago_info = search_journal_in_scimago(journal_name)
            if is_indexed_scimago and scimago_info:
                scimago_link = f"https://www.scimagojr.com/journalsearch.php?q={scimago_info['id']}&tip=sid"
                quartile = scimago_info['quartile']
                ref_type = scimago_info['type']
            
            # Check Scopus
            is_indexed_scopus, scopus_info = search_journal_in_scopus(journal_name)
            if is_indexed_scopus and scopus_info:
                # Format link Scopus yang benar menggunakan search parameter
                source_id = scopus_info['id']
                source_title = scopus_info.get('title', journal_name)
                # Encode title untuk URL
                import urllib.parse
                encoded_title = urllib.parse.quote(source_title)
                scopus_link = f"https://www.scopus.com/source/sourceInfo.uri?sourceId={source_id}"
                # Jika belum ada ref_type dari Scimago, gunakan dari Scopus
                if not is_indexed_scimago:
                    ref_type = scopus_info['type']
        
        # Gabungkan hasil - dianggap terindeks jika salah satu database menemukan
        is_indexed = is_indexed_scimago or is_indexed_scopus
        
        # Validasi overall
        ai_assessment_valid = all([
            result_json.get('is_format_correct', False),
            result_json.get('is_complete', False),
            result_json.get('is_year_recent', False),
        ])
        
        is_overall_valid = False
        final_feedback = result_json.get('feedback', 'Analisis AI selesai.')
        
        # Tambahkan catatan jika menggunakan mode Auto
        if original_style == 'Auto':
            final_feedback += f"\nMengikuti gaya sitasi yang terdeteksi: {detected_style} (Auto)"
        
        # Check kondisi untuk generate format example dan BibTeX
        is_format_correct = result_json.get('is_format_correct', False)
        is_complete = result_json.get('is_complete', False)
        
        format_example = None
        bibtex_string = None
        bibtex_available = False
        bibtex_partial = False
        bibtex_warning = None
        
        if is_complete and not is_format_correct and original_style != 'Auto':
            # Kondisi 1: Lengkap tapi format salah → Berikan contoh format yang benar
            try:
                # Extract volume, issue, pages dari AI response
                parsed_volume = result_json.get('parsed_volume')
                parsed_issue = result_json.get('parsed_issue')
                parsed_pages = result_json.get('parsed_pages')
                
                format_example = generate_correct_format_example(
                    authors=result_json.get('parsed_authors', []),
                    year=parsed_year or 2024,
                    title=result_json.get('parsed_title', 'Article Title'),
                    journal=journal_name or 'Journal Name',
                    style=detected_style,
                    volume=parsed_volume if parsed_volume else '10',
                    issue=parsed_issue if parsed_issue else '2',
                    pages=parsed_pages if parsed_pages else '1-10'
                )
                final_feedback += f"\nContoh format {detected_style} yang benar: {format_example}"
            except Exception as e:
                logger.warning(f"Gagal generate format example: {e}")
        
        should_generate_bibtex = False
        
        if is_complete and not is_format_correct:
            # Lengkap tapi format salah → Full BibTeX
            should_generate_bibtex = True
            bibtex_available = True
            bibtex_partial = False
        elif not is_complete:
            # Tidak lengkap → Partial BibTeX dengan warning
            should_generate_bibtex = True
            bibtex_available = True
            bibtex_partial = True
            missing_str = ", ".join(result_json.get('missing_elements', ['beberapa elemen']))
            bibtex_warning = f" File .bib tidak lengkap. Elemen yang hilang: {missing_str}. Field dengan 'MISSING' harus diisi manual."
        
        if should_generate_bibtex:
            try:
                bibtex_string, is_partial_flag = generate_bibtex(
                    reference_data=result_json,
                    is_complete=is_complete
                )
                bibtex_partial = is_partial_flag
            except Exception as e:
                logger.error(f"Error generating BibTeX for ref #{ref_num}: {e}")
                bibtex_string = None
                bibtex_available = False
        
        if is_indexed and ref_type in ACCEPTED_SCIMAGO_TYPES:
            is_overall_valid = True
            
            # Buat keterangan indeks
            index_notes = []
            if is_indexed_scimago:
                index_notes.append(f"terindeks di ScimagoJR (Quartile {quartile})")
            if is_indexed_scopus:
                index_notes.append("terindeks di Scopus")
            
            index_text = " dan ".join(index_notes)
            
            if ai_assessment_valid:
                final_feedback += f" Status: VALID (Sumber tipe '{ref_type}' {index_text} dan memenuhi kriteria kualitas)."
            else:
                # Tetap VALID meskipun format/tahun tidak sempurna
                final_feedback += f" Status: VALID (Sumber {index_text})."
        elif is_indexed:
            final_feedback += f" Status: INVALID (Sumber ditemukan di database, namun tipenya ('{ref_type}') tidak umum digunakan sebagai referensi utama)."
        elif ref_type in {'website', 'report'}:
            # Untuk website/report, tidak perlu cek database
            final_feedback += f" Status: INVALID (Sumber ini adalah '{ref_type}' dan tidak terindeks di database jurnal ilmiah)."
        else:
            final_feedback += f" Status: INVALID (Sumber ini adalah '{ref_type}', namun tidak ditemukan di database ScimagoJR atau Scopus)."

        # Ambil raw_reference_text dari AI response (fallback ke full_reference jika tidak ada)
        raw_ref_text = result_json.get('raw_reference_text', full_ref_text)
        
        detailed_results.append({
            "reference_number": ref_num,
            "reference_text": ref_text,
            "raw_reference": raw_ref_text,  # NEW: Teks asli dengan line breaks
            "full_reference": full_ref_text,
            "status": "valid" if is_overall_valid else "invalid",
            "reference_type": ref_type,
            "parsed_year": parsed_year,
            "parsed_journal": journal_name,
            "overall_score": overall_score,
            "is_indexed": is_indexed,
            "is_indexed_scimago": is_indexed_scimago,
            "is_indexed_scopus": is_indexed_scopus,
            "scimago_link": scimago_link,
            "scopus_link": scopus_link,
            "quartile": quartile,
            "validation_details": {
                "format_correct": result_json.get('is_format_correct', False),
                "complete": result_json.get('is_complete', False),
                "year_recent": result_json.get('is_year_recent', False),
            },
            "missing_elements": result_json.get('missing_elements', []),
            "feedback": final_feedback,
            "format_example": format_example,  # NEW: Contoh format yang benar
            "bibtex_available": bibtex_available,  # NEW: Apakah ada BibTeX
            "bibtex_partial": bibtex_partial,  # NEW: Apakah BibTeX partial
            "bibtex_warning": bibtex_warning,  # NEW: Warning untuk partial BibTeX
            "bibtex_string": bibtex_string  # NEW: BibTeX content untuk download
        })
    
    return detailed_results


def _generate_summary_and_recommendations(
    detailed_results,
    count_validation,
    style,
    journal_percent_threshold,
    min_ref_count=None
):
    total = len(detailed_results)
    valid_count = sum(1 for r in detailed_results if r['status'] == 'valid')
    journal_count = sum(1 for r in detailed_results if r['reference_type'] == 'journal')
    journal_percentage = (journal_count / total) * 100 if total > 0 else 0
    meets_journal_req = journal_percentage >= journal_percent_threshold
    
    distribution = {
        "journal_percentage": round(journal_percentage, 1),
        "meets_journal_requirement": meets_journal_req
    }
    
    summary = {
        "total_references": total,
        "valid_references": valid_count,
        "invalid_references": total - valid_count,
        "processing_errors": 0,
        "validation_rate": round((valid_count / total) * 100, 1) if total > 0 else 0,
        "count_validation": count_validation,
        "distribution_analysis": distribution,
        "style_used": style,
        "journal_percent_threshold": journal_percent_threshold,
        "min_ref_count": min_ref_count or Config.MIN_REFERENCE_COUNT
    }
    
    recommendations = []
    if summary['validation_rate'] < 70:
        recommendations.append("⚠️ Tingkat validitas rendah. Banyak referensi perlu perbaikan format atau kelengkapan.")
    if not meets_journal_req:
        recommendations.append(
            f"📊 Proporsi jurnal ({journal_percentage:.1f}%) belum memenuhi syarat minimal "
            f"yang Anda tentukan ({journal_percent_threshold}%)."
        )
    if not count_validation['is_count_appropriate']:
        recommendations.append(f"📝 {count_validation['count_message']}")
    if not recommendations:
        recommendations.append("✅ Referensi sudah memenuhi standar kualitas umum. Siap untuk tahap selanjutnya.")
    
    return summary, recommendations
