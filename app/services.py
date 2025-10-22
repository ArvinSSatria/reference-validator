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
    s = re.sub(r'[^a-z0-9]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def load_scimago_data():
    global SCIMAGO_DATA
    try:
        df = pd.read_csv(Config.SCIMAGO_FILE_PATH, sep=';', encoding='utf-8')
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
    Membaca PDF dan mengembalikan seluruh blok teks daftar pustaka.
    Sengaja dibuat 'greedy' untuk menghindari berhenti prematur karena page break.
    """
    try:
        pdf_bytes = file_stream.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        full_text = "".join(page.get_text("text", sort=True) + "\n" for page in doc)
        doc.close()
        paragraphs = [p.strip() for p in full_text.split('\n') if p.strip()]
        
        REFERENCE_HEADINGS = ["daftar pustaka", "daftar referensi", "referensi", "bibliography", "references", "pustaka rujukan"]
        start_index = -1

        # Cari judul "Daftar Pustaka" dari depan ke belakang
        for i, para in enumerate(paragraphs):
            if any(h in para.lower() for h in REFERENCE_HEADINGS) and len(para.split()) < 5:
                start_index = i
                logger.info(f"Judul Daftar Pustaka ditemukan di PDF pada paragraf #{i}: '{para}'")
                break
        
        if start_index == -1:
            return None, "Judul bagian 'Daftar Pustaka' / 'References' tidak ditemukan dalam dokumen PDF."

        # Ambil SEMUA paragraf setelah judul sampai akhir dokumen
        references_block = "\n".join(paragraphs[start_index + 1:])
        
        if not references_block.strip():
            return None, "Bagian 'Daftar Pustaka' ditemukan, tetapi tampaknya kosong."

        logger.info(f"Berhasil mengekstrak blok teks referensi dari PDF.")
        return references_block, None
        
    except Exception as e:
        logger.error(f"Gagal memproses file .pdf: {e}", exc_info=True)
        return None, f"Gagal memproses file .pdf: {e}"

def _get_references_from_request(request, file_stream=None):
    """Mengambil input sebagai SATU BLOK TEKS, baik dari file maupun textarea."""
    if 'file' in request.files and request.files['file'].filename:
        original_file_object = request.files['file']
        filename = secure_filename(original_file_object.filename)
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
        full_text = request.form['text'].strip()
        paragraphs = [p.strip() for p in full_text.split('\n') if p.strip()]
        return _find_references_section_as_text_block(paragraphs)
        
    return None, "Tidak ada input yang diberikan."

# --- (Fungsi-fungsi analisis sisanya tetap sama: _construct_batch_gemini_prompt, _process_ai_response, dll.) ---
def _construct_batch_gemini_prompt(references_list, style, year_range):
    from datetime import datetime
    year_threshold = datetime.now().year - year_range
    formatted_references = "\n".join([f"{i+1}. {ref}" for i, ref in enumerate(references_list)])

    style_examples = {
        "APA": "Contoh APA: Smith, J. (2023). Judul artikel. Nama Jurnal, 10(2), 1-10.",
        "Harvard": "Contoh Harvard: Smith, J. (2023) 'Judul artikel', Nama Jurnal, 10(2), pp. 1-10.",
        "IEEE": "Contoh IEEE: [1] J. Smith, \"Judul artikel,\" Nama Jurnal, vol. 10, no. 2, pp. 1-10, Jan. 2023.",
        "MLA": "Contoh MLA: Smith, John. \"Judul Artikel.\" Nama Jurnal, vol. 10, no. 2, 2023, pp. 1-10.",
        "Chicago": "Contoh Chicago: Smith, John. 2023. \"Judul Artikel.\" Nama Jurnal 10 (2): 1-10."
    }
    
    # [PERBAIKAN UTAMA DI SINI]
    return f"""
    Anda adalah AI ahli analisis daftar pustaka. Jawab SEMUA feedback dalam BAHASA INDONESIA.
    Analisis setiap referensi berikut berdasarkan gaya sitasi: **{style}**.

    ⚠️ Catatan Penting (versi lebih longgar / fleksibel):
    - Jika referensi berupa **preprint / working paper / early access / SSRN / arXiv / ResearchSquare**, TETAP dianggap ilmiah dan `is_scientific_source = true` selama ada DOI / Handle / SSRN ID / arXiv ID.
    - Informasi volume, issue, atau halaman yang tidak tersedia pada preprint/working paper TIDAK dianggap sebagai kekurangan (`is_complete = true`).
    - Penilaian `is_format_correct` hanya mengecek URUTAN UTAMA (penulis → tahun → judul). Variasi kecil gaya tanda baca / italic / huruf besar TIDAK mempengaruhi.
    - Jika jurnal Q1 atau terindeks, tetap OK meskipun tidak mencantumkan issue/halaman (karena beberapa jurnal pakai article number).
    - HANYA sumber non-ilmiah (blog pribadi, Wikipedia, konten marketing) yang diberi `is_scientific_source = false`.

    PROSES UNTUK SETIAP REFERENSI:
    1. **Ekstrak Elemen:** Penulis, Tahun, Judul, dan Nama Jurnal/Sumber.
    2. **Identifikasi tipe:** `reference_type` = journal / book / conference / preprint / website / other.
    3. **Kelengkapan (`is_complete`):**
    - true jika elemen utama ada (penulis, tahun, judul, sumber).
    - Halaman/volume/issue opsional untuk preprint atau model article-number.
    4. **Evaluasi Tahun (`is_year_recent`):** true jika tahun >= {year_threshold}.
    5. **Format (`is_format_correct`):** true jika urutan inti Penulis→Tahun→Judul sudah benar (tanpa cek detail tanda baca).
    6. **Evaluasi Sumber (`is_scientific_source`):**
    - true untuk jurnal, prosiding, buku akademik, preprint (SSRN/arXiv), dan working paper ilmiah.
    - false hanya untuk non-ilmiah.
    7. **Feedback:**
    - Jika ada kekurangan → jelaskan ringkas tanpa menyebut “INVALID”, cukup “perlu ditambahkan...”.

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
    Versi FIXED (Anti-Duplikasi):
    Menggunakan mekanisme 'claiming' (used_word_indices) untuk memastikan jika ada
    dua referensi dengan jurnal/tahun sama, keduanya tetap ter-highlight pada
    kemunculan teks yang berbeda di halaman yang sama.
    """
    try:
        pdf = fitz.open(original_filepath)
        detailed_results = validation_results.get('detailed_results', [])
        
        PATTENS_BLUE = (210/255.0, 236/255.0, 238/255.0)
        INDEXED_RGB  = (208/255.0, 233/255.0, 222/255.0)
        PINK_RGB     = (251/255.0, 215/255.0, 222/255.0)
        YEAR_RGB     = (255/255.0, 105/255.0, 97/255.0)

        start_annotating = False
        added_references_summary = False

        # Helper untuk cek apakah sebuah baris terlihat seperti referensi
        def _looks_like_reference_line(text):
            if not text or not isinstance(text, str): return False
            # Ada tahun 4 digit dalam kurung atau berdiri sendiri
            if re.search(r'\(\d{4}\)|\b\d{4}\b', text): return True
            # Dimulai dengan numbering [1], (1), 1.
            if re.match(r'^(\[\d+\]|\(\d+\)|\d+\.)', text.strip()): return True
            return False

        for page_num, page in enumerate(pdf):
            words_on_page = page.get_text("words") # Returns list of (x0,y0,x1,y1, "word", block_no, line_no, word_no)

            used_word_indices = set()

            # --- BAGIAN 1: DETEKSI & SUMMARY HEADING (Tidak berubah banyak) ---
            if not start_annotating:
                # (Logika deteksi heading dipertahankan sama seperti sebelumnya agar stabil)
                try:
                    heading_tokens = ['daftar pustaka', 'references', 'daftar referensi', 'bibliography', 'pustaka rujukan', 'referensi']
                    lines = []
                    for wi, w in enumerate(words_on_page):
                        x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
                        if not txt or not txt.strip(): continue
                        if not lines or abs(y0 - lines[-1]['y']) > 3:
                            lines.append({'y': y0, 'words':[txt], 'word_indices':[wi], 'rects':[fitz.Rect(w[:4])]})
                        else:
                            lines[-1]['words'].append(txt)
                            lines[-1]['word_indices'].append(wi)
                            lines[-1]['rects'].append(fitz.Rect(w[:4]))

                    heading_rects = []
                    for li, line in enumerate(lines):
                        line_text = ' '.join(line['words']).strip().lower()
                        norm_line = re.sub(r'[^a-z0-9\s]', '', line_text)
                        
                        found_ht = False
                        for ht in heading_tokens:
                            if norm_line == ht:
                                found_ht = True
                            elif li+1 < len(lines):
                                next_text = re.sub(r'[^a-z0-9\s]', '', ' '.join(lines[li+1]['words']).strip().lower())
                                if f"{norm_line} {next_text}".strip() == ht:
                                    found_ht = True
                                    # Tambahkan rects baris berikutnya jika judul 2 baris
                                    line['rects'].extend(lines[li+1]['rects'])

                        if found_ht:
                            # Cek konteks 7 baris ke depan
                            context = ' '.join([' '.join(lines[j]['words']) for j in range(li+1, min(len(lines), li+8))])
                            if _looks_like_reference_line(context):
                                start_annotating = True
                                heading_rects = line['rects']
                                break
                    
                    if not start_annotating: continue # Lanjut ke halaman berikutnya jika belum ketemu

                except Exception: continue

            # --- BAGIAN 2: GAMBAR SUMMARY NOTE PADA HEADING ---
            if start_annotating and not added_references_summary and heading_rects:
                try:
                    heading_full = fitz.Rect(heading_rects[0])
                    for r in heading_rects[1:]: heading_full.include_rect(r)
                    
                    # Highlight Heading
                    h = page.add_highlight_annot(heading_full)
                    h.set_colors(stroke=PATTENS_BLUE, fill=PATTENS_BLUE)
                    h.update()

                    # Siapkan Teks Summary
                    summary = validation_results.get('summary', {})
                    total = len(detailed_results)
                    journal_count = sum(1 for r in detailed_results if r.get('reference_type') == 'journal')
                    sjr_count = sum(1 for r in detailed_results if r.get('is_indexed'))
                    
                    # Hitung year approved berdasarkan data detail
                    year_approved = sum(1 for r in detailed_results if r.get('validation_details', {}).get('year_recent'))
                    
                    q_counts = {'Q1':0,'Q2':0,'Q3':0,'Q4':0,'Not Found':0}
                    for r in detailed_results:
                         q = r.get('quartile')
                         if q in q_counts: q_counts[q] += 1
                         elif q: q_counts['Not Found'] += 1

                    summary_content = (
                        f"Total Referensi: {total}\n"
                        f"Artikel Jurnal: {journal_count} ({ (journal_count/total*100) if total else 0:.1f}%)\n"
                        f"Terindeks SJR: {sjr_count} ({ (sjr_count/total*100) if total else 0:.1f}%)\n"
                        f"Validitas Tahun (Recent): {year_approved} dari {total}\n"
                        f"Kuartil: Q1:{q_counts['Q1']} | Q2:{q_counts['Q2']} | Q3:{q_counts['Q3']} | Q4:{q_counts['Q4']}"
                    )

                    note = page.add_text_annot(fitz.Point(heading_full.x0, max(0, heading_full.y0 - 15)), summary_content)
                    note.set_info(title="Ringkasan Validasi")
                    note.set_colors(stroke=PATTENS_BLUE, fill=PATTENS_BLUE)
                    note.update()
                    added_references_summary = True
                    
                except Exception as e:
                    logger.warning(f"Gagal membuat summary heading: {e}")   

            # --- PERSIAPAN TOKEN HALAMAN UNTUK PENCARIAN JURNAL ---
            # Kita expand agar kata yang tergabung (misal karena formatting) tetap bisa dicari per kata
            expanded_tokens = []
            for wi, w in enumerate(words_on_page):
                cleaned = _clean_scimago_title(w[4])
                if cleaned:
                    for part in cleaned.split():
                        expanded_tokens.append({'token': part, 'word_index': wi, 'rect': fitz.Rect(w[:4])})
            
            # --- BAGIAN 3: HIGHLIGHT NAMA JURNAL ---
            for result in detailed_results:
                # Cek apakah tipe jurnal atau terindeks (sesuai permintaan user untuk highlight jurnal)
                is_journal_or_indexed = (result.get('reference_type') == 'journal') or result.get('is_indexed')
                if not is_journal_or_indexed: continue

                journal_name = result.get('parsed_journal')
                if not journal_name or len(journal_name) < 2: continue

                search_tokens = _clean_scimago_title(journal_name).split()
                if not search_tokens: continue
                plen = len(search_tokens)

                # Scan halaman ini untuk mencari jurnal tersebut
                for i in range(len(expanded_tokens) - plen + 1):
                    # 1. Cek kecocokan token
                    potential_match_tokens = [t['token'] for t in expanded_tokens[i:i+plen]]
                    if potential_match_tokens == search_tokens:
                        # 2. [CRITICAL FIX] Cek apakah kata-kata ini SUDAH DIPAKAI referensi lain?
                        match_indices = [expanded_tokens[i+k]['word_index'] for k in range(plen)]
                        if any(idx in used_word_indices for idx in match_indices):
                            continue # Skip! Cari kemunculan berikutnya di halaman ini.
                        
                        # 3. Jika belum dipakai, KLAIM kata-kata ini.
                        
                        last_matched_word_index = expanded_tokens[i + plen - 1]['word_index']
                        last_word_of_match_text = words_on_page[last_matched_word_index][4]
                        
                        next_word_text = ""
                        if last_matched_word_index + 1 < len(words_on_page):
                            next_word_text = words_on_page[last_matched_word_index + 1][4]

                        disqualifiers = ['in', 'proceedings', 'conference', 'symposium', 'report', 'book']
                        if next_word_text.lower() in disqualifiers:
                            continue # Batalkan kecocokan ini, cari yang lain.
                        
                        # Aturan tambahan: jika kata terakhir diakhiri titik dan diikuti "In" (contoh: "scientometrics. In")
                        if last_word_of_match_text.endswith('.') and next_word_text.lower() == 'in':
                            continue
                        
                        used_word_indices.update(match_indices)
                        
                        # 4. Lakukan Highlighting & Note
                        try:
                            # Ambil rect unik untuk highlight (karena 1 kata asli bisa di-split jadi beberapa token)
                            unique_wi = sorted(list(set(match_indices)))
                            rects_to_highlight = [fitz.Rect(words_on_page[wi][:4]) for wi in unique_wi]
                            
                            first_rect = rects_to_highlight[0] if rects_to_highlight else None
                            is_indexed = result.get('is_indexed')
                            color = INDEXED_RGB if is_indexed else PINK_RGB

                            for r in rects_to_highlight:
                                annot = page.add_highlight_annot(r)
                                annot.set_colors(stroke=color, fill=color)
                                annot.update()
                            
                            if first_rect:
                                note_text = (f"Jurnal: {journal_name}\n"
                                             f"Tipe: {result.get('reference_type','N/A')}\n"
                                             f"Kuartil: {result.get('quartile','N/A')}")
                                note = page.add_text_annot(fitz.Point(first_rect.x0, max(0, first_rect.y0 - 15)), note_text)
                                note.set_info(title="Info Jurnal" if not is_indexed else "Terindeks Scimago")
                                note.set_colors(stroke=color, fill=color)
                                note.update()
                        except Exception as e:
                            logger.warning(f"Gagal highlight jurnal ref {result['reference_number']}: {e}")

                        break # Jurnal ini sudah ketemu di halaman ini, lanjut ke referensi berikutnya

            # --- BAGIAN 4: HIGHLIGHT TAHUN OUTDATED ---
            # Ambil tahun minimal dari hasil validasi global
            top_level_year = validation_results.get('year_range')
            min_year = (datetime.now().year - int(top_level_year)) if top_level_year else 0

            for result in detailed_results:
                parsed_year = result.get('parsed_year')
                # Hanya proses jika tahun valid DAN kurang dari minimal (outdated)
                if not parsed_year or not isinstance(parsed_year, int): continue
                if parsed_year >= min_year: continue 

                year_str = str(parsed_year)
                
                # Cari tahun di halaman ini yang BELUM DIKLAIM
                match_found_on_page = False
                for wi, w in enumerate(words_on_page):
                    # Bersihkan kata dari tanda baca agar "2020." atau "(2020)" terbaca "2020"
                    clean_word = re.sub(r'[^0-9]', '', w[4])
                    
                    # 1. Cek kecocokan tahun
                    if clean_word == year_str:
                        # 2. [CRITICAL FIX] Cek claim
                        if wi in used_word_indices:
                            continue # Tahun ini sudah dipakai referensi lain (atau bagian dari judul jurnal)
                        
                        # 3. Klaim
                        used_word_indices.add(wi)
                        match_found_on_page = True

                        # 4. Highlight & Note
                        try:
                            r = fitz.Rect(w[:4])
                            h = page.add_highlight_annot(r)
                            h.set_colors(stroke=YEAR_RGB, fill=YEAR_RGB)
                            h.update()

                            note_text = f"Tahun: {year_str}\nMinimal: {min_year}\nStatus: Outdated"
                            note = page.add_text_annot(fitz.Point(r.x0, max(0, r.y0 - 15)), note_text)
                            note.set_info(title="Tahun Outdated")
                            note.set_colors(stroke=YEAR_RGB, fill=YEAR_RGB)
                            note.update()
                        except Exception as e:
                             logger.warning(f"Gagal highlight tahun ref {result['reference_number']}: {e}")
                        
                        break # Tahun untuk referensi INI sudah ketemu, lanjut referensi berikutnya

        # Finalisasi PDF
        pdf_bytes = pdf.tobytes()
        pdf.close()
        return pdf_bytes, None

    except Exception as e:
        logger.error(f"Fatal error di create_annotated_pdf: {e}", exc_info=True)
        return None, "Gagal total saat proses anotasi PDF."
    
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