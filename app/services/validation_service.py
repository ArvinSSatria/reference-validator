import logging
import re
from werkzeug.utils import secure_filename
from config import Config
from app.services.ai_service import split_references_with_ai, analyze_references_with_ai
from app.services.scimago_service import search_journal_in_scimago
from app.services.pdf_service import extract_references_from_pdf
from app.services.docx_service import extract_references_from_docx
from app.utils.text_utils import find_references_section

logger = logging.getLogger(__name__)


def process_validation_request(request, saved_file_stream=None):
    # Langkah 1: Dapatkan SELURUH BLOK TEKS daftar pustaka dari input
    references_block, error = _get_references_from_request(request, saved_file_stream)
    if error:
        return {"error": error}
    if not references_block:
        return {"error": "Tidak ada konten referensi yang dapat diproses."}
    
    try:
        # Langkah 2: AI Call #1 - Split references
        references_list, error = split_references_with_ai(references_block)
        if error:
            return {"error": error}
        
        if not references_list:
            return {"error": "Tidak ada referensi individual yang dapat diidentifikasi oleh AI."}

        # Langkah 3: Validasi jumlah referensi
        count = len(references_list)
        count_valid = Config.MIN_REFERENCE_COUNT <= count <= Config.MAX_REFERENCE_COUNT
        count_message = f"Jumlah referensi ({count}) sudah sesuai standar."
        if count < Config.MIN_REFERENCE_COUNT:
            count_message = f"Jumlah referensi ({count}) kurang dari minimum ({Config.MIN_REFERENCE_COUNT})."
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
        
        # Langkah 4: AI Call #2 - Analyze references
        batch_results_json, detected_style, error = analyze_references_with_ai(references_list, style, year_range)
        if error:
            return {"error": error}
        
        # Langkah 5: Process AI response & match dengan Scimago
        detailed_results = _process_ai_response(batch_results_json, references_list, style, detected_style)
        
        # Langkah 6: Generate summary & recommendations
        summary, recommendations = _generate_summary_and_recommendations(
            detailed_results,
            count_validation,
            detected_style,  # Gunakan detected_style instead of style
            journal_percent_threshold
        )

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
        return {"error": f"Terjadi kesalahan saat pemrosesan AI. Detail: {e}"}


def _get_references_from_request(request, file_stream=None):
    if 'file' in request.files and request.files['file'].filename:
        original_file_object = request.files['file']
        filename = secure_filename(original_file_object.filename)
        stream_to_read = file_stream or original_file_object
        
        # Validasi ekstensi
        if not ('.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS):
            return None, "Format file tidak didukung."

        # Panggil fungsi yang sesuai berdasarkan NAMA FILE
        if filename.lower().endswith('.docx'):
            return extract_references_from_docx(stream_to_read)
        elif filename.lower().endswith('.pdf'):
            return extract_references_from_pdf(stream_to_read)
            
    if 'text' in request.form and request.form['text'].strip():
        full_text = request.form['text'].strip()
        paragraphs = [p.strip() for p in full_text.split('\n') if p.strip()]
        return find_references_section(paragraphs)
        
    return None, "Tidak ada input yang diberikan."


def _process_ai_response(batch_results_json, references_list, original_style, detected_style):
    """
    Process AI response and match dengan Scimago database.
    
    Args:
        batch_results_json: JSON response dari AI
        references_list: List referensi asli
        original_style: Style yang dipilih pengguna (bisa "Auto")
        detected_style: Style yang terdeteksi oleh AI
    """
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
        
        is_indexed = False
        scimago_link = None
        quartile = None
        journal_info = None
        
        # Search di Scimago database HANYA untuk tipe journal/conference
        # SKIP untuk website, report, atau organisasi
        should_check_scimago = journal_name and ref_type in {'journal', 'conference', 'book series'}
        
        if should_check_scimago:
            is_indexed, journal_info = search_journal_in_scimago(journal_name)
            if is_indexed and journal_info:
                scimago_link = f"https://www.scimagojr.com/journalsearch.php?q={journal_info['id']}&tip=sid"
                quartile = journal_info['quartile']
                ref_type = journal_info['type']
        
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
        
        # UPDATED LOGIC: Prioritas utama adalah terindeks di Scimago
        # Jika terindeks, langsung VALID (ignore format/tahun)
        if is_indexed and ref_type in ACCEPTED_SCIMAGO_TYPES:
            is_overall_valid = True
            if ai_assessment_valid:
                final_feedback += f" Status: VALID (Sumber tipe '{ref_type}' terindeks di ScimagoJR dan memenuhi kriteria kualitas)."
            else:
                # Tetap VALID meskipun format/tahun tidak sempurna
                final_feedback += f" Status: VALID (Sumber terindeks di ScimagoJR dengan Quartile {quartile})."
        elif is_indexed:
            final_feedback += f" Status: INVALID (Sumber ditemukan di ScimagoJR, namun tipenya ('{ref_type}') tidak umum digunakan sebagai referensi utama)."
        elif ref_type in {'website', 'report'}:
            # Untuk website/report, tidak perlu cek Scimago
            final_feedback += f" Status: INVALID (Sumber ini adalah '{ref_type}' dan tidak terindeks di database jurnal ilmiah ScimagoJR 2024)."
        else:
            final_feedback += f" Status: INVALID (Sumber ini adalah '{ref_type}', namun tidak ditemukan di database ScimagoJR 2024)."

        detailed_results.append({
            "reference_number": ref_num,
            "reference_text": ref_text,
            "full_reference": full_ref_text,  # TAMBAHAN: Full reference text untuk highlighting
            "status": "valid" if is_overall_valid else "invalid",
            "reference_type": ref_type,
            "parsed_year": parsed_year,
            "parsed_journal": journal_name,
            "overall_score": overall_score,
            "is_indexed": is_indexed,
            "scimago_link": scimago_link,
            "quartile": quartile,
            "validation_details": {
                "format_correct": result_json.get('is_format_correct', False),
                "complete": result_json.get('is_complete', False),
                "year_recent": result_json.get('is_year_recent', False),
            },
            "missing_elements": result_json.get('missing_elements', []),
            "feedback": final_feedback
        })
    
    return detailed_results


def _generate_summary_and_recommendations(
    detailed_results,
    count_validation,
    style,
    journal_percent_threshold
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
        "journal_percent_threshold": journal_percent_threshold
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
