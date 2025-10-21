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
import difflib
from werkzeug.utils import secure_filename
from config import Config
import xml.etree.ElementTree as ET
from app import logger
import textwrap
from docx2pdf import convert
import tempfile
import shutil
import subprocess

logger = logging.getLogger(__name__)

SCIMAGO_DATA = {
    "by_title": {},
    "by_cleaned_title": {}
}
_MODEL_CACHE = None

def _clean_scimago_title(title):
    if not isinstance(title, str): return ""
    s = title.lower()
    # Ganti SEMUA yang bukan huruf/angka dengan SPASI
    s = re.sub(r'[^a-z0-9]', ' ', s)
    # Ganti beberapa spasi menjadi SATU spasi
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def load_scimago_data():
    global SCIMAGO_DATA
    try:
        df = pd.read_csv(Config.SCIMAGO_FILE_PATH, sep=';', encoding='utf-8')
         # Check for all required columns
        required_cols = ['Sourceid', 'Title', 'Type', 'SJR Best Quartile']
        if all(col in df.columns for col in required_cols):
            df.dropna(subset=required_cols, inplace=True)
            for _, row in df.iterrows():
                title = row['Title'].strip()
                source_id = row['Sourceid']
                quartile = row['SJR Best Quartile']
                source_type = row['Type'].strip().lower()

                journal_info = {
                    'id': source_id,
                    'quartile': quartile,
                    'type': source_type
                }

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

def _is_likely_reference(text):
    """
    Mendeteksi apakah sebuah baris teks kemungkinan adalah entri referensi.
    """
    text = text.strip()
    if len(text) < 20 or len(text) > 500:
        return False
    # Dimulai dengan nomor [d], (d), d.
    if re.match(r'^\[\d+\]|^\(\d+\)|^\d+\.', text):
        return True
    # Gaya Penulis APA/Chicago (Nama, I.)
    if re.match(r'^[A-Z][a-zA-Z\-\']{2,},\s([A-Z]\.\s?)+', text):
        return True
    # Dimulai dengan nama Organisasi diikuti tahun
    if re.match(r'^([A-Z][a-zA-Z\']+\s){2,}\.\s\(\d{4}', text):
        return True
    # Mengandung tahun dan DOI
    if re.search(r'\(\d{4}\)', text) and 'doi.org' in text.lower():
        return True
    return False

def _find_references_section_as_text_block(paragraphs):
    REFERENCE_HEADINGS = ["daftar pustaka", "referensi", "reference", "references", "bibliography", "pustaka rujukan"]
    STOP_HEADINGS = ["lampiran", "appendix", "biodata", "curriculum vitae", "riwayat hidup"]

    start_index = -1
    for i in range(len(paragraphs) - 1, -1, -1):
        para = paragraphs[i].strip()
        para_lower = para.lower()
        if any(h in para_lower for h in REFERENCE_HEADINGS) and len(para.split()) < 5:
            if i + 1 < len(paragraphs) and _is_likely_reference(paragraphs[i + 1]):
                start_index = i + 1
                break

    if start_index == -1:
        for i in range(len(paragraphs) - 1, -1, -1):
            para = paragraphs[i].strip()
            if any(h in para.lower() for h in REFERENCE_HEADINGS) and len(para.split()) < 5:
                start_index = i + 1
                break

    if start_index == -1:
        return None, "Bagian 'Daftar Pustaka' tidak ditemukan."

    end_index = len(paragraphs)
    captured_paragraphs = []
    consecutive_non_ref_count = 0

    for j in range(start_index, len(paragraphs)):
        para = paragraphs[j]

        # Jika menemukan judul STOP_HEADINGS, berhenti
        if any(stop in para.lower() for stop in STOP_HEADINGS):
            logger.info(f"Berhenti karena menemukan judul stop: '{para}'")
            break

        # Logika utama: deteksi referensi
        if _is_likely_reference(para):
            captured_paragraphs.append(para)
            consecutive_non_ref_count = 0
        else:
            # Tambahkan ke baris sebelumnya (baris lanjutan)
            if captured_paragraphs:
                captured_paragraphs[-1] += " " + para.strip()
            consecutive_non_ref_count += 1

        # 🧠 Tambahkan logika berhenti cerdas di sini:
        if consecutive_non_ref_count >= 5 or (
            consecutive_non_ref_count >= 3 and len(para.strip()) < 30
        ):
            logger.info("Berhenti menangkap karena pola teks tidak lagi menyerupai referensi.")
            break

    # 🧹 Bersihkan trailing paragraf yang tidak mengandung tahun atau DOI
    while captured_paragraphs and not re.search(r'\(\d{4}\)|doi\.org', captured_paragraphs[-1]):
        captured_paragraphs.pop()

    references_block = "\n".join(captured_paragraphs).strip()
    if not references_block:
        return None, "Bagian 'Daftar Pustaka' ditemukan, tetapi kosong."

    return references_block, None

def _get_paragraph_text(p):
     """
     Mengekstrak teks lengkap dari paragraf, termasuk dari Field Codes (Mendeley).
     """
     WORD_NAMESPACE = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
     TEXT = WORD_NAMESPACE + 't'
     xml_string = p._p.xml
     try:
         xml_tree = ET.fromstring(xml_string)
         text_nodes = xml_tree.findall('.//' + TEXT)
         if text_nodes:
             return "".join(node.text for node in text_nodes if node.text)
     except ET.ParseError:
         return p.text
     return ""

