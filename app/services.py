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
from statistics import median

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

        REFERENCE_HEADINGS = [
            "daftar pustaka", "daftar referensi", "referensi",
            "bibliography", "references", "pustaka rujukan", "reference"
        ]
        # Normalizer to handle spaced small-caps like "R E F E R E N C E S"
        def _norm_heading(s: str) -> str:
            s = s.lower()
            # keep letters only to collapse spaced caps, drop digits/punct
            return re.sub(r'[^a-z]+', '', s)

        targets = [re.sub(r'\s+', '', h) for h in REFERENCE_HEADINGS]
        start_index = -1

        # 1) Cari judul dari depan ke belakang (toleran terhadap small-caps/spacing dan colon)
        for i, para in enumerate(paragraphs):
            para_clean = para.lower().strip(':').strip()
            norm_line = _norm_heading(para_clean)
            if any(t in norm_line for t in targets) and len(para.split()) <= 8:
                start_index = i
                logger.info(f"Judul Daftar Pustaka/References ditemukan di paragraf #{i}: '{para}'")
                break

        # 2) Cek kemungkinan judul dua baris (gabungkan dua baris bertetangga)
        if start_index == -1:
            for i in range(len(paragraphs) - 1):
                comb = paragraphs[i] + ' ' + paragraphs[i + 1]
                if any(t in _norm_heading(comb) for t in targets):
                    start_index = i + 1  # konten mulai di bawah baris kedua
                    logger.info(f"Judul References terdeteksi dalam dua baris di sekitar paragraf #{i} dan #{i+1}")
                    break
        
        if start_index == -1:
            # 3) Fallback konservatif: cari blok yang tampak seperti referensi di paruh akhir dokumen
            half = max(0, len(paragraphs) // 2)
            for i in range(half, len(paragraphs)):
                window = paragraphs[i:i + 8]
                if not window:
                    continue
                ref_like = sum(1 for p in window if _is_likely_reference(p))
                if ref_like >= 3:
                    start_index = i
                    logger.info("Fallback: Menggunakan deteksi pola referensi tanpa heading eksplisit.")
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
            words_on_page = page.get_text("words")  # (x0,y0,x1,y1, word, block_no, line_no, word_no)

            used_word_indices = set()
            
            # ✅ RESET heading_rects untuk setiap halaman (hindari carry-over dari page sebelumnya)
            current_page_heading_rects = []

            # Group words by (block_no, line_no) to create reliable line structures
            by_line = {}
            for wi, w in enumerate(words_on_page):
                if not w[4] or not str(w[4]).strip():
                    continue
                key = (w[5], w[6])
                if key not in by_line:
                    by_line[key] = {
                        'y': w[1],
                        'x_min': w[0],
                        'x_max': w[2],
                        'word_indices': [wi],
                        'words': [w[4]],
                        'rects': [fitz.Rect(w[:4])]
                    }
                else:
                    by_line[key]['y'] = min(by_line[key]['y'], w[1])
                    by_line[key]['x_min'] = min(by_line[key]['x_min'], w[0])
                    by_line[key]['x_max'] = max(by_line[key]['x_max'], w[2])
                    by_line[key]['word_indices'].append(wi)
                    by_line[key]['words'].append(w[4])
                    by_line[key]['rects'].append(fitz.Rect(w[:4]))

            # Convert to ordered list of lines, sorted by Y
            lines = sorted(by_line.values(), key=lambda d: d['y'])

            # --- KUMPULKAN MARKER NOMOR REFERENSI DI HALAMAN INI ---
            def _collect_reference_markers(words):
                markers = []  # list of dict {num:int, y:float, x:float, wi:int}
                for wi, w in enumerate(words):
                    t = str(w[4]).strip()
                    m = None
                    # Bentuk umum dalam satu token
                    for pat in [r'^\[(\d+)\]$', r'^\((\d+)\)$', r'^(\d+)\.$']:
                        m = re.match(pat, t)
                        if m:
                            try:
                                num = int(m.group(1))
                                markers.append({'num': num, 'y': w[1], 'x': (w[0]+w[2])/2.0, 'wi': wi})
                            except Exception:
                                pass
                            break
                # Urutkan berdasarkan y (atas ke bawah)
                markers.sort(key=lambda d: d['y'])
                return markers

            markers = _collect_reference_markers(words_on_page)
            markers_by_number = {}
            for idx, mk in enumerate(markers):
                mk_next_y = markers[idx + 1]['y'] if idx + 1 < len(markers) else None
                mk['next_y'] = mk_next_y
                markers_by_number[mk['num']] = mk

            # --- BAGIAN 1: DETEKSI & SUMMARY HEADING (Tidak berubah banyak) ---
            if not start_annotating:
                # (Logika deteksi heading dipertahankan sama seperti sebelumnya agar stabil)
                try:
                    heading_tokens = ['daftar pustaka', 'references', 'daftar referensi', 'bibliography', 'pustaka rujukan', 'referensi']

                    for li, line in enumerate(lines):
                        line_text = ' '.join(line['words']).strip().lower()
                        norm_line = re.sub(r'[^a-z0-9\s]', '', line_text)

                        found_ht = False
                        for ht in heading_tokens:
                            if norm_line == ht:
                                found_ht = True
                            elif li + 1 < len(lines):
                                next_text = re.sub(r'[^a-z0-9\s]', '', ' '.join(lines[li + 1]['words']).strip().lower())
                                if f"{norm_line} {next_text}".strip() == ht:
                                    found_ht = True
                                    # Tambahkan rects baris berikutnya jika judul 2 baris
                                    line['rects'].extend(lines[li + 1]['rects'])

                        if found_ht:
                            # Cek konteks 7 baris ke depan
                            context = ' '.join([' '.join(lines[j]['words']) for j in range(li + 1, min(len(lines), li + 8))])
                            if _looks_like_reference_line(context):
                                start_annotating = True
                                current_page_heading_rects = line['rects']
                                logger.info(f"🎯 FOUND References heading at page {page_num + 1}, Y={line['y']:.1f}, start_annotating=True")
                                break

                    if not start_annotating:
                        continue  # Lanjut ke halaman berikutnya jika belum ketemu

                except Exception:
                    continue

            # --- BAGIAN 2: GAMBAR SUMMARY NOTE PADA HEADING ---
            if start_annotating and not added_references_summary and current_page_heading_rects:
                try:
                    heading_full = fitz.Rect(current_page_heading_rects[0])
                    for r in current_page_heading_rects[1:]: heading_full.include_rect(r)
                    
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
            
            def _is_line_a_reference_entry(text_line: str) -> bool:
                """
                Memeriksa apakah sebuah baris teks dimulai dengan format yang umum
                untuk entri daftar pustaka.
                """
                line = text_line.strip()
                # Dimulai dengan [1] atau (1) atau 1.
                if re.match(r'^(\[\d+\]|\(\d+\)|\d+\.)', line):
                    return True
                # Dimulai dengan format Nama, F. (gaya APA, Chicago, dll.)
                if re.match(r'^[A-Z][a-zA-Z\-\']{2,},\s+([A-Z]\.\s?)+', line):
                    return True
                return False
            
            # Helper: strict detector for reference entry starts (avoid body text with citation years)
            def _looks_like_reference_entry_start_line_text(t: str) -> bool:
                t = t.strip()
                if re.match(r'^(\[\d+\]|\(\d+\)|\d+\.)', t):
                    # Hindari bagian outline/penomoran body: wajib ada indikasi referensi (tahun 4 digit)
                    return bool(re.search(r'(19|20)\d{2}', t))
                if re.match(r'^[A-Z][a-zA-Z\-\']{2,},\s([A-Z]\.\s?)+', t):
                    return True
                return False

            # Helper: check if a matched token sequence sits within quotes on its line (likely article title)
            def _is_within_quotes(match_word_indices):
                if not match_word_indices:
                    return False
                # assume all tokens are on the same line; if not, use the first one's line
                first_wi = match_word_indices[0]
                if first_wi < 0 or first_wi >= len(words_on_page):
                    return False
                key = (words_on_page[first_wi][5], words_on_page[first_wi][6])
                line = by_line.get(key)
                if not line:
                    return False
                texts = line['words']
                # locate quote-like tokens in the line
                quote_open_chars = {'"', '“', '‘', "'"}
                quote_close_chars = {'"', '”', '’', "'"}
                first_quote_idx = None
                last_quote_idx = None
                for idx, t in enumerate(texts):
                    if any(ch in t for ch in quote_open_chars):
                        if first_quote_idx is None:
                            first_quote_idx = idx
                    if any(ch in t for ch in quote_close_chars):
                        last_quote_idx = idx
                if first_quote_idx is None or last_quote_idx is None or last_quote_idx <= first_quote_idx:
                    return False
                min_m = min(match_word_indices)
                max_m = max(match_word_indices)
                # map indices in the full page to indices in this line
                try:
                    rel_indices = [line['word_indices'].index(i) for i in match_word_indices]
                except ValueError:
                    return False
                return min(rel_indices) > first_quote_idx and max(rel_indices) < last_quote_idx

            # Heuristic: extend quotes detection across adjacent lines within the same block
            def _is_within_quotes_extended(match_word_indices):
                try:
                    if _is_within_quotes(match_word_indices):
                        return True
                    wi = match_word_indices[0]
                    bno = words_on_page[wi][5]
                    lno = words_on_page[wi][6]
                    # collect prev, curr, next lines in same block
                    neighbors = []
                    for dl in (-1, 0, 1):
                        key = (bno, lno + dl)
                        if key in by_line:
                            neighbors.append(' '.join(by_line[key]['words']))
                    joined = '\n'.join(neighbors)
                    # Count quotes; if odd count before the match line, assume inside quotes
                    # Simplified parity approach
                    quote_chars = ['"', '“', '”', '‘', '’', "'"]
                    total_quotes = sum(joined.count(ch) for ch in quote_chars)
                    # If there are at least 2 quotes in neighbors, and current line sits between, we assume it's within quotes
                    return total_quotes >= 2 and any(ch in neighbors[0] for ch in quote_chars)
                except Exception:
                    return False

            # ✅ NEW FUNCTION: Verifikasi bahwa matched text muncul SETELAH tanda kutip penutup
            def _appears_after_closing_quote(match_word_indices):
                """
                Dalam format APA, nama jurnal SELALU muncul setelah penutup kutip judul artikel:
                Penulis (Tahun). "Judul Artikel." Nama Jurnal, Volume.
                
                Returns True jika matched text muncul setelah tanda kutip penutup
                (kemungkinan besar adalah nama jurnal yang benar)
                """
                if not match_word_indices:
                    return False
                
                first_match_wi = match_word_indices[0]
                
                # Tanda kutip penutup yang umum digunakan (termasuk variasi Unicode)
                quote_close_chars = {'"', '”', '’', "'", '»', '›'}
                
                # Scan backward dari match position (max 20 kata ke belakang)
                # untuk mencari tanda kutip penutup
                for i in range(first_match_wi - 1, max(0, first_match_wi - 20), -1):
                    word_text = words_on_page[i][4]
                    
                    # Cek apakah word ini mengandung tanda kutip penutup
                    if any(ch in word_text for ch in quote_close_chars):
                        # ✅ Ditemukan tanda kutip penutup sebelum match
                        # Ini kemungkinan besar adalah nama jurnal yang benar
                        return True
                    
                    # Stop jika menemukan nomor referensi (berarti kita sudah melewati batas)
                    if i == max(0, first_match_wi - 20):
                        break
                
                return False

            # NEW: detect if there are any quote characters around the match line (same block, +/- 1 line)
            def _has_any_quotes_nearby(match_word_indices):
                try:
                    if not match_word_indices:
                        return False
                    wi = match_word_indices[0]
                    bno = words_on_page[wi][5]
                    lno = words_on_page[wi][6]
                    neighbors = []
                    for dl in (-1, 0, 1):
                        key = (bno, lno + dl)
                        if key in by_line:
                            neighbors.append(' '.join(by_line[key]['words']))
                    joined = '\n'.join(neighbors)
                    quote_chars = ['"', '“', '”', '‘', '’', "'"]
                    return any(ch in joined for ch in quote_chars)
                except Exception:
                    return False

            # Fallback: setelah tanda kutip penutup, ambil frasa berikutnya sebagai kandidat nama jurnal
            def _fallback_highlight_journal_after_quote(clean_query_tokens):
                """Cari tanda kutip penutup di halaman, lalu ambil 1-5 kata setelahnya
                sebagai kandidat nama jurnal, dan cocokkan secara ringan.
                Return: tuple(highlight_indices:list[int], first_rect:fitz.Rect) atau (None, None)
                """
                try:
                    stop_tokens = {'vol', 'volume', 'no', 'issue', 'pages', 'pp', 'doi', 'https', 'http'}
                    for wi, w in enumerate(words_on_page):
                        t = w[4]
                        if any(ch in t for ch in ['"', '”', '’', "'", '»', '›']):
                            # ambil sampai 5 kata berikutnya sebagai kandidat
                            cand_indices = []
                            cand_tokens = []
                            for k in range(1, 6):
                                if wi + k >= len(words_on_page):
                                    break
                                nxt = words_on_page[wi + k][4]
                                cleaned = _clean_scimago_title(nxt)
                                if not cleaned:
                                    continue
                                # stop jika ketemu token penghenti
                                if cleaned in stop_tokens:
                                    break
                                cand_indices.append(wi + k)
                                cand_tokens.append(cleaned)
                                # untuk nama satu token (mis. pnas, ecancer) cukup 1 token
                                if len(clean_query_tokens) == 1 and len(cand_tokens) >= 1:
                                    break
                            if not cand_tokens:
                                continue
                            # kecocokan ringan: exact pada token pertama atau semua token sama
                            if len(clean_query_tokens) == 1:
                                if cand_tokens[0] == clean_query_tokens[0]:
                                    # valid kandidat
                                    rects = [fitz.Rect(words_on_page[idx][:4]) for idx in cand_indices[:1]]
                                    return cand_indices[:1], (rects[0] if rects else None)
                            else:
                                # bandingkan dengan jaccard pada set token kecil
                                qset = set(clean_query_tokens)
                                cset = set(cand_tokens)
                                inter = len(qset & cset)
                                uni = max(1, len(qset | cset))
                                if inter / uni >= 0.6:
                                    rects = [fitz.Rect(words_on_page[idx][:4]) for idx in cand_indices]
                                    return cand_indices, (rects[0] if rects else None)
                except Exception:
                    return None, None
                return None, None
            
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
                matched = False
                for i in range(len(expanded_tokens) - max(plen, 1) + 1):
                    # 1. Cek kecocokan token (default, per-kata)
                    potential_match_tokens = [t['token'] for t in expanded_tokens[i:i+plen]]
                    matched_window_len = None
                    if potential_match_tokens == search_tokens:
                        matched_window_len = plen
                    # 1b. Fallback untuk kasus small-caps/letter-spaced (mis. P N A S -> "PNAS")
                    elif len(search_tokens) == 1:
                        query = search_tokens[0]
                        combined = ""
                        tmp_indices = []
                        # Batasi panjang gabungan untuk efisiensi
                        max_join = min(len(expanded_tokens) - i, max(2, len(query)))
                        for k in range(max_join):
                            tok = expanded_tokens[i + k]['token']
                            combined += tok
                            tmp_indices.append(expanded_tokens[i + k]['word_index'])
                            # Early stop jika tidak lagi prefix dari query
                            if not query.startswith(combined):
                                break
                            if combined == query:
                                potential_match_tokens = [combined]
                                matched_window_len = k + 1
                                break

                    if matched_window_len is not None:
                        # 2. [CRITICAL FIX] Cek apakah kata-kata ini SUDAH DIPAKAI referensi lain?
                        match_indices = [expanded_tokens[i+k]['word_index'] for k in range(matched_window_len)]
                        if any(idx in used_word_indices for idx in match_indices):
                            continue # Skip! Cari kemunculan berikutnya di halaman ini.
                        
                        # 3. Jika belum dipakai, KLAIM kata-kata ini.
                        last_matched_word_index = expanded_tokens[i + matched_window_len - 1]['word_index']
                        last_word_of_match_text = words_on_page[last_matched_word_index][4]
                        
                        # 🔥 CRITICAL: CLAIM SELURUH REFERENCE ENTRY!
                        # Cari Y coordinate dari jurnal match
                        first_match_word_idx = match_indices[0]
                        journal_y = words_on_page[first_match_word_idx][1]
                        
                        # Find reference marker for this entry
                        ref_num = result.get('reference_number')
                        if ref_num and ref_num in markers_by_number:
                            marker_info = markers_by_number[ref_num]
                            marker_y = marker_info['y']
                            next_marker_y = marker_info.get('next_y')
                            
                            # CLAIM all words in this reference entry (between this marker and next marker)
                            for wi, w in enumerate(words_on_page):
                                word_y = w[1]
                                if word_y >= marker_y - 5:  # Start from marker
                                    if next_marker_y is None or word_y < next_marker_y - 5:
                                        used_word_indices.add(wi)
                        
                        next_word_text = ""
                        if last_matched_word_index + 1 < len(words_on_page):
                            next_word_text = words_on_page[last_matched_word_index + 1][4]

                        disqualifiers = ['in', 'proceedings', 'conference', 'symposium', 'report', 'book']
                        if next_word_text.lower() in disqualifiers:
                            continue # Batalkan kecocokan ini, cari yang lain.
                        
                        # Aturan tambahan: jika kata terakhir diakhiri titik dan diikuti "In" (contoh: "scientometrics. In")
                        if last_word_of_match_text.endswith('.') and next_word_text.lower() == 'in':
                            continue

                        # FILTER 1: If the matched phrase is within quotes on its line, likely part of article title → skip
                        if _is_within_quotes(match_indices) or _is_within_quotes_extended(match_indices):
                            continue
                        
                        # FILTER 2: Require "after closing quote" ONLY when quotes exist nearby; otherwise, don't block
                        if _has_any_quotes_nearby(match_indices):
                            if not _appears_after_closing_quote(match_indices):
                                # Skip jika match TIDAK muncul setelah kutip penutup (kemungkinan bagian dari judul)
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

                        matched = True
                        break # Jurnal ini sudah ketemu di halaman ini, lanjut ke referensi berikutnya

                # Fallback: jika belum matched dengan pencarian token biasa, coba heuristik setelah tanda kutip
                if not matched:
                    cand_indices, first_rect = _fallback_highlight_journal_after_quote(search_tokens)
                    if cand_indices:
                        try:
                            unique_wi = sorted(list(set(cand_indices)))
                            rects_to_highlight = [fitz.Rect(words_on_page[wi][:4]) for wi in unique_wi]
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
                            
                            # 🔥 CRITICAL: CLAIM SELURUH REFERENCE ENTRY untuk fallback juga!
                            ref_num = result.get('reference_number')
                            if ref_num and ref_num in markers_by_number:
                                marker_info = markers_by_number[ref_num]
                                marker_y = marker_info['y']
                                next_marker_y = marker_info.get('next_y')
                                
                                for wi, w in enumerate(words_on_page):
                                    word_y = w[1]
                                    if word_y >= marker_y - 5:
                                        if next_marker_y is None or word_y < next_marker_y - 5:
                                            used_word_indices.add(wi)
                            
                            for wi in unique_wi:
                                used_word_indices.add(wi)
                        except Exception as e:
                            logger.warning(f"Fallback highlight gagal untuk ref {result['reference_number']}: {e}")

# --- BAGIAN 4: HIGHLIGHT TAHUN OUTDATED ---
            top_level_year = validation_results.get('year_range')
            current_year = datetime.now().year
            min_year_threshold = int(top_level_year) if top_level_year else 5
            min_year = current_year - min_year_threshold
            year_pattern = re.compile(r'\b(19\d{2}|20\d{2})\b')

            y_start_threshold = 0
            if current_page_heading_rects:
                try:
                    heading_full = fitz.Rect(current_page_heading_rects[0])
                    for r in current_page_heading_rects[1:]:
                        heading_full.include_rect(r)
                    y_start_threshold = heading_full.y1 - 2
                except Exception:
                    pass

            def _is_in_reference_region(rect):
                if current_page_heading_rects and y_start_threshold > 0:
                    if rect.y0 < y_start_threshold:
                        return False
                elif not start_annotating:
                    return False
                return True

            def _is_year_in_quotes(word_idx):
                """
                Deteksi ketat: anggap 'di dalam kutip' HANYA bila pada baris yang sama
                terdapat tanda kutip ganda pembuka dan penutup, dan posisi tahun berada di antaranya.
                - Hindari menganggap apostrof (') sebagai kutip (banyak muncul di nama O'Connor).
                - Tambahkan dukungan glyph PDF yang sering muncul sebagai hasil decoding: ô (open), ö (close).
                """
                try:
                    # Hanya double-quotes untuk mencegah false positive dari apostrof pada nama
                    quote_open_chars = {'"', '“', 'ô'}   # ASCII, curly open, and PDF-decoded open
                    quote_close_chars = {'"', '”', 'ö'}  # ASCII, curly close, and PDF-decoded close

                    key = (words_on_page[word_idx][5], words_on_page[word_idx][6])
                    line = by_line.get(key)
                    if not line:
                        return False
                    try:
                        rel_idx = line['word_indices'].index(word_idx)
                    except ValueError:
                        return False

                    # Helper closures
                    def line_open_before(idx, line_words):
                        # Count opening quotes in earlier tokens OR within current token (approximation)
                        current_token = str(words_on_page[word_idx][4])
                        if any(ch in current_token for ch in quote_open_chars):
                            return True
                        for i, t in enumerate(line_words):
                            if i >= idx: break
                            if any(ch in t for ch in quote_open_chars):
                                return True
                        return False

                    def line_close_after(idx, line_words):
                        # Count closing quotes in later tokens OR within current token (approximation)
                        current_token = str(words_on_page[word_idx][4])
                        if any(ch in current_token for ch in quote_close_chars):
                            return True
                        for i in range(idx + 1, len(line_words)):
                            if any(ch in line_words[i] for ch in quote_close_chars):
                                return True
                        return False

                    def line_has_any(chars, line_words):
                        return any(any(ch in t for ch in chars) for t in line_words)

                    # Special: if the year appears parenthesized like (2011), treat as NOT in quotes
                    try:
                        cur_txt = str(words_on_page[word_idx][4])
                        prev_txt = str(words_on_page[line['word_indices'][rel_idx-1]][4]) if rel_idx-1 >= 0 else ''
                        next_txt = str(words_on_page[line['word_indices'][rel_idx+1]][4]) if rel_idx+1 < len(line['word_indices']) else ''
                        if '(' in cur_txt or ')' in cur_txt or prev_txt.endswith('(') or next_txt.startswith(')'):
                            return False
                    except Exception:
                        pass

                    # 1) Same-line strict
                    same_line = line_open_before(rel_idx, line['words']) and line_close_after(rel_idx, line['words'])
                    if same_line:
                        return True

                    # 2) Multi-line (strict double-quote only within same block):
                    bno, lno = words_on_page[word_idx][5], words_on_page[word_idx][6]
                    prev_line = by_line.get((bno, lno - 1))
                    next_line = by_line.get((bno, lno + 1))

                    # Case A: prev has open, current has close after year
                    if prev_line and line_close_after(rel_idx, line['words']):
                        if line_has_any(quote_open_chars, prev_line['words']) and not line_has_any(quote_close_chars, prev_line['words']):
                            return True

                        # Extra heuristic: author-year line then title (close quote in current line)
                        try:
                            prev_text = ' '.join(prev_line['words'])
                            if re.search(r"\((19|20)\d{2}\)\.?\s*$", prev_text):
                                return True
                        except Exception:
                            pass

                    # Case B: current has open before year, next has close
                    if next_line and line_open_before(rel_idx, line['words']):
                        if line_has_any(quote_close_chars, next_line['words']) and not line_has_any(quote_open_chars, next_line['words']):
                            return True

                    # 3) Title-like heuristic: detect year ranges or closing quote near the token
                    try:
                        line_text = ' '.join(line['words'])
                        if re.search(r'(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}', line_text):
                            return True
                        # if the same token or the next token has a closing quote glyph, likely end of title
                        if any(ch in str(words_on_page[word_idx][4]) for ch in quote_close_chars):
                            return True
                        for offset in range(1, 4):
                            if rel_idx + offset < len(line['word_indices']):
                                nxt = str(words_on_page[line['word_indices'][rel_idx+offset]][4])
                                if any(ch in nxt for ch in quote_close_chars):
                                    return True
                    except Exception:
                        pass

                    return False
                except Exception:
                    return False

            # SINGLE SCAN dengan duplicate tracking PER REFERENSI
            highlighted_years_per_reference = {}  # Key: reference_start_line, Value: set of highlighted years
            
            for wi, w in enumerate(words_on_page):
                
                word_text = str(w[4])
                for match in year_pattern.finditer(word_text):
                    year_str = match.group(0)
                    year_int = int(year_str)
                    
                    if year_int >= min_year:
                        continue
                    if _is_year_in_quotes(wi):
                        continue
                    
                    word_rect = fitz.Rect(w[:4])
                    
                    if not _is_in_reference_region(word_rect):
                        continue
                    
                    try:
                        current_bno, current_lno = w[5], w[6]
                        current_key = (current_bno, current_lno)
                        current_line_info = by_line.get(current_key)
                        
                        is_part_of_reference_entry = False
                        if current_line_info:
                            current_line_text = ' '.join(current_line_info['words'])
                            # Cek baris saat ini
                            if _is_line_a_reference_entry(current_line_text):
                                is_part_of_reference_entry = True
                            else:
                                # Jika baris saat ini gagal, cek baris sebelumnya sebagai fallback
                                prev_key = (current_bno, current_lno - 1)
                                prev_line_info = by_line.get(prev_key)
                                if prev_line_info:
                                    prev_line_text = ' '.join(prev_line_info['words'])
                                    if _is_line_a_reference_entry(prev_line_text):
                                        # Baris sebelumnya adalah awal referensi, jadi baris ini adalah lanjutannya.
                                        is_part_of_reference_entry = True

                        if not is_part_of_reference_entry:
                            continue # Bukan bagian dari entri referensi. LEWATI.

                    except Exception:
                        continue
                    
                    # Identifikasi referensi mana yang sedang kita proses
                    try:
                        # Cari baris awal referensi ini (untuk tracking per-referensi)
                        reference_start_line = None
                        bno, lno = w[5], w[6]
                        
                        # Cari mundur hingga 5 baris dalam blok yang sama untuk menemukan awal referensi
                        for i in range(lno, max(-1, lno - 5), -1):
                            key = (bno, i)
                            line_info = by_line.get(key)
                            if line_info:
                                line_text = ' '.join(line_info['words'])
                                if _is_line_a_reference_entry(line_text):
                                    # Gunakan teks baris ini sebagai identifier unik referensi
                                    reference_start_line = line_text
                                    break
                        
                        if not reference_start_line:
                            # Fallback: gunakan koordinat Y sebagai identifier
                            reference_start_line = f"ref_at_y_{round(w[1], 1)}"
                        
                        # Inisialisasi set untuk referensi ini jika belum ada
                        if reference_start_line not in highlighted_years_per_reference:
                            highlighted_years_per_reference[reference_start_line] = set()
                        
                        # PENTING: Cek apakah tahun ini sudah di-highlight di REFERENSI INI saja
                        if year_str in highlighted_years_per_reference[reference_start_line]:
                            continue  # Skip, tahun ini sudah di-highlight di referensi yang sama
                        
                        # Tandai bahwa tahun ini sudah di-highlight di referensi ini
                        highlighted_years_per_reference[reference_start_line].add(year_str)
                        
                    except Exception:
                        continue
                    
                    try:
                        start_pos = match.start()
                        end_pos = match.end()
                        word_len = len(word_text)
                        
                        if word_len > 0:
                            x_start_ratio = start_pos / word_len
                            x_end_ratio = end_pos / word_len
                            word_width = word_rect.x1 - word_rect.x0
                            year_rect = fitz.Rect(
                                word_rect.x0 + (word_width * x_start_ratio),
                                word_rect.y0,
                                word_rect.x0 + (word_width * x_end_ratio),
                                word_rect.y1
                            )
                        else:
                            year_rect = word_rect
                        
                        h = page.add_highlight_annot(year_rect)
                        h.set_colors(stroke=YEAR_RGB, fill=YEAR_RGB)
                        h.update()
                        
                        note_text = f"Tahun: {year_str}\\nMinimal: {min_year}\\nStatus: Outdated"
                        note = page.add_text_annot(
                            fitz.Point(year_rect.x0, max(0, year_rect.y0 - 15)), 
                            note_text
                        )
                        note.set_info(title="Tahun Outdated")
                        note.set_colors(stroke=YEAR_RGB, fill=YEAR_RGB)
                        note.update()
                    except Exception as e:
                        logger.error(f"Error highlighting year: {e}")

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