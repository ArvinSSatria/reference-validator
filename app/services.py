import fitz  # PyMuPDF
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
    "by_title": {},
    "by_cleaned_title": {}
}
_MODEL_CACHE = None

def _clean_scimago_title(title):
    if not isinstance(title, str): return ""
    return re.sub(r'[\.,\(\)]', '', title.lower()).strip()

def load_scimago_data():
    global SCIMAGO_DATA
    try:
        df = pd.read_csv(Config.SCIMAGO_FILE_PATH, sep=';', encoding='utf-8')
         # Check for all required columns
        required_cols = ['Sourceid', 'Title', 'SJR Best Quartile']
        if all(col in df.columns for col in required_cols):
            df.dropna(subset=required_cols, inplace=True)
            for _, row in df.iterrows():
                title = row['Title'].strip()
                source_id = row['Sourceid']
                quartile = row['SJR Best Quartile']
                
                journal_info = {'id': source_id, 'quartile': quartile}
                
                SCIMAGO_DATA["by_title"][title.lower()] = journal_info
                cleaned_title = _clean_scimago_title(title)
                SCIMAGO_DATA["by_cleaned_title"][cleaned_title] = journal_info
                
            logger.info(f"Dataset ScimagoJR berhasil dimuat dengan {len(SCIMAGO_DATA['by_title'])} jurnal.")
        else:
            logger.error(f"Kolom yang dibutuhkan ('Sourceid', 'Title', 'SJR Best Quartile') tidak ditemukan.")
    except Exception as e:
        logger.error(f"Error saat memuat database ScimagoJR: {e}")

load_scimago_data()

def get_generative_model():
    global _MODEL_CACHE
    if _MODEL_CACHE: return _MODEL_CACHE
    try:
        genai.configure(api_key=Config.GEMINI_API_KEY, transport='rest')
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        preferred_models = ['models/gemini-flash-latest', 'models/gemini-pro', 'models/gemini-pro-latest']
        model_to_use = None
        for model in preferred_models:
            if model in available_models:
                model_to_use = model
                break
        if not model_to_use:
            logger.warning("Model preferensi tidak ditemukan, menggunakan model pertama yang tersedia.")
            if not available_models: raise Exception("Tidak ada model yang tersedia di akun Anda.")
            model_to_use = available_models[0]
        logger.info(f"Menginisialisasi dan caching model: {model_to_use}")
        _MODEL_CACHE = genai.GenerativeModel(model_to_use)
        return _MODEL_CACHE
    except Exception as e:
        logger.critical(f"Gagal total menginisialisasi model Gemini: {e}")
        raise e

# --- LOGIKA EKSTRAKSI BARU DENGAN METODE "PEMOTONGAN" ---

def _find_references_section_as_text_block(paragraphs):
    """Menemukan bagian daftar pustaka dan mengembalikannya sebagai SATU BLOK TEKS."""
    REFERENCE_HEADINGS = ["daftar pustaka", "referensi", "bibliography", "references", "pustaka rujukan"]
    start_index = -1

    for i, para in enumerate(paragraphs):
        # Cari judul yang berdiri sendiri
        if any(h in para.lower() for h in REFERENCE_HEADINGS) and len(para) < 30:
            start_index = i
            logger.info(f"Judul Daftar Pustaka ditemukan di paragraf #{i}: '{para}'")
            break
    
    if start_index == -1:
        return None, "Judul bagian 'Daftar Pustaka' tidak ditemukan dalam dokumen."

    # Gabungkan semua paragraf setelah judul menjadi satu string besar
    references_block = "\n".join(paragraphs[start_index + 1:])
    
    if not references_block.strip():
        return None, "Bagian 'Daftar Pustaka' ditemukan, tetapi kosong."

    return references_block, None

def _extract_references_from_docx(file_stream):
    """Membaca DOCX dan mengembalikan daftar pustaka sebagai satu blok teks."""
    try:
        doc = docx.Document(io.BytesIO(file_stream.read()))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return _find_references_section_as_text_block(paragraphs)
    except Exception as e:
        logger.error(f"Gagal memproses file .docx: {e}", exc_info=True)
        return None, f"Gagal memproses file .docx: {e}"

def _extract_references_from_pdf(file_stream):
    """Membaca PDF dan mengembalikan daftar pustaka sebagai satu blok teks."""
    try:
        pdf_bytes = file_stream.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        full_text = "".join(page.get_text("text") + "\n" for page in doc)
        doc.close()
        paragraphs = [p.strip() for p in full_text.split('\n') if p.strip()]
        return _find_references_section_as_text_block(paragraphs)
    except Exception as e:
        logger.error(f"Gagal memproses file .pdf: {e}", exc_info=True)
        return None, f"Gagal memproses file .pdf: {e}"