def _extract_references_from_docx(file_stream):
    """
    Versi FINAL untuk DOCX: Menggunakan logika 'tangkap dan berhenti cerdas'
    yang andal untuk file terstruktur seperti DOCX, termasuk dari Mendeley.
    """
    try:
        doc = docx.Document(io.BytesIO(file_stream.read()))
        # Gunakan pembaca XML untuk menangani field codes Mendeley
        all_paragraphs = [_get_paragraph_text(p).strip() for p in doc.paragraphs]
        paragraphs = [p for p in all_paragraphs if p] # Filter baris kosong

        REFERENCE_HEADINGS = ["daftar pustaka", "referensi", "bibliography", "references", "pustaka rujukan"]
        STOP_HEADINGS = ["lampiran", "appendix", "biodata", "curriculum vitae", "riwayat hidup"]
        
        start_index = -1
        # Cari judul dari depan
        for i, para in enumerate(paragraphs):
            if any(h == para.lower() for h in REFERENCE_HEADINGS):
                # Verifikasi konteks
                for j in range(i + 1, min(i + 6, len(paragraphs))):
                    if _is_likely_reference(paragraphs[j]):
                        start_index = j
                        break
                if start_index != -1:
                    break
        
        if start_index == -1:
            return None, "Bagian 'Daftar Pustaka' tidak ditemukan atau tidak diikuti konten valid di file DOCX."

        # Logika tangkap dan berhenti cerdas
        captured_paragraphs = []
        consecutive_non_ref_count = 0
        for i in range(start_index, len(paragraphs)):
            para = paragraphs[i]
            if any(stop == para.lower() for stop in STOP_HEADINGS):
                break
            if _is_likely_reference(para):
                captured_paragraphs.append(para)
                consecutive_non_ref_count = 0
            else:
                if captured_paragraphs:
                    captured_paragraphs[-1] += " " + para
                consecutive_non_ref_count += 1
            if consecutive_non_ref_count >= 5:
                # Hapus baris-baris non-referensi terakhir yang mungkin tertangkap
                captured_paragraphs = captured_paragraphs[:-5]
                break
        
        references_block = "\n".join(captured_paragraphs)
        if not references_block:
            return None, "Bagian 'Daftar Pustaka' ditemukan di DOCX, tetapi isinya kosong."
        return references_block, None
    except Exception as e:
        logger.error(f"Gagal memproses file .docx: {e}", exc_info=True)
        return None, f"Gagal memproses file .docx: {e}"

def _extract_references_from_pdf(file_stream):
    """
    [VERSI PERBAIKAN] Membaca PDF dan mengembalikan blok teks daftar pustaka
    dengan logika 'berhenti cerdas' untuk menghindari menangkap konten non-referensi.
    """
    try:
        pdf_bytes = file_stream.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Ekstrak teks per halaman dan gabungkan menjadi satu daftar paragraf
        all_paragraphs = []
        for page in doc:
            # Gunakan get_text("blocks") untuk menjaga struktur paragraf lebih baik
            blocks = page.get_text("blocks", sort=True)
            for b in blocks:
                # b[4] adalah teks blok, ganti newline di dalam blok dengan spasi
                block_text = b[4].replace('\n', ' ').strip()
                if block_text:
                    all_paragraphs.append(block_text)
        doc.close()

        REFERENCE_HEADINGS = ["daftar pustaka", "referensi", "bibliography", "references", "pustaka rujukan"]
        STOP_HEADINGS = ["lampiran", "appendix", "biodata", "curriculum vitae", "riwayat hidup"]
        start_index = -1

        # Cari judul "Daftar Pustaka"
        for i, para in enumerate(all_paragraphs):
            para_lower = para.lower()
            # Judul harus berdiri sendiri atau hampir sendiri
            if any(h in para_lower for h in REFERENCE_HEADINGS) and len(para.split()) < 5:
                # Pastikan baris berikutnya adalah referensi
                if i + 1 < len(all_paragraphs) and _is_likely_reference(all_paragraphs[i + 1]):
                    start_index = i + 1
                    logger.info(f"Judul Daftar Pustaka ditemukan di PDF pada paragraf #{i}: '{para}'")
                    break
        
        if start_index == -1:
            return None, "Judul bagian 'Daftar Pustaka' / 'References' tidak ditemukan atau tidak diikuti konten valid."

        # [PERBAIKAN UTAMA] Implementasi logika tangkap dan berhenti cerdas
        captured_paragraphs = []
        consecutive_non_ref_count = 0
        for j in range(start_index, len(all_paragraphs)):
            para = all_paragraphs[j]
            para_lower = para.lower()

            # Berhenti jika menemukan judul stop
            if any(stop == para_lower for stop in STOP_HEADINGS) and len(para.split()) < 5:
                logger.info(f"Berhenti menangkap karena menemukan judul stop: '{para}'")
                break
            
            # Logika utama: tangkap jika terlihat seperti referensi
            if _is_likely_reference(para):
                captured_paragraphs.append(para)
                consecutive_non_ref_count = 0
            else:
                # Jika baris pendek dan tidak seperti referensi, ini mungkin header/footer
                if len(para.split()) < 8: 
                    consecutive_non_ref_count += 1
                # Jika baris panjang tapi tidak seperti referensi, mungkin akhir bagian
                elif captured_paragraphs:
                    # Gabungkan dengan baris sebelumnya jika ini adalah kelanjutan
                    captured_paragraphs[-1] += " " + para
                
            # Berhenti jika 3 baris berturut-turut tidak terlihat seperti referensi
            if consecutive_non_ref_count >= 3:
                logger.info("Berhenti menangkap karena pola teks tidak lagi menyerupai referensi.")
                break
        
        references_block = "\n".join(captured_paragraphs).strip()
        
        if not references_block:
            return None, "Bagian 'Daftar Pustaka' ditemukan, tetapi isinya kosong atau tidak dapat diurai."

        logger.info(f"Berhasil mengekstrak blok teks referensi dari PDF dengan 'stop cerdas'.")
        return references_block, None
        
    except Exception as e:
        logger.error(f"Gagal memproses file .pdf: {e}", exc_info=True)
        return None, f"Gagal memproses file .pdf: {e}"

