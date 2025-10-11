import os
import google.generativeai as genai
import io
import json
import re
import logging
from datetime import datetime
import pandas as pd
import docx
from werkzeug.utils import secure_filename
from config import Config

logger = logging.getLogger(__name__)

SCIMAGO_DATA = {
    "by_title": {}, # Untuk menyimpan {judul: id}
    "by_cleaned_title": {} # Untuk menyimpan {judul_bersih: id}
}

_MODEL_CACHE = None

def _clean_scimago_title(title):
    return re.sub(r'[\.,\(\)]', '', title.lower()).strip()

def load_scimago_data():
    global SCIMAGO_DATA
    try:
        df = pd.read_csv(Config.SCIMAGO_FILE_PATH, sep=';', encoding='utf-8')
        if 'Sourceid' in df.columns and 'Title' in df.columns:
            df.dropna(subset=['Sourceid', 'Title'], inplace=True)
            for _, row in df.iterrows():
                title = row['Title'].strip()
                source_id = row['Sourceid']
                
                # Simpan data asli
                SCIMAGO_DATA["by_title"][title.lower()] = source_id
                # Simpan data yang sudah dibersihkan untuk pencarian
                cleaned_title = _clean_scimago_title(title)
                SCIMAGO_DATA["by_cleaned_title"][cleaned_title] = source_id

            logger.info(f"Dataset ScimagoJR berhasil dimuat dengan {len(SCIMAGO_DATA['by_title'])} jurnal.")
        else:
            logger.error("Kolom 'Sourceid' atau 'Title' tidak ditemukan.")
    except Exception as e:
        logger.error(f"Error saat memuat database ScimagoJR: {e}")

load_scimago_data()

def get_generative_model():
    global _MODEL_CACHE
    if _MODEL_CACHE:
        return _MODEL_CACHE

    try:
        genai.configure(
            api_key=Config.GEMINI_API_KEY,
            transport='rest'
        )
        
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        preferred_models = [
            'models/gemini-flash-latest',
            'models/gemini-2.5-pro',
        ]
        
        model_to_use = None
        for model in preferred_models:
            if model in available_models:
                model_to_use = model
                break
        
        if not model_to_use:
            logger.warning("Model preferensi tidak ditemukan, menggunakan model pertama yang tersedia.")
            if not available_models:
                raise Exception("Tidak ada model yang tersedia di akun Anda.")
            model_to_use = available_models[0]

        logger.info(f"Menginisialisasi dan caching model: {model_to_use}")
        _MODEL_CACHE = genai.GenerativeModel(model_to_use)
        return _MODEL_CACHE

    except Exception as e:
        logger.critical(f"Gagal total menginisialisasi model Gemini: {e}")
        raise e

def _clean_reference_text(text):
    text = re.sub(r'^\[\d+\]\s*|^\(\d+\)\s*|^\d+\.\s*|^\d+\)\s*', '', text.strip()) 
    text = re.sub(r'\s+', ' ', text) 
    return text.strip()

def _is_likely_reference(text):
    text = text.strip()
    if len(text) < 25:
        return False
    if re.match(r'^\[\d+\]|^\(\d+\)|^\d+\.', text):
        return True
    if re.search(r'\(\d{4}\)|\.\s\d{4}\.', text):
        if re.search(r'[A-Z][a-z]+,\s[A-Z]\.', text):
            return True
    if 'doi.org' in text.lower():
        return True
    return False