def _get_references_from_request(request):
    """Mengambil input sebagai SATU BLOK TEKS, baik dari file maupun textarea."""
    if 'file' in request.files and request.files['file'].filename:
        file = request.files['file']
        filename = secure_filename(file.filename)
        
        if not ('.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS):
            return None, "Format file tidak didukung."

        if filename.lower().endswith('.docx'):
            return _extract_references_from_docx(file)
        elif filename.lower().endswith('.pdf'):
            return _extract_references_from_pdf(file)
    
    if 'text' in request.form and request.form['text'].strip():
        # Jika input dari textarea, itu sudah menjadi blok teks
        return request.form['text'].strip(), None
        
    return None, "Tidak ada input yang diberikan."

# --- (Fungsi-fungsi analisis sisanya tetap sama: _construct_batch_gemini_prompt, _process_ai_response, dll.) ---
def _construct_batch_gemini_prompt(references_list, style, year_range):
    # ... (Kode tidak berubah) ...
    year_threshold = datetime.now().year - year_range
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
        - Untuk 'journal' dan 'conference': Dianggap terkini jika >= {year_threshold} ({year_range} tahun terakhir). Beri `false` pada `is_year_recent` jika lebih tua.
        - Untuk 'book': Aturan tahun lebih longgar. `is_year_recent` bisa `true` bahkan jika lebih tua dari {year_range} tahun, terutama jika itu adalah buku teks fundamental.
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

# Ganti seluruh fungsi ini di app/services.py

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
        quartile = None
        
        # Debug output
        print(f"\n[DEBUG] Memproses: '{journal_name}' (Tipe: {ref_type})")
        
        if journal_name and SCIMAGO_DATA["by_cleaned_title"]:
            cleaned_journal_name = _clean_scimago_title(journal_name)
            
            # Strategi 1: Coba pencocokan persis (paling akurat)
            if cleaned_journal_name in SCIMAGO_DATA["by_cleaned_title"]:
                is_indexed = True
                journal_info = SCIMAGO_DATA["by_cleaned_title"][cleaned_journal_name]
                scimago_link = f"https://www.scimagojr.com/journalsearch.php?q={journal_info['id']}&tip=sid"
                quartile = journal_info['quartile']
            
            # Strategi 2: Jika gagal, coba pencocokan 'in' yang lebih longgar
            else:
                # --- PERBAIKAN DI SINI ---
                for cleaned_title_db, journal_info in SCIMAGO_DATA["by_cleaned_title"].items():
                    if len(cleaned_journal_name) > 4 and cleaned_journal_name in cleaned_title_db:
                        is_indexed = True
                        scimago_link = f"https://www.scimagojr.com/journalsearch.php?q={journal_info['id']}&tip=sid"
                        quartile = journal_info['quartile'] # <-- BARIS YANG HILANG SEBELUMNYA
                        break
        
        # --- (Sisa kode tidak berubah) ---
        ai_assessment_valid = all([
            result_json.get('is_format_correct', False),
            result_json.get('is_complete', False),
            result_json.get('is_year_recent', False),
            result_json.get('is_scientific_source', False)
        ])
        
        is_overall_valid = False
        final_feedback = result_json.get('feedback', 'Analisis AI selesai.')
        if ref_type == 'journal':
            if ai_assessment_valid and is_indexed:
                is_overall_valid = True
                final_feedback += " Status: VALID (Jurnal terindeks di ScimagoJR dan memenuhi kriteria kualitas)."
            elif not is_indexed:
                final_feedback += " Status: INVALID (Jurnal tidak ditemukan di database ScimagoJR 2024)."
            else:
                final_feedback += " Status: INVALID (Meskipun jurnal terindeks, format/kelengkapan/tahun tidak memenuhi syarat.)"
        else:
            is_overall_valid = False
            final_feedback += f" Status: INVALID (Sumber ini adalah '{ref_type}', bukan jurnal terindeks ScimagoJR.)"
            
        detailed_results.append({
            "reference_number": ref_num, "reference_text": ref_text, "status": "valid" if is_overall_valid else "invalid",
            "reference_type": ref_type, "parsed_year": parsed_year, "parsed_journal": journal_name,
            "overall_score": overall_score, "is_indexed": is_indexed, "scimago_link": scimago_link, "quartile": quartile,
            "validation_details": {
                "format_correct": result_json.get('is_format_correct', False),
                "complete": result_json.get('is_complete', False),
                "year_recent": result_json.get('is_year_recent', False),
            },
            "missing_elements": result_json.get('missing_elements', []), "feedback": final_feedback
        })
    return detailed_results
    
def _generate_summary_and_recommendations(detailed_results, count_validation, style):
    # ... (Kode tidak berubah) ...
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

# --- FUNGSI UTAMA YANG DIUBAH TOTAL ---

def process_validation_request(request):
    """
    Fungsi orkestrator utama dengan metode "pemotongan" AI.
    """
    # Langkah 1: Dapatkan SELURUH BLOK TEKS daftar pustaka dari input
    references_block, error = _get_references_from_request(request)
    if error: return {"error": error}
    if not references_block: return {"error": "Tidak ada konten referensi yang dapat diproses."}
    
    try:
        model = get_generative_model()

        # Langkah 2: Panggilan AI #1 - "MEMOTONG" blok teks menjadi daftar referensi
        logger.info("Meminta AI untuk memisahkan referensi dari blok teks...")
        splitter_prompt = f"""
        Diberikan blok teks daftar pustaka berikut, pisahkan menjadi entri-entri referensi individual.
        Pastikan setiap entri adalah referensi yang lengkap.
        Kembalikan hasilnya sebagai sebuah array JSON dari string.
        Contoh output: ["Referensi lengkap pertama...", "Referensi lengkap kedua...", "Referensi lengkap ketiga..."]

        Teks untuk dipisahkan:
        ---
        {references_block}
        ---
        """
        response = model.generate_content(splitter_prompt)
        
        # Ekstraksi JSON yang lebih tangguh
        json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if not json_match:
            logger.error(f"AI gagal memisahkan referensi. Respons mentah: {response.text}")
            raise ValueError("AI gagal memisahkan referensi ke dalam format JSON array.")
        
        references_list = json.loads(json_match.group(0))
        logger.info(f"AI berhasil memisahkan menjadi {len(references_list)} referensi.")
        
        if not references_list:
            return {"error": "Tidak ada referensi individual yang dapat diidentifikasi oleh AI."}

        # Langkah 3: Lanjutkan dengan alur yang sudah ada, menggunakan `references_list` yang baru
        count = len(references_list)
        count_valid = Config.MIN_REFERENCE_COUNT <= count <= Config.MAX_REFERENCE_COUNT
        count_message = f"Jumlah referensi ({count}) sudah sesuai standar."
        if count < Config.MIN_REFERENCE_COUNT:
            count_message = f"Jumlah referensi ({count}) kurang dari minimum ({Config.MIN_REFERENCE_COUNT})."
        elif count > Config.MAX_REFERENCE_COUNT:
            count_message = f"Jumlah referensi ({count}) melebihi maksimum ({Config.MAX_REFERENCE_COUNT})."
        count_validation = {"is_count_appropriate": count_valid, "count_message": count_message}
        
        style = request.form.get('style', 'APA')
        year_range = request.form.get('year_range', Config.REFERENCE_YEAR_THRESHOLD, type=int)
        
        # Langkah 4: Panggilan AI #2 - MENGANALISIS daftar yang sudah bersih
        logger.info(f"Memulai analisis BATCH untuk {len(references_list)} referensi (Gaya: {style}).")
        analyzer_prompt = _construct_batch_gemini_prompt(references_list, style, year_range)
        analysis_response = model.generate_content(analyzer_prompt, generation_config={"temperature": 0.1})
        
        analysis_json_match = re.search(r'\[.*\]', analysis_response.text, re.DOTALL)
        if not analysis_json_match:
            logger.error(f"AI gagal menganalisis referensi. Respons mentah: {analysis_response.text}")
            raise ValueError("AI gagal menganalisis referensi ke dalam format JSON array.")
        
        batch_results_json = json.loads(analysis_json_match.group(0))
        detailed_results = _process_ai_response(batch_results_json, references_list)
        summary, recommendations = _generate_summary_and_recommendations(detailed_results, count_validation, style)

        return {
            "success": True,
            "summary": summary,
            "detailed_results": detailed_results,
            "recommendations": recommendations
        }

    except Exception as e:
        logger.error(f"Error kritis saat pemrosesan AI: {e}", exc_info=True)
        return {"error": f"Terjadi kesalahan saat pemrosesan AI. Detail: {e}"}