def _get_references_from_request(request, file_stream=None):
    """Mengambil input sebagai SATU BLOK TEKS, baik dari file maupun textarea."""
    if 'file' in request.files and request.files['file'].filename:
        # --- PERBAIKAN UTAMA DI SINI ---
        
        # Selalu ambil nama file dari request asli
        original_file_object = request.files['file']
        filename = secure_filename(original_file_object.filename)

        # Prioritaskan stream dari file yang sudah disimpan (untuk dibaca isinya)
        # Jika tidak ada (kasus input teks), baru ambil dari request upload.
        stream_to_read = file_stream or original_file_object
        
        # Validasi ekstensi
        if not ('.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS):
            return None, "Format file tidak didukung."

        # Panggil fungsi yang sesuai berdasarkan NAMA FILE
        if filename.lower().endswith('.docx'):
            return _extract_references_from_docx(stream_to_read)
        elif filename.lower().endswith('.pdf'):
            return _extract_references_from_pdf(stream_to_read)
            
    if 'text' in request.form and request.form['text'].strip():
        return request.form['text'].strip(), None
        
    return None, "Tidak ada input yang diberikan."

# --- (Fungsi-fungsi analisis sisanya tetap sama: _construct_batch_gemini_prompt, _process_ai_response, dll.) ---
def _construct_batch_gemini_prompt(references_list, style, year_range):
    from datetime import datetime
    year_threshold = datetime.now().year - year_range
    formatted_references = "\n".join([f"{i+1}. {ref}" for i, ref in enumerate(references_list)])

    style_examples = {
        "APA": "Contoh APA: Smith, J. (2023). Judul artikel. *Nama Jurnal*, *10*(2), 1-10.",
        "Harvard": "Contoh Harvard: Smith, J. (2023) 'Judul artikel', *Nama Jurnal*, 10(2), pp. 1-10.",
        "IEEE": "Contoh IEEE: [1] J. Smith, \"Judul artikel,\" *Nama Jurnal*, vol. 10, no. 2, pp. 1-10, Jan. 2023.",
        "MLA": "Contoh MLA: Smith, John. \"Judul Artikel.\" *Nama Jurnal*, vol. 10, no. 2, 2023, pp. 1-10.",
        "Chicago": "Contoh Chicago: Smith, John. 2023. \"Judul Artikel.\" *Nama Jurnal* 10 (2): 1-10."
    }
    
    return f"""
    Anda adalah AI ahli analisis daftar pustaka. Jawab SEMUA feedback dalam BAHASA INDONESIA.
    Analisis setiap referensi berikut berdasarkan gaya sitasi: **{style}**.

    PROSES UNTUK SETIAP REFERENSI:
    1.  **Ekstrak Elemen:** Ekstrak Penulis, Tahun, Judul, dan Nama Jurnal/Sumber.
    2.  **Identifikasi Tipe:** Tentukan `reference_type` ('journal', 'book', 'conference', 'website', 'other').
    3.  **Evaluasi Kelengkapan (`is_complete`):** Pastikan elemen wajib ada (Penulis, Tahun, Judul, Sumber, Halaman untuk jurnal). Jika tidak, `is_complete` = false.
    4.  **Evaluasi Tahun (`is_year_recent`):** `is_year_recent` = true jika tahun >= {year_threshold} (kecuali untuk buku fundamental).
    5.  **Evaluasi Format (`is_format_correct`):**
        - Fokus utama pada **STRUKTUR dan URUTAN ELEMEN** (Penulis-Tahun-Judul) sesuai gaya '{style}'.
        - Beri `is_format_correct` = **true** jika STRUKTUR UTAMA sudah benar, meskipun ada kesalahan styling minor.
        - Jika ada saran perbaikan styling (seperti cetak miring/italics pada nama jurnal atau volume), sebutkan saran tersebut di `feedback` tanpa membuat `is_format_correct` menjadi false.
        - Beri `is_format_correct` = **false** hanya jika ada kesalahan STRUKTUR FATAL (misal: urutan elemen salah, tanda kurung/kutip salah total).
    6.  **Evaluasi Sumber (`is_scientific_source`):** Tentukan `true` untuk sumber ilmiah, `false` untuk non-ilmiah.

    DAFTAR REFERENSI:
    ---
    {formatted_references}
    ---

    INSTRUKSI OUTPUT:
    Kembalikan sebagai ARRAY JSON TUNGGAL dengan struktur berikut:
    {{
        "reference_number": <int>,
        "parsed_authors": ["Penulis 1"],
        "parsed_year": <int>,
        "parsed_title": "<string>",
        "parsed_journal": "<string>",
        "reference_type": "journal/book/conference/website/other",
        "is_format_correct": <boolean>,
        "is_complete": <boolean>,
        "is_year_recent": <boolean>,
        "is_scientific_source": <boolean>,
        "missing_elements": ["elemen_hilang"],
        "feedback": "<Saran perbaikan dalam BAHASA INDONESIA, atau 'OK' jika sempurna>"
    }}
    """

def _process_ai_response(batch_results_json, references_list):
    detailed_results = []
    
    ACCEPTED_SCIMAGO_TYPES = {'journal', 'book series', 'trade journal', 'conference and proceeding'}

    for result_json in batch_results_json:
        # (Parsing data dasar tidak berubah)
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
        journal_info = None
        
        if journal_name and SCIMAGO_DATA["by_cleaned_title"]:
            cleaned_journal_name = _clean_scimago_title(journal_name)

            # Strategi 1: Coba pencocokan persis
            if cleaned_journal_name in SCIMAGO_DATA["by_cleaned_title"]:
                is_indexed = True
                journal_info = SCIMAGO_DATA["by_cleaned_title"][cleaned_journal_name]
            
            # Strategi 2: Pencocokan fuzzy
            else:
                query_words = set(cleaned_journal_name.split())
                if len(query_words) > 0:
                    best_match_info = None
                    highest_score = 0.55  # lebih toleran
                    best_match_title = ""

                    for title_db, info in SCIMAGO_DATA["by_cleaned_title"].items():
                        db_words = set(title_db.split())
                        if not db_words: continue

                        # 1) Exact subset: semua kata query ada di db (kuat)
                        if query_words.issubset(db_words) or db_words.issubset(query_words):
                            best_match_info = info
                            best_match_title = title_db
                            highest_score = 1.0
                            break

                        # 2) Jaccard-like overlap
                        common_words = query_words.intersection(db_words)
                        jaccard = len(common_words) / len(query_words.union(db_words))

                        # 3) Sequence similarity on full cleaned names
                        seq_ratio = difflib.SequenceMatcher(None, cleaned_journal_name, title_db).ratio()

                        # Combine scores, bias seq_ratio slightly
                        score = max(jaccard, seq_ratio * 0.9)

                        if score > highest_score:
                            highest_score = score
                            best_match_info = info
                            best_match_title = title_db

        # --- (Sisa kode tidak berubah) ---
        if is_indexed and journal_info:
            scimago_link = f"https://www.scimagojr.com/journalsearch.php?q={journal_info['id']}&tip=sid"
            quartile = journal_info['quartile']
            ref_type = journal_info['type']
        
        ai_assessment_valid = all([
            result_json.get('is_format_correct', False),
            result_json.get('is_complete', False),
            result_json.get('is_year_recent', False),
        ])
        
        is_overall_valid = False
        final_feedback = result_json.get('feedback', 'Analisis AI selesai.')
        
        if is_indexed and ref_type in ACCEPTED_SCIMAGO_TYPES:
            if ai_assessment_valid:
                is_overall_valid = True
                final_feedback += f" Status: VALID (Sumber tipe '{ref_type}' terindeks di ScimagoJR dan memenuhi kriteria kualitas)."
            else:
                final_feedback += f" Status: INVALID (Meskipun sumber terindeks, format/kelengkapan/tahun tidak memenuhi syarat.)"
        elif is_indexed:
            final_feedback += f" Status: INVALID (Sumber ditemukan di ScimagoJR, namun tipenya ('{ref_type}') tidak umum digunakan sebagai referensi utama)."
        else:
            final_feedback += f" Status: INVALID (Sumber ini adalah '{ref_type}', namun tidak ditemukan di database ScimagoJR 2024)."

        detailed_results.append({
            "reference_number": ref_num,
            "reference_text": ref_text, "status": "valid" if is_overall_valid else "invalid",
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
    
def _generate_summary_and_recommendations(detailed_results, count_validation, style, journal_percent_threshold):
    # ... (Kode tidak berubah) ...
    total = len(detailed_results)
    valid_count = sum(1 for r in detailed_results if r['status'] == 'valid')
    journal_count = sum(1 for r in detailed_results if r['reference_type'] == 'journal')
    journal_percentage = (journal_count / total) * 100 if total > 0 else 0
    meets_journal_req = journal_percentage >= journal_percent_threshold
    distribution = {"journal_percentage": round(journal_percentage, 1), "meets_journal_requirement": meets_journal_req}
    summary = {
        "total_references": total, "valid_references": valid_count, "invalid_references": total - valid_count,
        "processing_errors": 0, "validation_rate": round((valid_count / total) * 100, 1) if total > 0 else 0,
        "count_validation": count_validation, "distribution_analysis": distribution, "style_used": style,
        "journal_percent_threshold": journal_percent_threshold
    }
    recommendations = []
    if summary['validation_rate'] < 70: recommendations.append("⚠️ Tingkat validitas rendah. Banyak referensi perlu perbaikan format atau kelengkapan.")
    if not meets_journal_req: recommendations.append(f"📊 Proporsi jurnal ({journal_percentage:.1f}%) belum memenuhi syarat minimal yang Anda tentukan ({journal_percent_threshold}%).")
    if not count_validation['is_count_appropriate']: recommendations.append(f"📝 {count_validation['count_message']}")
    if not recommendations: recommendations.append("✅ Referensi sudah memenuhi standar kualitas umum. Siap untuk tahap selanjutnya.")
    return summary, recommendations

def process_validation_request(request, saved_file_stream=None):
    """
    Fungsi orkestrator utama dengan metode "pemotongan" AI.
    """
    # Langkah 1: Dapatkan SELURUH BLOK TEKS daftar pustaka dari input
    references_block, error = _get_references_from_request(request, saved_file_stream)
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
        journal_percent_threshold = request.form.get('journal_percent', Config.JOURNAL_PROPORTION_THRESHOLD, type=float)
        
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
        summary, recommendations = _generate_summary_and_recommendations(detailed_results, count_validation, style, journal_percent_threshold)

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

# Ganti seluruh fungsi ini di app/services.py

def create_annotated_pdf_from_file(original_filepath, validation_results):
    """
    Versi Final Paling Andal: Menangani nama jurnal yang terpotong antar baris
    dan memperbaiki bug 'bad quads entry'.
    """
    try:
        pdf = fitz.open(original_filepath)
        detailed_results = validation_results.get('detailed_results', [])
        highlighted_ref_numbers = set()
        added_references_summary = False

        start_annotating = False
        def _looks_like_reference_line(text):
            # Simple heuristic: contains a 4-digit year or starts with numbering
            if not text or not isinstance(text, str):
                return False
            if re.search(r'\(\d{4}\)|\d{4}', text):
                return True
            if re.match(r'^(\[\d+\]|\(\d+\)|\d+\.)', text.strip()):
                return True
            return False

        def _heading_followed_by_reference(page_words, start_idx):
            # Look ahead a few words/lines after the heading to see if there's a likely reference
            # Build small context text from the following 30 words
            texts = []
            for j in range(start_idx + 1, min(len(page_words), start_idx + 60)):
                texts.append(page_words[j][4])
            context = ' '.join(texts)
            return _looks_like_reference_line(context)

        for page in pdf:
            if not start_annotating:
                page_text_lower = page.get_text("text").lower()
                if any(h in page_text_lower for h in ["daftar pustaka", "references"]):
                    start_annotating = True
            if not start_annotating:
                continue

            words_on_page = page.get_text("words")

            # Jika ini halaman tempat judul 'Daftar Pustaka' ditemukan dan kita belum
            # menambahkan ringkasan, cari posisi judul dan tambahkan highlight + note
            if start_annotating and not added_references_summary:
                try:
                    # Build lines from words_on_page by grouping words with similar Y coordinates.
                    # This lets us detect a standalone heading line (not an inline phrase in a paragraph)
                    heading_tokens = ['daftar pustaka', 'references']
                    lines = []
                    for wi, w in enumerate(words_on_page):
                        x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
                        if not txt or not txt.strip():
                            continue
                        if not lines:
                            lines.append({'y': y0, 'words':[txt], 'word_indices':[wi], 'rects':[fitz.Rect(w[:4])]})
                        else:
                            # if vertical gap is small, consider same line
                            if abs(y0 - lines[-1]['y']) <= 3:
                                lines[-1]['words'].append(txt)
                                lines[-1]['word_indices'].append(wi)
                                lines[-1]['rects'].append(fitz.Rect(w[:4]))
                            else:
                                lines.append({'y': y0, 'words':[txt], 'word_indices':[wi], 'rects':[fitz.Rect(w[:4])]})

                    heading_idx = None
                    heading_rects = []
                    for li, line in enumerate(lines):
                        line_text = ' '.join(line['words']).strip().lower()
                        for ht in heading_tokens:
                            # Normalize line text (remove punctuation) for strict comparison
                            norm_line = re.sub(r'[^a-z0-9\s]', '', line_text)
                            if norm_line == ht:
                                # exact line match
                                # Check next few lines for reference-like patterns
                                context = []
                                for j in range(li+1, min(len(lines), li+7)):
                                    context.append(' '.join(lines[j]['words']))
                                context_text = ' '.join(context)
                                if _looks_like_reference_line(context_text):
                                    heading_idx = li
                                    heading_rects = line['rects']
                                    break
                            else:
                                # Allow two-line heading like 'daftar' + 'pustaka'
                                if li+1 < len(lines):
                                    next_line_text = ' '.join(lines[li+1]['words']).strip().lower()
                                    norm_next = re.sub(r'[^a-z0-9\s]', '', next_line_text)
                                    if f"{norm_line} {norm_next}".strip() == ht:
                                        context = []
                                        for j in range(li+2, min(len(lines), li+8)):
                                            context.append(' '.join(lines[j]['words']))
                                        context_text = ' '.join(context)
                                        if _looks_like_reference_line(context_text):
                                            heading_idx = li
                                            heading_rects = line['rects'] + lines[li+1]['rects']
                                            break
                        if heading_idx is not None:
                            break

                    # Jika heading ditemukan, buat highlight/per-kata highlight dan sebuah note
                    if heading_rects:
                        # Gabungkan rects menjadi satu area untuk highlight heading
                        heading_full = fitz.Rect(heading_rects[0])
                        for r in heading_rects[1:]:
                            heading_full.include_rect(r)

                        try:
                            # Light blue for heading RGB(210,236,238)
                            pattens_blue = (210/255.0, 236/255.0, 238/255.0)
                            h = page.add_highlight_annot(heading_full)
                            h.set_colors(stroke=pattens_blue, fill=pattens_blue)
                            h.update()
                        except Exception:
                            # fallback: add a rectangle annotation
                            try:
                                r_annot = page.add_rect_annot(heading_full)
                                r_annot.set_colors(stroke=pattens_blue, fill=pattens_blue)
                                r_annot.set_opacity(0.4)
                                r_annot.set_blend_mode("Multiply")
                                r_annot.update()
                            except Exception:
                                logger.debug("Gagal menambahkan highlight heading, lanjut tanpa highlight")

                        # Siapkan ringkasan validasi berdasarkan validation_results dan detailed_results
                        summary = validation_results.get('summary', {})
                        total = summary.get('total_references', len(detailed_results))
                        journal_count = sum(1 for r in detailed_results if r.get('reference_type') == 'journal')
                        non_journal_count = total - journal_count
                        journal_pct = round((journal_count / total) * 100, 1) if total > 0 else 0.0
                        non_journal_pct = round((non_journal_count / total) * 100, 1) if total > 0 else 0.0

                        # Terindeks SJR (is_indexed True pada detailed_results)
                        sjr_count = sum(1 for r in detailed_results if r.get('is_indexed'))
                        sjr_pct = round((sjr_count / total) * 100, 1) if total > 0 else 0.0

                        distrib = summary.get('distribution_analysis', {})
                        meets_journal_req = distrib.get('meets_journal_requirement')
                        journal_percentage = distrib.get('journal_percentage')
                        # Try to get threshold if provided
                        # Ambil threshold yang dipakai (jika disertakan di summary dari proses utama)
                        raw_threshold = validation_results.get('journal_percent_threshold')
                        if raw_threshold is None:
                            raw_threshold = validation_results.get('summary', {}).get('journal_percent_threshold')
                        if isinstance(raw_threshold, (int, float)):
                            threshold = f"{raw_threshold}%"
                        else:
                            threshold = str(raw_threshold or 'N/A')

                        meets_text = 'VALID' if meets_journal_req else 'INVALID'
                        if isinstance(journal_percentage, (int, float)):
                            jp_display = f"{journal_percentage:.1f}%"
                        else:
                            jp_display = f"{journal_pct:.1f}%"

                        # Year validity
                        year_approved = sum(1 for r in detailed_results if r.get('validation_details', {}).get('year_recent'))
                        year_not_approved = total - year_approved

                        # Quartile counts
                        q_counts = {'Q1':0,'Q2':0,'Q3':0,'Q4':0,'Not Found':0}
                        for r in detailed_results:
                            q = r.get('quartile')
                            if q in ('Q1','Q2','Q3','Q4'):
                                q_counts[q] += 1
                            else:
                                q_counts['Not Found'] += 1

                        summary_content = (
                            f"Total Referensi: {total}\n"
                            f"Artikel Jurnal: {journal_count} ({journal_pct}%)\n"
                            f"Artikel Non-jurnal: {non_journal_count} ({non_journal_pct}%)\n"
                            f"Terindeks SJR: {sjr_count} ({sjr_pct}%)\n"
                            f"Min. Persyaratan Jurnal: {meets_text} ({jp_display} / {threshold})\n"
                            f"Validitas Tahun: {year_approved} approved / {year_not_approved} not approved\n"
                            f"Kuartil: Q1: {q_counts['Q1']} | Q2: {q_counts['Q2']} | Q3: {q_counts['Q3']} | Q4: {q_counts['Q4']} | Tidak ditemukan: {q_counts['Not Found']}"
                        )

                        # Tambahkan satu popup note di atas heading
                        try:
                            popup_pos = fitz.Point(heading_full.x0, max(0, heading_full.y0 - 18))
                            note = page.add_text_annot(popup_pos, summary_content)
                            note.set_info(title="Ringkasan Validasi Referensi")
                            try:
                                # Try to color the note with Pattens Blue if supported
                                note.set_colors(stroke=pattens_blue, fill=pattens_blue)
                            except Exception:
                                pass
                            note.update()
                        except Exception as ex:
                            logger.warning(f"Gagal menambahkan summary note pada heading: {ex}")

                        added_references_summary = True
                except Exception as ex:
                    logger.warning(f"Error saat mencoba menambahkan highlight/summary untuk heading: {ex}")

            # Bangun daftar token yang 'diperluas' sehingga kata-kata seperti
            # 'Hardy-Ramanujan' (yang muncul sebagai satu word entry) dipecah
            # menjadi token ['hardy', 'ramanujan'] dan tetap dipetakan ke kotak kata asli.
            expanded_tokens = []  # list of dicts: {token, word_index, rect}
            for wi, w in enumerate(words_on_page):
                cleaned = _clean_scimago_title(w[4])
                if not cleaned:
                    continue
                parts = cleaned.split()
                for part in parts:
                    expanded_tokens.append({
                        'token': part,
                        'word_index': wi,
                        'rect': fitz.Rect(w[:4])
                    })

                for result in detailed_results:
                    ref_num = result.get('reference_number')
                    # Hanya beri anotasi pada journals (user requested) dan jika belum diproses
                    if ref_num in highlighted_ref_numbers:
                        continue

                    journal_type = (result.get('reference_type') or '').lower()
                    # Jika jurnal tidak bertipe 'journal', tetap proses jika SCIMAGO menandainya sebagai terindeks
                    is_indexed_flag = bool(result.get('is_indexed'))
                    if not (journal_type == 'journal' or is_indexed_flag):
                        continue

                    journal_name = result.get('parsed_journal')
                    # Jika tidak ada nama jurnal yang berarti, lewati
                    if not journal_name or len(journal_name) < 3:
                        continue

                    search_tokens = _clean_scimago_title(journal_name).split()
                    if not search_tokens:
                        continue

                    plen = len(search_tokens)
                    page_token_list = [t['token'] for t in expanded_tokens]

                    for i in range(len(page_token_list) - plen + 1):
                        if page_token_list[i:i+plen] == search_tokens:
                            matched_word_indices = [expanded_tokens[i + k]['word_index'] for k in range(plen)]
                            unique_word_indices = []
                            for idx in matched_word_indices:
                                if not unique_word_indices or unique_word_indices[-1] != idx:
                                    unique_word_indices.append(idx)

                            matched_word_rects = [fitz.Rect(words_on_page[idx][:4]) for idx in unique_word_indices]

                            # Tandai agar tidak diproses lagi
                            highlighted_ref_numbers.add(ref_num)

                            # Buat konten note sesuai kondisi: apakah terindeks atau tidak
                            is_indexed = bool(result.get('is_indexed'))
                            quartile = result.get('quartile', 'N/A')
                            scimago_link = result.get('scimago_link', 'N/A')

                            # Prepare first rect for popup
                            first_rect_for_popup = None

                            # Define pink highlight color once (used for non-indexed highlights & notes)
                            pink_rgb = (251/255.0, 215/255.0, 222/255.0)
                            # Define indexed journal color (used for both highlight and note)
                            indexed_rgb = (208/255.0, 233/255.0, 222/255.0)

                            # Apply highlights per word and collect first rect
                            for wi, rect in enumerate(matched_word_rects):
                                try:
                                    if rect.x0 == rect.x1 or rect.y0 == rect.y1:
                                        rect = fitz.Rect(rect.x0, rect.y0, rect.x0 + 1, rect.y0 + 1)
                                    if first_rect_for_popup is None:
                                        first_rect_for_popup = rect

                                    # If journal is indexed -> keep existing yellow highlight behavior
                                    if is_indexed:
                                        h = page.add_highlight_annot(rect)
                                        # Use same greenish tint as the indexed journal note
                                        h.set_colors(stroke=indexed_rgb, fill=indexed_rgb)
                                        h.update()
                                    else:
                                        # Non-indexed journals: pale pink -> reuse pink_rgb defined above
                                        try:
                                            h = page.add_highlight_annot(rect)
                                            # set both stroke and fill to make color visible in some viewers
                                            h.set_colors(stroke=pink_rgb, fill=pink_rgb)
                                            h.update()
                                        except Exception:
                                            # fallback to rectangle with fill
                                            try:
                                                r_annot = page.add_rect_annot(rect)
                                                r_annot.set_colors(stroke=pink_rgb, fill=pink_rgb)
                                                r_annot.set_opacity(0.4)
                                                r_annot.set_blend_mode("Multiply")
                                                r_annot.update()
                                            except Exception:
                                                logger.debug("Gagal menambahkan highlight pale pink, lanjut tanpa highlight")

                                except Exception as ex:
                                    logger.warning(f"Gagal membuat highlight untuk kata pada ref {ref_num}: {ex}")


                            # Add sticky note for indexed or non-indexed journals
                            try:
                                if first_rect_for_popup:
                                    popup_pos = fitz.Point(first_rect_for_popup.x0, max(0, first_rect_for_popup.y0 - 18))
                                    if is_indexed:
                                        # Note for indexed journals (greenish tint)
                                        note_text = (f"Jurnal: {result.get('parsed_journal', 'N/A')}\n"
                                                     f"Jenis: {result.get('reference_type', 'N/A')}\n"
                                                     f"Kuartil: {quartile}\n"
                                                     f"Link: {scimago_link}")
                                        note = page.add_text_annot(popup_pos, note_text)
                                        note.set_info(title="Sumber Terindeks Scimago")
                                        indexed_rgb = (208/255.0, 233/255.0, 222/255.0)
                                        try:
                                            note.set_colors(stroke=indexed_rgb, fill=indexed_rgb)
                                        except Exception:
                                            pass
                                        note.update()
                                    else:
                                        # Non-indexed fallback (pink) — reuse pink_rgb defined above
                                        note_text = (f"Sumber: {result.get('parsed_journal', 'N/A')}\n"
                                                     f"Jenis: journal")
                                        note = page.add_text_annot(popup_pos, note_text)
                                        note.set_info(title="Sumber Tidak Terindeks Scimago")
                                        try:
                                            note.set_colors(stroke=pink_rgb, fill=pink_rgb)
                                        except Exception:
                                            pass
                                        note.update()

                            except Exception as ex:
                                logger.warning(f"Gagal membuat popup note untuk ref {ref_num}: {ex}")

                            break
        
            # Per-page pass: ensure outdated years are highlighted and annotated for ALL references
            try:
                # Use RGB(255,105,97) for year highlight and note (normalized to 0-1)
                year_rgb = (255/255.0, 105/255.0, 97/255.0)
                # Determine minimal allowed year from validation_results (top-level)
                year_range_used_top = validation_results.get('year_range') if isinstance(validation_results, dict) else None
                current_year_top = datetime.now().year
                minimal_allowed_year_top = None
                if isinstance(year_range_used_top, int):
                    minimal_allowed_year_top = current_year_top - int(year_range_used_top)

                annotated_year_refs = set()
                # For every reference in detailed_results, try to find and mark its year on the current page
                for result in detailed_results:
                    try:
                        ref_num = result.get('reference_number')
                        if ref_num in annotated_year_refs:
                            continue
                        parsed_year = result.get('parsed_year')
                        if not parsed_year or minimal_allowed_year_top is None:
                            continue
                        try:
                            if int(parsed_year) >= int(minimal_allowed_year_top):
                                continue
                        except Exception:
                            continue

                        year_str = str(parsed_year)
                        year_rects = []
                        # Find tokens on this page that match the year (allow punctuation like (2020), 2020, etc.)
                        for widx, w in enumerate(words_on_page):
                            try:
                                token = w[4].strip()
                                norm = re.sub(r'^[^0-9]*(\d{4})[^0-9]*$', r"\1", token)
                                if norm == year_str:
                                    year_rects.append(fitz.Rect(w[:4]))
                            except Exception:
                                continue

                        # Fallback: fullmatch with punctuation
                        if not year_rects:
                            for widx, w in enumerate(words_on_page):
                                try:
                                    if re.fullmatch(r"\(?%s\)?[\.,;:?]?" % re.escape(year_str), w[4].strip()):
                                        year_rects.append(fitz.Rect(w[:4]))
                                except Exception:
                                    continue

                        if not year_rects:
                            # nothing found on this page for this reference's year
                            continue

                        first_year_rect = None
                        for rect in year_rects:
                            try:
                                if rect.is_empty:
                                    continue
                                if rect.x0 == rect.x1 or rect.y0 == rect.y1:
                                    rect = fitz.Rect(rect.x0, rect.y0, rect.x0 + 1, rect.y0 + 1)
                                h = page.add_highlight_annot(rect)
                                h.set_colors(stroke=year_rgb, fill=year_rgb)
                                try:
                                    # Make highlight opacity similar to fallback rect so colors match
                                    h.set_opacity(0.4)
                                except Exception:
                                    pass
                                h.update()
                                if first_year_rect is None:
                                    first_year_rect = rect
                            except Exception:
                                try:
                                    r2 = page.add_rect_annot(rect)
                                    r2.set_colors(stroke=year_rgb, fill=year_rgb)
                                    # Make fallback rectangle more opaque so it visually matches highlights
                                    try:
                                        r2.set_opacity(0.4)
                                    except Exception:
                                        pass
                                    # Use Multiply blend mode to interact with underlying text like a real highlighter
                                    try:
                                        r2.set_blend_mode("Multiply")
                                    except Exception:
                                        # If set_blend_mode not available on this PyMuPDF version, ignore
                                        pass
                                    # Try to remove rectangle border for closer visual match (optional)
                                    try:
                                        r2.set_border(width=0)
                                    except Exception:
                                        pass
                                    # Finally persist the annotation changes (after blend mode)
                                    r2.update()
                                    if first_year_rect is None:
                                        first_year_rect = rect
                                except Exception:
                                    logger.debug("Gagal menambahkan highlight tahun pada halaman")

                        # Add a note anchored to top-center of first_year_rect
                        if first_year_rect is not None:
                            try:
                                center_x = (first_year_rect.x0 + first_year_rect.x1) / 2.0
                                popup_pos = fitz.Point(center_x, max(0, first_year_rect.y0 - 18))
                                note_text = f"Tahun terbit: ({parsed_year}) | kurang dari tahun minimal: ({minimal_allowed_year_top})."
                                note = page.add_text_annot(popup_pos, note_text)
                                note.set_info(title="Kurang Dari Tahun minimal")
                                try:
                                    note.set_colors(stroke=year_rgb, fill=year_rgb)
                                except Exception:
                                    pass
                                note.update()
                            except Exception as ex:
                                logger.warning(f"Gagal menambahkan catatan tahun untuk ref {ref_num}: {ex}")

                        annotated_year_refs.add(ref_num)
                    except Exception:
                        continue
            except Exception:
                # don't let year-annotation failures block overall processing
                pass

        pdf_bytes = pdf.tobytes()
        pdf.close()
        
        return pdf_bytes, None

    except Exception as e:
        logger.error(f"Error di create_annotated_pdf_from_file: {e}", exc_info=True)
        return None, f"Gagal membuat anotasi pada file PDF asli."
    
def convert_docx_to_pdf(docx_path):
    """
    Mengonversi file DOCX ke PDF dan mengembalikan path ke file PDF baru.
    """
    try:
        # Tentukan path output. Simpan di folder yang sama dengan nama yang sama tapi ekstensi .pdf
        pdf_path = os.path.splitext(docx_path)[0] + ".pdf"
        
        logger.info(f"Mengonversi '{docx_path}' ke '{pdf_path}'...")
        try:
            convert(docx_path, pdf_path)
        except Exception as primary_ex:
            # Tangani kasus umum COM CoInitialize error (docx2pdf via MS Word)
            msg = str(primary_ex)
            logger.warning(f"docx2pdf gagal: {msg}")
            # Jika error berisi CoInitialize, coba inisialisasi COM secara eksplisit (Windows)
            if 'CoInitialize' in msg or "CoInitialize has not been called" in msg:
                try:
                    import pythoncom
                    pythoncom.CoInitialize()
                    logger.info("Memanggil pythoncom.CoInitialize() dan mencoba lagi konversi DOCX...")
                    convert(docx_path, pdf_path)
                except Exception as com_ex:
                    logger.warning(f"Gagal setelah CoInitialize retry: {com_ex}")
                    # Coba fallback ke LibreOffice/soffice jika tersedia
                    if shutil.which('soffice'):
                        try:
                            logger.info("Mencoba konversi menggunakan LibreOffice (soffice)...")
                            subprocess.check_call([shutil.which('soffice'), '--headless', '--convert-to', 'pdf', '--outdir', os.path.dirname(pdf_path), docx_path])
                        except Exception as lo_ex:
                            logger.error(f"Fallback LibreOffice gagal: {lo_ex}", exc_info=True)
                            raise com_ex
                    else:
                        raise com_ex
            else:
                # Jika bukan CoInitialize, coba fallback ke LibreOffice
                if shutil.which('soffice'):
                    try:
                        logger.info("docx2pdf gagal, mencoba fallback LibreOffice (soffice)...")
                        subprocess.check_call([shutil.which('soffice'), '--headless', '--convert-to', 'pdf', '--outdir', os.path.dirname(pdf_path), docx_path])
                    except Exception as lo_ex:
                        logger.error(f"Fallback LibreOffice gagal: {lo_ex}", exc_info=True)
                        raise primary_ex
                else:
                    raise primary_ex
        
        if os.path.exists(pdf_path):
            logger.info("Konversi DOCX ke PDF berhasil.")
            return pdf_path, None
        else:
            return None, "Konversi DOCX ke PDF gagal, file output tidak dibuat."
            
    except Exception as e:
        # Ini sering terjadi jika MS Word tidak terinstal atau ada masalah COM
        logger.error(f"Error saat mengonversi DOCX ke PDF: {e}", exc_info=True)
        # Berikan pesan yang lebih membantu termasuk kemungkinan solusi
        help_msg = (
            "Gagal mengonversi DOCX ke PDF. Jika Anda menggunakan Windows, pastikan Microsoft Word terinstal "
            "dan aplikasi berjalan setidaknya sekali. Jika server/headless, pasang LibreOffice dan coba lagi. "
            f"Detail teknis: {e}"
        )
        return None, help_msg