def _extract_references_from_docx(file_stream):
    try:
        doc = docx.Document(io.BytesIO(file_stream.read()))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        
        REFERENCE_HEADINGS = ["daftar pustaka", "referensi", "bibliography", "references", "pustaka rujukan"]
        
        references_text = []
        start_index = -1

        for i, para in enumerate(paragraphs):
            if any(h in para.lower() for h in REFERENCE_HEADINGS) and len(para) < 30:
                found_first_ref = False
                for j in range(1, 6):
                    if (i + j) < len(paragraphs):
                        next_para = paragraphs[i + j]
                        if _is_likely_reference(next_para):
                            start_index = i + j
                            found_first_ref = True
                            logger.info(f"Judul '{para}' divalidasi. Referensi pertama ditemukan di paragraf #{start_index}.")
                            break
                if found_first_ref:
                    break
        
        if start_index == -1:
            return None, "Judul bagian 'Daftar Pustaka' tidak ditemukan atau tidak diikuti oleh konten referensi yang valid."

        references_text.append(_clean_reference_text(paragraphs[start_index]))
        
        consecutive_non_ref_count = 0
        for i in range(start_index + 1, len(paragraphs)):
            para = paragraphs[i]
            
            if _is_likely_reference(para):
                cleaned = _clean_reference_text(para)
                references_text.append(cleaned)
                consecutive_non_ref_count = 0
            else:
                consecutive_non_ref_count += 1
            
            if consecutive_non_ref_count >= 3:
                logger.info(f"Berhenti menangkap setelah menemukan {consecutive_non_ref_count} paragraf non-referensi berturut-turut.")
                break
        
        logger.info(f"Berhasil mengekstrak {len(references_text)} referensi dari DOCX (metode cerdas v2).")
        return references_text, None

    except Exception as e:
        logger.error(f"Gagal memproses file .docx: {e}", exc_info=True)
        return None, f"Gagal memproses file .docx: {e}"

def _get_references_from_request(request):
    if 'file' in request.files and request.files['file'].filename:
        file = request.files['file']
        filename = secure_filename(file.filename)
        if not filename.lower().endswith('.docx'):
            return None, "Saat ini hanya mendukung file .docx"
        return _extract_references_from_docx(file)
    if 'text' in request.form and request.form['text'].strip():
        text_input = request.form['text'].strip()
        ref_list = [_clean_reference_text(r) for r in text_input.split('\n') if r.strip()]
        return ref_list, None
    return None, "Tidak ada input yang diberikan."

def _construct_batch_gemini_prompt(references_list, style):
    year_threshold = datetime.now().year - Config.REFERENCE_YEAR_THRESHOLD
    formatted_references = "\n".join([f"{i+1}. {ref}" for i, ref in enumerate(references_list)])
    return f"""
    Anda adalah sistem AI ahli untuk validasi referensi ilmiah. Analisis DAFTAR REFERENSI berikut dan kembalikan hasil sebagai SEBUAH ARRAY JSON TUNGGAL yang valid.
    ATURAN VALIDASI:
    1. FORMAT: Sesuai gaya sitasi '{style}'.
    2. KELENGKAPAN: Harus memuat elemen wajib berdasarkan jenisnya:
        - Untuk 'journal': Penulis, Tahun, Judul Artikel, Nama Jurnal, Volume, Nomor Isu (jika ada), dan **Rentang Halaman**.
        - Untuk 'book': Penulis/Editor, Tahun, Judul Buku, Penerbit.
        - Untuk 'conference': Penulis, Tahun, Judul Paper, Nama Konferensi.
        Beri `false` pada `is_complete` dan sebutkan elemen yang hilang di `missing_elements` jika tidak terpenuhi.
    3. TAHUN TERBIT:
        - Untuk 'journal' dan 'conference': Dianggap terkini jika >= {year_threshold} (sangat disarankan). Beri `false` pada `is_year_recent` jika lebih tua.
        - Untuk 'book': Aturan tahun lebih longgar. `is_year_recent` bisa `true` bahkan jika lebih tua dari {year_threshold}, terutama jika itu adalah buku teks fundamental atau edisi terbaru.
    4. JENIS SUMBER: Harus dari sumber yang kredibel dan otoritatif.
        ✓ Jurnal peer-reviewed, Buku akademik, Proceeding konferensi
        ✓ Website dari organisasi pemerintah, akademik, atau internasional yang dikenal (seperti WHO, PBB, universitas)
        ✗ Blog pribadi, Wikipedia, media sosial, situs komersial
    DAFTAR REFERENSI YANG DIANALISIS:
    ---
    {formatted_references}
    ---
    INSTRUKSI OUTPUT:
    Berikan respons HANYA dalam format array JSON. Setiap objek dalam array harus memiliki struktur berikut:
    {{
        "reference_number": <int>,
        "reference_text": "<string>",
        "parsed_year": <int> atau null,
        "parsed_journal": "<string>" atau null,
        "reference_type": "journal/book/conference/website/other",
        "is_format_correct": <boolean>,
        "is_complete": <boolean>,
        "is_year_recent": <boolean>,
        "is_scientific_source": <boolean>,
        "overall_score": <int, 0-100, nilai berdasarkan kelengkapan DAN kesesuaian format>,
        "missing_elements": ["<string>"],
        "feedback": "<string>"
    }}
    """

def _process_ai_response(batch_results_json, references_list):
    detailed_results = []
    for result_json in batch_results_json:
        ref_num = result_json.get("reference_number", 0)
        ref_text = references_list[ref_num - 1] if 0 < ref_num <= len(references_list) else "Teks tidak ditemukan"
        year_match = re.search(r'(\d{4})', str(result_json.get('parsed_year', '')))
        parsed_year = int(year_match.group(1)) if year_match else None
        overall_score = result_json.get('overall_score', 0)
        
        journal_name = result_json.get('parsed_journal')
        ref_type = result_json.get('reference_type', 'other')
        
        is_indexed = False
        scimago_link = None
        
        if journal_name and SCIMAGO_DATA["by_cleaned_title"]:
            cleaned_journal_name = _clean_scimago_title(journal_name)
            
            # 1: Coba pencocokan persis (paling akurat)
            if cleaned_journal_name in SCIMAGO_DATA["by_cleaned_title"]:
                is_indexed = True
                source_id = SCIMAGO_DATA["by_cleaned_title"][cleaned_journal_name]
                scimago_link = f"https://www.scimagojr.com/journalsearch.php?q={source_id}&tip=sid"
            
            # 2: Jika gagal, coba pencocokan 'in' yang lebih longgar
            else:
                for cleaned_title_db, source_id in SCIMAGO_DATA["by_cleaned_title"].items():
                    if len(cleaned_journal_name) > 4 and cleaned_journal_name in cleaned_title_db:
                        is_indexed = True
                        scimago_link = f"https://www.scimagojr.com/journalsearch.php?q={source_id}&tip=sid"
                        break
        
        ai_assessment_valid = all([
            result_json.get('is_format_correct', False),
            result_json.get('is_complete', False),
            result_json.get('is_year_recent', False),
            result_json.get('is_scientific_source', True)
        ])
        
        is_overall_valid = False
        final_feedback = result_json.get('feedback', 'Analisis AI selesai.')
        
        if ref_type == 'journal':
            if ai_assessment_valid and is_indexed:
                is_overall_valid = True
                final_feedback += " Status: VALID (Jurnal terindeks di ScimagoJR dan memenuhi semua kriteria kualitas)."
            elif not is_indexed:
                final_feedback += " Status: INVALID (Jurnal tidak ditemukan di database ScimagoJR 2024)."
            else:
                final_feedback += " Status: INVALID (Meskipun jurnal terindeks, format/kelengkapan/tahun tidak memenuhi syarat.)"
        else:
            is_overall_valid = False
            final_feedback += f" Status: INVALID (Sumber ini adalah '{ref_type}', bukan jurnal terindeks ScimagoJR.)"

        detailed_results.append({
            "reference_number": ref_num,
            "reference_text": ref_text,
            "status": "valid" if is_overall_valid else "invalid",
            "reference_type": ref_type,
            "parsed_year": parsed_year,
            "parsed_journal": journal_name,
            "overall_score": overall_score,
            "is_indexed": is_indexed,
            "scimago_link": scimago_link,
            "validation_details": {
                "format_correct": result_json.get('is_format_correct', False),
                "complete": result_json.get('is_complete', False),
                "year_recent": result_json.get('is_year_recent', False),
                "scientific_source": result_json.get('is_scientific_source', False) # Tetap tampilkan ini
            },
            "missing_elements": result_json.get('missing_elements', []),
            "feedback": final_feedback
        })
    return detailed_results

def _generate_summary_and_recommendations(detailed_results, count_validation, style):
    total = len(detailed_results)
    valid_count = sum(1 for r in detailed_results if r['status'] == 'valid')
    journal_count = sum(1 for r in detailed_results if r['reference_type'] == 'journal')
    journal_percentage = (journal_count / total) * 100 if total > 0 else 0
    meets_journal_req = journal_percentage >= Config.JOURNAL_PROPORTION_THRESHOLD
    distribution = {"journal_percentage": round(journal_percentage, 1), "meets_journal_requirement": meets_journal_req}
    summary = {
        "total_references": total, "valid_references": valid_count, "invalid_references": total - valid_count,
        "processing_errors": 0, "validation_rate": round((valid_count / total) * 100, 1) if total > 0 else 0,
        "count_validation": count_validation, "distribution_analysis": distribution, "style_used": style
    }
    recommendations = []
    if summary['validation_rate'] < 70: recommendations.append("⚠️ Tingkat validitas rendah. Banyak referensi perlu perbaikan format atau kelengkapan.")
    if not meets_journal_req: recommendations.append(f"📊 Proporsi jurnal ({journal_percentage:.1f}%) belum memenuhi syarat minimal {Config.JOURNAL_PROPORTION_THRESHOLD}%.")
    if not count_validation['is_count_appropriate']: recommendations.append(f"📝 {count_validation['count_message']}")
    if not recommendations: recommendations.append("✅ Referensi sudah memenuhi standar kualitas umum. Siap untuk tahap selanjutnya.")
    return summary, recommendations


def process_validation_request(request):
    references_list, error = _get_references_from_request(request)
    if error: return {"error": error}
    if not references_list: return {"error": "Tidak ada referensi yang dapat diproses."}
    
    count = len(references_list)
    count_valid = Config.MIN_REFERENCE_COUNT <= count <= Config.MAX_REFERENCE_COUNT
    count_message = f"Jumlah referensi ({count}) sudah sesuai standar."
    if count < Config.MIN_REFERENCE_COUNT:
        count_message = f"Jumlah referensi ({count}) kurang dari minimum ({Config.MIN_REFERENCE_COUNT})."
    elif count > Config.MAX_REFERENCE_COUNT:
        count_message = f"Jumlah referensi ({count}) melebihi maksimum ({Config.MAX_REFERENCE_COUNT})."
    
    count_validation = {"is_count_appropriate": count_valid, "count_message": count_message}

    style = request.form.get('style', 'APA')
    logger.info(f"Memulai analisis BATCH untuk {len(references_list)} referensi (Gaya: {style}).")
    
    try:
        model = get_generative_model()
        
        prompt = _construct_batch_gemini_prompt(references_list, style)
        response = model.generate_content(prompt, generation_config={"temperature": 0.1})
        
        response_text = response.text.strip().replace('```json', '').replace('```', '').strip()
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if not json_match:
            raise ValueError("Respons AI tidak mengandung format array JSON yang valid.")
        
        batch_results_json = json.loads(json_match.group(0))
        
        detailed_results = _process_ai_response(batch_results_json, references_list)
        summary, recommendations = _generate_summary_and_recommendations(detailed_results, count_validation, style)

        return {
            "success": True,
            "summary": summary,
            "detailed_results": detailed_results,
            "recommendations": recommendations
        }

    except Exception as e:
        logger.error(f"Error kritis saat pemrosesan batch AI: {e}", exc_info=True)
        return {"error": f"Terjadi kesalahan saat berkomunikasi dengan AI. Detail: {e}"}