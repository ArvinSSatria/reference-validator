import fitz
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
    REFERENCE_HEADINGS = ["daftar pustaka", "daftar referensi","referensi", "reference", "references", "bibliography", "pustaka rujukan"]
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

        REFERENCE_HEADINGS = ["daftar pustaka", "daftar referensi", "referensi", "bibliography", "references", "pustaka rujukan"]
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
    
def _detect_layout(page, width_threshold=0.65):
    """
    Mendeteksi tata letak halaman (satu atau multi-kolom) berdasarkan
    lebar median dari blok-blok teks.

    Returns: 'single_column' atau 'multi_column'
    """
    page_width = page.rect.width
    if page_width == 0: return 'single_column' # Fallback

    # Gunakan 'blocks' untuk mendapatkan grup paragraf yang lebih alami
    blocks = page.get_text("blocks", sort=True)
    if not blocks: return 'single_column'

    # Filter blok yang terlalu kecil (kemungkinan noise atau nomor halaman)
    block_widths = [b[2] - b[0] for b in blocks if (b[3] - b[1]) > 8 and (b[2] - b[0]) > 20]
    if not block_widths: return 'single_column'

    median_width = median(block_widths)

    # Jika lebar median blok teks kurang dari 65% lebar halaman, anggap multi-kolom
    if median_width < page_width * width_threshold:
        logger.info(f"Halaman {page.number+1}: Terdeteksi layout multi-kolom (lebar median: {median_width:.1f} vs lebar halaman: {page_width:.1f})")
        return 'multi_column'
    else:
        logger.info(f"Halaman {page.number+1}: Terdeteksi layout satu kolom (lebar median: {median_width:.1f} vs lebar halaman: {page_width:.1f})")
        return 'single_column'

def _annotate_multi_column_page(
    page,
    page_num,
    detailed_results,
    validation_results,
    start_annotating,
    added_references_summary,
    colors
):
    """
    Memproses dan menganotasi SATU halaman PDF dengan asumsi tata letak multi-kolom.
    Fungsi ini berisi logika yang sudah terbukti andal untuk format dua kolom.

    Args:
        page (fitz.Page): Objek halaman PyMuPDF yang akan diproses.
        page_num (int): Nomor halaman (berbasis nol).
        detailed_results (list): Hasil analisis detail dari AI.
        validation_results (dict): Ringkasan hasil validasi.
        start_annotating (bool): Status apakah bagian referensi sudah ditemukan.
        added_references_summary (bool): Status apakah kotak ringkasan sudah ditambahkan.
        colors (dict): Dictionary berisi nilai RGB untuk highlight.

    Returns:
        tuple[bool, bool, list]: Status terbaru dari (start_annotating, added_references_summary)
                                 dan daftar rect heading yang ditemukan di halaman ini.
    """
    # Ekstrak warna dari dictionary
    PATTENS_BLUE = colors['PATTENS_BLUE']
    INDEXED_RGB = colors['INDEXED_RGB']
    PINK_RGB = colors['PINK_RGB']
    YEAR_RGB = colors['YEAR_RGB']

    words_on_page = page.get_text("words")
    used_word_indices = set()
    current_page_heading_rects = []

    # Group words by (block_no, line_no) to create reliable line structures
    by_line = {}
    for wi, w in enumerate(words_on_page):
        if not w[4] or not str(w[4]).strip(): continue
        key = (w[5], w[6])
        if key not in by_line:
            by_line[key] = {'y': w[1], 'x_min': w[0], 'x_max': w[2], 'word_indices': [wi], 'words': [w[4]], 'rects': [fitz.Rect(w[:4])]}
        else:
            by_line[key]['y'] = min(by_line[key]['y'], w[1])
            by_line[key]['x_min'] = min(by_line[key]['x_min'], w[0])
            by_line[key]['x_max'] = max(by_line[key]['x_max'], w[2])
            by_line[key]['word_indices'].append(wi)
            by_line[key]['words'].append(w[4])
            by_line[key]['rects'].append(fitz.Rect(w[:4]))
    lines = sorted(by_line.values(), key=lambda d: d['y'])

    # Helper untuk cek apakah sebuah baris terlihat seperti referensi
    def _looks_like_reference_line(text):
        if not text or not isinstance(text, str): return False
        if re.search(r'\(\d{4}\)|\b\d{4}\b', text): return True
        if re.match(r'^(\[\d+\]|\(\d+\)|\d+\.)', text.strip()): return True
        return False

    # KUMPULKAN MARKER NOMOR REFERENSI DI HALAMAN INI
    def _collect_reference_markers(words):
        markers = []
        for wi, w in enumerate(words):
            t = str(w[4]).strip()
            m = None
            for pat in [r'^\[(\d+)\]$', r'^\((\d+)\)$', r'^(\d+)\.$']:
                m = re.match(pat, t)
                if m:
                    try:
                        num = int(m.group(1))
                        markers.append({'num': num, 'y': w[1], 'x': (w[0]+w[2])/2.0, 'wi': wi})
                    except Exception: pass
                    break
        markers.sort(key=lambda d: d['y'])
        return markers
    markers = _collect_reference_markers(words_on_page)
    markers_by_number = {}
    for idx, mk in enumerate(markers):
        mk_next_y = markers[idx + 1]['y'] if idx + 1 < len(markers) else None
        mk['next_y'] = mk_next_y
        markers_by_number[mk['num']] = mk

    # BAGIAN 1: DETEKSI HEADING
    if not start_annotating:
        try:
            heading_tokens = ['daftar pustaka', 'references', 'daftar referensi', 'bibliography', 'pustaka rujukan', 'referensi']
            for li, line in enumerate(lines):
                line_text = ' '.join(line['words']).strip().lower()
                norm_line = re.sub(r'[^a-z0-9\s]', '', line_text)
                found_ht = False
                for ht in heading_tokens:
                    if norm_line == ht: found_ht = True
                    elif li + 1 < len(lines):
                        next_text = re.sub(r'[^a-z0-9\s]', '', ' '.join(lines[li + 1]['words']).strip().lower())
                        if f"{norm_line} {next_text}".strip() == ht:
                            found_ht = True
                            line['rects'].extend(lines[li + 1]['rects'])
                if found_ht:
                    context = ' '.join([' '.join(lines[j]['words']) for j in range(li + 1, min(len(lines), li + 8))])
                    if _looks_like_reference_line(context):
                        start_annotating = True
                        current_page_heading_rects = line['rects']
                        logger.info(f"🎯 Ditemukan judul Daftar Pustaka di halaman {page_num + 1}, Y={line['y']:.1f}, memulai anotasi.")
                        break
            if not start_annotating:
                return start_annotating, added_references_summary, []
        except Exception:
            return start_annotating, added_references_summary, []

    # BAGIAN 2: GAMBAR SUMMARY NOTE PADA HEADING
    if start_annotating and not added_references_summary and current_page_heading_rects:
        try:
            heading_full = fitz.Rect(current_page_heading_rects[0])
            for r in current_page_heading_rects[1:]: heading_full.include_rect(r)
            h = page.add_highlight_annot(heading_full)
            h.set_colors(stroke=PATTENS_BLUE, fill=PATTENS_BLUE)
            h.update()

            total = len(detailed_results)
            journal_count = sum(1 for r in detailed_results if r.get('reference_type') == 'journal')
            sjr_count = sum(1 for r in detailed_results if r.get('is_indexed'))
            year_approved = sum(1 for r in detailed_results if r.get('validation_details', {}).get('year_recent'))
            q_counts = {'Q1':0,'Q2':0,'Q3':0,'Q4':0,'Not Found':0}
            for r in detailed_results:
                q = r.get('quartile')
                if q in q_counts: q_counts[q] += 1
                elif q: q_counts['Not Found'] += 1

            summary_content = (f"Total Referensi: {total}\n"
                f"Artikel Jurnal: {journal_count} ({ (journal_count/total*100) if total else 0:.1f}%)\n"
                f"Artikel Non-Jurnal: {total - journal_count} ({ ((total - journal_count)/total*100) if total else 0:.1f}%)\n"
                f"Terindeks SJR: {sjr_count} ({ (sjr_count/total*100) if total else 0:.1f}%)\n"
                f"Validitas Tahun (Recent): {year_approved} dari {total}\n"
                f"Kuartil: Q1:{q_counts['Q1']} | Q2:{q_counts['Q2']} | Q3:{q_counts['Q3']} | Q4:{q_counts['Q4']}")
            note = page.add_text_annot(fitz.Point(heading_full.x0, max(0, heading_full.y0 - 15)), summary_content)
            note.set_info(title="Ringkasan Validasi")
            note.set_colors(stroke=PATTENS_BLUE, fill=PATTENS_BLUE)
            note.update()
            added_references_summary = True
        except Exception as e:
            logger.warning(f"Gagal membuat ringkasan heading: {e}")

    # PERSIAPAN TOKEN HALAMAN UNTUK PENCARIAN JURNAL
    expanded_tokens = []
    for wi, w in enumerate(words_on_page):
        cleaned = _clean_scimago_title(w[4])
        if cleaned:
            for part in cleaned.split():
                expanded_tokens.append({'token': part, 'word_index': wi, 'rect': fitz.Rect(w[:4])})

    # --- Helper-helper lokal yang spesifik untuk logika ini ---
    def _is_within_quotes(match_word_indices):
        if not match_word_indices: return False
        first_wi = match_word_indices[0]
        if first_wi < 0 or first_wi >= len(words_on_page): return False
        key = (words_on_page[first_wi][5], words_on_page[first_wi][6])
        line = by_line.get(key)
        if not line: return False
        texts = line['words']
        quote_open_chars = {'"', '“', '‘', "'"}
        quote_close_chars = {'"', '”', '’', "'"}
        first_quote_idx = None
        last_quote_idx = None
        for idx, t in enumerate(texts):
            if any(ch in t for ch in quote_open_chars):
                if first_quote_idx is None: first_quote_idx = idx
            if any(ch in t for ch in quote_close_chars):
                last_quote_idx = idx
        if first_quote_idx is None or last_quote_idx is None or last_quote_idx <= first_quote_idx: return False
        try:
            rel_indices = [line['word_indices'].index(i) for i in match_word_indices]
        except ValueError: return False
        return min(rel_indices) > first_quote_idx and max(rel_indices) < last_quote_idx

    def _is_within_quotes_extended(match_word_indices):
        try:
            if _is_within_quotes(match_word_indices): return True
            wi = match_word_indices[0]
            bno, lno = words_on_page[wi][5], words_on_page[wi][6]
            neighbors = []
            for dl in (-1, 0, 1):
                key = (bno, lno + dl)
                if key in by_line: neighbors.append(' '.join(by_line[key]['words']))
            joined = '\n'.join(neighbors)
            quote_chars = ['"', '“', '”', '‘', '’', "'"]
            total_quotes = sum(joined.count(ch) for ch in quote_chars)
            return total_quotes >= 2 and any(ch in neighbors[0] for ch in quote_chars)
        except Exception: return False

    def _appears_after_closing_quote(match_word_indices):
        if not match_word_indices: return False
        first_match_wi = match_word_indices[0]
        quote_close_chars = {'"', '”', '’', "'", '»', '›'}
        for i in range(first_match_wi - 1, max(0, first_match_wi - 20), -1):
            word_text = words_on_page[i][4]
            if any(ch in word_text for ch in quote_close_chars): return True
            if i == max(0, first_match_wi - 20): break
        return False

    def _has_any_quotes_nearby(match_word_indices):
        try:
            if not match_word_indices: return False
            wi = match_word_indices[0]
            bno, lno = words_on_page[wi][5], words_on_page[wi][6]
            neighbors = []
            for dl in (-1, 0, 1):
                key = (bno, lno + dl)
                if key in by_line: neighbors.append(' '.join(by_line[key]['words']))
            joined = '\n'.join(neighbors)
            quote_chars = ['"', '“', '”', '‘', '’', "'"]
            return any(ch in joined for ch in quote_chars)
        except Exception: return False

    def _fallback_highlight_journal_after_quote(clean_query_tokens):
        try:
            stop_tokens = {'vol', 'volume', 'no', 'issue', 'pages', 'pp', 'doi', 'https', 'http'}
            for wi, w in enumerate(words_on_page):
                t = w[4]
                if any(ch in t for ch in ['"', '”', '’', "'", '»', '›']):
                    cand_indices, cand_tokens = [], []
                    for k in range(1, 6):
                        if wi + k >= len(words_on_page): break
                        nxt, cleaned = words_on_page[wi + k][4], _clean_scimago_title(words_on_page[wi + k][4])
                        if not cleaned: continue
                        if cleaned in stop_tokens: break
                        cand_indices.append(wi + k)
                        cand_tokens.append(cleaned)
                        if len(clean_query_tokens) == 1 and len(cand_tokens) >= 1: break
                    if not cand_tokens: continue
                    if len(clean_query_tokens) == 1:
                        if cand_tokens[0] == clean_query_tokens[0]:
                            rects = [fitz.Rect(words_on_page[idx][:4]) for idx in cand_indices[:1]]
                            return cand_indices[:1], (rects[0] if rects else None)
                    else:
                        qset, cset = set(clean_query_tokens), set(cand_tokens)
                        inter, uni = len(qset & cset), max(1, len(qset | cset))
                        if inter / uni >= 0.6:
                            rects = [fitz.Rect(words_on_page[idx][:4]) for idx in cand_indices]
                            return cand_indices, (rects[0] if rects else None)
        except Exception: return None, None
        return None, None

    # BAGIAN 3: HIGHLIGHT NAMA JURNAL
    for result in detailed_results:
        is_journal_or_indexed = (result.get('reference_type') == 'journal') or result.get('is_indexed')
        if not is_journal_or_indexed: continue
        journal_name = result.get('parsed_journal')
        if not journal_name or len(journal_name) < 2: continue
        search_tokens = _clean_scimago_title(journal_name).split()
        if not search_tokens: continue
        plen = len(search_tokens)
        matched = False
        for i in range(len(expanded_tokens) - max(plen, 1) + 1):
            potential_match_tokens = [t['token'] for t in expanded_tokens[i:i+plen]]
            matched_window_len = None
            if potential_match_tokens == search_tokens: matched_window_len = plen
            elif len(search_tokens) == 1:
                query, combined, tmp_indices = search_tokens[0], "", []
                max_join = min(len(expanded_tokens) - i, max(2, len(query)))
                for k in range(max_join):
                    tok = expanded_tokens[i + k]['token']
                    combined += tok
                    tmp_indices.append(expanded_tokens[i + k]['word_index'])
                    if not query.startswith(combined): break
                    if combined == query:
                        potential_match_tokens, matched_window_len = [combined], k + 1
                        break
            if matched_window_len is not None:
                match_indices = [expanded_tokens[i+k]['word_index'] for k in range(matched_window_len)]
                if any(idx in used_word_indices for idx in match_indices): continue
                
                last_matched_word_index = expanded_tokens[i + matched_window_len - 1]['word_index']
                last_word_of_match_text = words_on_page[last_matched_word_index][4]
                
                ref_num = result.get('reference_number')
                if ref_num and ref_num in markers_by_number:
                    marker_info = markers_by_number[ref_num]
                    marker_y, next_marker_y = marker_info['y'], marker_info.get('next_y')
                    for wi, w in enumerate(words_on_page):
                        word_y = w[1]
                        if word_y >= marker_y - 5:
                            if next_marker_y is None or word_y < next_marker_y - 5:
                                used_word_indices.add(wi)
                
                next_word_text = ""
                if last_matched_word_index + 1 < len(words_on_page):
                    next_word_text = words_on_page[last_matched_word_index + 1][4]
                if next_word_text.lower() in ['in', 'proceedings', 'conference', 'symposium', 'report', 'book']: continue
                if last_word_of_match_text.endswith('.') and next_word_text.lower() == 'in': continue
                if _is_within_quotes(match_indices) or _is_within_quotes_extended(match_indices): continue
                if _has_any_quotes_nearby(match_indices) and not _appears_after_closing_quote(match_indices): continue
                
                used_word_indices.update(match_indices)
                try:
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
                break
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
                    ref_num = result.get('reference_number')
                    if ref_num and ref_num in markers_by_number:
                        marker_info = markers_by_number[ref_num]
                        marker_y, next_marker_y = marker_info['y'], marker_info.get('next_y')
                        for wi, w in enumerate(words_on_page):
                            word_y = w[1]
                            if word_y >= marker_y - 5:
                                if next_marker_y is None or word_y < next_marker_y - 5:
                                    used_word_indices.add(wi)
                    for wi in unique_wi: used_word_indices.add(wi)
                except Exception as e:
                    logger.warning(f"Fallback highlight gagal untuk ref {result['reference_number']}: {e}")

    # BAGIAN 4: HIGHLIGHT TAHUN OUTDATED
    top_level_year = validation_results.get('year_range')
    min_year_threshold = int(top_level_year) if top_level_year else 5
    min_year = datetime.now().year - min_year_threshold
    year_pattern = re.compile(r'\b(19\d{2}|20\d{2})\b')
    y_start_threshold = 0
    if current_page_heading_rects:
        try:
            heading_full = fitz.Rect(current_page_heading_rects[0])
            for r in current_page_heading_rects[1:]: heading_full.include_rect(r)
            y_start_threshold = heading_full.y1 - 2
        except Exception: pass

    def _is_in_reference_region(rect):
        if current_page_heading_rects and y_start_threshold > 0:
            return rect.y0 >= y_start_threshold
        elif not start_annotating: return False
        return True

    def _is_year_in_quotes(word_idx):
        # (Logika _is_year_in_quotes tetap sama, saya singkat untuk kejelasan)
        try:
            quote_open_chars = {'"', '“', 'ô'}
            quote_close_chars = {'"', '”', 'ö'}
            key = (words_on_page[word_idx][5], words_on_page[word_idx][6])
            line = by_line.get(key)
            if not line: return False
            try: rel_idx = line['word_indices'].index(word_idx)
            except ValueError: return False
            def line_open_before(idx, lw): return any(any(c in t for c in quote_open_chars) for t in lw[:idx])
            def line_close_after(idx, lw): return any(any(c in t for c in quote_close_chars) for t in lw[idx+1:])
            cur_txt = str(words_on_page[word_idx][4])
            prev_txt = str(words_on_page[line['word_indices'][rel_idx-1]][4]) if rel_idx > 0 else ''
            next_txt = str(words_on_page[line['word_indices'][rel_idx+1]][4]) if rel_idx + 1 < len(line['word_indices']) else ''
            if '(' in cur_txt or ')' in cur_txt or prev_txt.endswith('(') or next_txt.startswith(')'): return False
            if line_open_before(rel_idx, line['words']) and line_close_after(rel_idx, line['words']): return True
        except Exception: return False
        return False

    def _is_line_a_reference_entry(text_line: str):
        line = text_line.strip()
        if re.match(r'^(\[\d+\]|\(\d+\)|\d+\.)', line): return True
        if re.match(r'^[A-Z][a-zA-Z\-\']{2,},\s+([A-Z]\.\s?)+', line): return True
        return False

    highlighted_years_per_reference = {}
    for wi, w in enumerate(words_on_page):
        word_text = str(w[4])
        for match in year_pattern.finditer(word_text):
            year_str, year_int = match.group(0), int(match.group(0))
            if year_int >= min_year or _is_year_in_quotes(wi): continue
            word_rect = fitz.Rect(w[:4])
            if not _is_in_reference_region(word_rect): continue
            try:
                current_bno, current_lno = w[5], w[6]
                current_key, is_part_of_reference_entry = (current_bno, current_lno), False
                if by_line.get(current_key):
                    if _is_line_a_reference_entry(' '.join(by_line[current_key]['words'])): is_part_of_reference_entry = True
                    else:
                        prev_key = (current_bno, current_lno - 1)
                        if by_line.get(prev_key) and _is_line_a_reference_entry(' '.join(by_line[prev_key]['words'])): is_part_of_reference_entry = True
                if not is_part_of_reference_entry: continue
            except Exception: continue
            try:
                reference_start_line = None
                bno, lno = w[5], w[6]
                for i in range(lno, max(-1, lno - 5), -1):
                    key = (bno, i)
                    if by_line.get(key) and _is_line_a_reference_entry(' '.join(by_line[key]['words'])):
                        reference_start_line = ' '.join(by_line[key]['words'])
                        break
                if not reference_start_line: reference_start_line = f"ref_at_y_{round(w[1], 1)}"
                if reference_start_line not in highlighted_years_per_reference: highlighted_years_per_reference[reference_start_line] = set()
                if year_str in highlighted_years_per_reference[reference_start_line]: continue
                highlighted_years_per_reference[reference_start_line].add(year_str)
            except Exception: continue
            try:
                start_pos, end_pos, word_len = match.start(), match.end(), len(word_text)
                year_rect = word_rect
                if word_len > 0:
                    x_start_ratio, x_end_ratio, word_width = start_pos / word_len, end_pos / word_len, word_rect.x1 - word_rect.x0
                    year_rect = fitz.Rect(word_rect.x0 + (word_width * x_start_ratio), word_rect.y0, word_rect.x0 + (word_width * x_end_ratio), word_rect.y1)
                h = page.add_highlight_annot(year_rect)
                h.set_colors(stroke=YEAR_RGB, fill=YEAR_RGB)
                h.update()
                note_text = f"Tahun: {year_str}\nMinimal: {min_year}\nStatus: Outdated"
                note = page.add_text_annot(fitz.Point(year_rect.x0, max(0, year_rect.y0 - 15)), note_text)
                note.set_info(title="Tahun Outdated")
                note.set_colors(stroke=YEAR_RGB, fill=YEAR_RGB)
                note.update()
            except Exception as e:
                logger.error(f"Error highlighting tahun: {e}")

    return start_annotating, added_references_summary, current_page_heading_rects

def _annotate_single_column_page(
    page,
    page_num,
    detailed_results,
    validation_results,
    start_annotating,
    added_references_summary,
    colors
):
    """
    Memproses dan menganotasi halaman SATU KOLOM dengan logika yang diadopsi 
    penuh dari _annotate_multi_column_page yang sudah sempurna.
    """
    PATTENS_BLUE, INDEXED_RGB, PINK_RGB, YEAR_RGB = colors.values()
    
    words_on_page = page.get_text("words")
    used_word_indices = set()
    current_page_heading_rects = []
    
    # Bangun struktur by_line (sama seperti multi-column)
    by_line = {}
    for wi, w in enumerate(words_on_page):
        if not w[4] or not str(w[4]).strip(): continue
        key = (w[5], w[6])
        if key not in by_line:
            by_line[key] = {'y': w[1], 'x_min': w[0], 'x_max': w[2], 'word_indices': [wi], 'words': [w[4]], 'rects': [fitz.Rect(w[:4])]}
        else:
            by_line[key]['y'] = min(by_line[key]['y'], w[1])
            by_line[key]['x_min'] = min(by_line[key]['x_min'], w[0])
            by_line[key]['x_max'] = max(by_line[key]['x_max'], w[2])
            by_line[key]['word_indices'].append(wi)
            by_line[key]['words'].append(w[4])
            by_line[key]['rects'].append(fitz.Rect(w[:4]))
    lines = sorted(by_line.values(), key=lambda d: d['y'])
    
    lines = sorted(by_line.values(), key=lambda d: d['y'])

    # Helper functions
    def _looks_like_reference_line(text):
        if not text or not isinstance(text, str): 
            return False
        if re.search(r'\(\d{4}\)|\b\d{4}\b', text): 
            return True
        if re.match(r'^(\[\d+\]|\(\d+\)|\d+\.)', text.strip()): 
            return True
        return False

    def _collect_reference_markers(words):
        markers = []
        for wi, w in enumerate(words):
            t = str(w[4]).strip()
            m = None
            for pat in [r'^\[(\d+)\]$', r'^\((\d+)\)$', r'^(\d+)\.$']:
                m = re.match(pat, t)
                if m:
                    try:
                        num = int(m.group(1))
                        markers.append({
                            'num': num, 
                            'y': w[1], 
                            'x': (w[0]+w[2])/2.0, 
                            'wi': wi
                        })
                    except Exception: 
                        pass
                    break
        markers.sort(key=lambda d: d['y'])
        return markers
    
    markers = _collect_reference_markers(words_on_page)
    markers_by_number = {}
    for idx, mk in enumerate(markers):
        mk_next_y = markers[idx + 1]['y'] if idx + 1 < len(markers) else None
        mk['next_y'] = mk_next_y
        markers_by_number[mk['num']] = mk

    # BAGIAN 1: DETEKSI HEADING
    if not start_annotating:
        try:
            heading_tokens = ['daftar pustaka', 'references', 'daftar referensi', 'bibliography', 'pustaka rujukan', 'referensi']
            for li in range(len(lines) - 1, -1, -1):
                line = lines[li]
                line_text = ' '.join(line['words']).strip().lower()
                norm_line = re.sub(r'[^a-z0-9\s]', '', line_text)
                found_ht = False
                for ht in heading_tokens:
                    if norm_line == ht: found_ht = True
                    elif li + 1 < len(lines):
                        next_text = re.sub(r'[^a-z0-9\s]', '', ' '.join(lines[li + 1]['words']).strip().lower())
                        if f"{norm_line} {next_text}".strip() == ht:
                            found_ht = True
                            line['rects'].extend(lines[li + 1]['rects'])
                if found_ht:
                    context = ' '.join([' '.join(lines[j]['words']) for j in range(li + 1, min(len(lines), li + 8))])
                    if _looks_like_reference_line(context):
                        start_annotating = True
                        current_page_heading_rects = line['rects']
                        logger.info(f"🎯 Ditemukan judul Daftar Pustaka di halaman {page_num + 1}, Y={line['y']:.1f}, memulai anotasi.")
                        break
            if not start_annotating:
                return start_annotating, added_references_summary, []
        except Exception:
            return start_annotating, added_references_summary, []

    # BAGIAN 2: SUMMARY NOTE PADA HEADING
    if start_annotating and not added_references_summary and current_page_heading_rects:
        try:
            heading_full = fitz.Rect(current_page_heading_rects[0])
            for r in current_page_heading_rects[1:]: 
                heading_full.include_rect(r)
            
            h = page.add_highlight_annot(heading_full)
            h.set_colors(stroke=PATTENS_BLUE, fill=PATTENS_BLUE)
            h.update()

            total = len(detailed_results)
            journal_count = sum(1 for r in detailed_results if r.get('reference_type') == 'journal')
            sjr_count = sum(1 for r in detailed_results if r.get('is_indexed'))
            year_approved = sum(1 for r in detailed_results if r.get('validation_details', {}).get('year_recent'))
            
            q_counts = {'Q1':0,'Q2':0,'Q3':0,'Q4':0,'Not Found':0}
            for r in detailed_results:
                q = r.get('quartile')
                if q in q_counts: 
                    q_counts[q] += 1
                elif q: 
                    q_counts['Not Found'] += 1

            summary_content = (
                f"Total Referensi: {total}\n"
                f"Artikel Jurnal: {journal_count} ({(journal_count/total*100) if total else 0:.1f}%)\n"
                f"Artikel Non-Jurnal: {total - journal_count} ({((total - journal_count)/total*100) if total else 0:.1f}%)\n"
                f"Terindeks SJR: {sjr_count} ({(sjr_count/total*100) if total else 0:.1f}%)\n"
                f"Validitas Tahun (Recent): {year_approved} dari {total}\n"
                f"Kuartil: Q1:{q_counts['Q1']} | Q2:{q_counts['Q2']} | Q3:{q_counts['Q3']} | Q4:{q_counts['Q4']}"
            )
            
            note = page.add_text_annot(fitz.Point(heading_full.x0, max(0, heading_full.y0 - 15)), summary_content)
            note.set_info(title="Ringkasan Validasi")
            note.set_colors(stroke=PATTENS_BLUE, fill=PATTENS_BLUE)
            note.update()
            added_references_summary = True
        except Exception as e:
            logger.warning(f"Gagal membuat ringkasan heading: {e}")

    # PERSIAPAN TOKEN UNTUK PENCARIAN JURNAL
    expanded_tokens = []
    for wi, w in enumerate(words_on_page):
        cleaned = _clean_scimago_title(w[4])
        if cleaned:
            for part in cleaned.split():
                expanded_tokens.append({
                    'token': part, 
                    'word_index': wi, 
                    'rect': fitz.Rect(w[:4])
                })

    # Helper untuk quote detection
    def _is_within_quotes(match_word_indices):
        if not match_word_indices: 
            return False
        first_wi = match_word_indices[0]
        if first_wi < 0 or first_wi >= len(words_on_page): 
            return False
        
        key = (words_on_page[first_wi][5], words_on_page[first_wi][6])
        line = by_line.get(key)
        if not line: 
            return False
        
        texts = line['words']
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
        
        try:
            rel_indices = [line['word_indices'].index(i) for i in match_word_indices]
        except ValueError: 
            return False
        
        return min(rel_indices) > first_quote_idx and max(rel_indices) < last_quote_idx

    def _is_within_quotes_extended(match_word_indices):
        try:
            if _is_within_quotes(match_word_indices): 
                return True
            wi = match_word_indices[0]
            bno, lno = words_on_page[wi][5], words_on_page[wi][6]
            neighbors = []
            for dl in (-1, 0, 1):
                key = (bno, lno + dl)
                if key in by_line: 
                    neighbors.append(' '.join(by_line[key]['words']))
            joined = '\n'.join(neighbors)
            quote_chars = ['"', '"', '"', ''', ''', "'"]
            total_quotes = sum(joined.count(ch) for ch in quote_chars)
            return total_quotes >= 2 and any(ch in neighbors[0] for ch in quote_chars)
        except Exception: 
            return False

    def _appears_after_closing_quote(match_word_indices):
        if not match_word_indices: 
            return False
        first_match_wi = match_word_indices[0]
        quote_close_chars = {'"', '”', '’', "'", '»', '›'}
        for i in range(first_match_wi - 1, max(0, first_match_wi - 20), -1):
            word_text = words_on_page[i][4]
            if any(ch in word_text for ch in quote_close_chars): 
                return True
            if i == max(0, first_match_wi - 20): 
                break
        return False

    def _has_any_quotes_nearby(match_word_indices):
        try:
            if not match_word_indices: 
                return False
            wi = match_word_indices[0]
            bno, lno = words_on_page[wi][5], words_on_page[wi][6]
            neighbors = []
            for dl in (-1, 0, 1):
                key = (bno, lno + dl)
                if key in by_line: 
                    neighbors.append(' '.join(by_line[key]['words']))
            joined = '\n'.join(neighbors)
            quote_chars = ['"', '"', '"', ''', ''', "'"]
            return any(ch in joined for ch in quote_chars)
        except Exception: 
            return False

    def _fallback_highlight_journal_after_quote(clean_query_tokens):
        try:
            stop_tokens = {'vol', 'volume', 'no', 'issue', 'pages', 'pp', 'doi', 'https', 'http'}
            for wi, w in enumerate(words_on_page):
                t = w[4]
                if any(ch in t for ch in ['"', '”', '’', "'", '»', '›']):
                    cand_indices, cand_tokens = [], []
                    for k in range(1, 6):
                        if wi + k >= len(words_on_page): 
                            break
                        nxt = words_on_page[wi + k][4]
                        cleaned = _clean_scimago_title(nxt)
                        if not cleaned: 
                            continue
                        if cleaned in stop_tokens: 
                            break
                        cand_indices.append(wi + k)
                        cand_tokens.append(cleaned)
                        if len(clean_query_tokens) == 1 and len(cand_tokens) >= 1: 
                            break
                    
                    if not cand_tokens: 
                        continue
                    
                    if len(clean_query_tokens) == 1:
                        if cand_tokens[0] == clean_query_tokens[0]:
                            rects = [fitz.Rect(words_on_page[idx][:4]) for idx in cand_indices[:1]]
                            return cand_indices[:1], (rects[0] if rects else None)
                    else:
                        qset, cset = set(clean_query_tokens), set(cand_tokens)
                        inter, uni = len(qset & cset), max(1, len(qset | cset))
                        if inter / uni >= 0.6:
                            rects = [fitz.Rect(words_on_page[idx][:4]) for idx in cand_indices]
                            return cand_indices, (rects[0] if rects else None)
        except Exception: 
            return None, None
        return None, None

    # BAGIAN 3: HIGHLIGHT NAMA JURNAL (sama seperti multi-column)
    for result in detailed_results:
        is_journal_or_indexed = (result.get('reference_type') == 'journal') or result.get('is_indexed')
        if not is_journal_or_indexed: continue
        journal_name = result.get('parsed_journal')
        if not journal_name or len(journal_name) < 2: continue
        search_tokens = _clean_scimago_title(journal_name).split()
        if not search_tokens: continue
        plen = len(search_tokens)
        matched = False
        for i in range(len(expanded_tokens) - max(plen, 1) + 1):
            potential_match_tokens = [t['token'] for t in expanded_tokens[i:i+plen]]
            matched_window_len = None
            if potential_match_tokens == search_tokens: matched_window_len = plen
            elif len(search_tokens) == 1:
                query, combined, tmp_indices = search_tokens[0], "", []
                max_join = min(len(expanded_tokens) - i, max(2, len(query)))
                for k in range(max_join):
                    tok = expanded_tokens[i + k]['token']
                    combined += tok
                    tmp_indices.append(expanded_tokens[i + k]['word_index'])
                    if not query.startswith(combined): break
                    if combined == query:
                        potential_match_tokens, matched_window_len = [combined], k + 1
                        break
            if matched_window_len is not None:
                match_indices = [expanded_tokens[i+k]['word_index'] for k in range(matched_window_len)]
                if any(idx in used_word_indices for idx in match_indices): continue
                
                last_matched_word_index = expanded_tokens[i + matched_window_len - 1]['word_index']
                last_word_of_match_text = words_on_page[last_matched_word_index][4]
                
                ref_num = result.get('reference_number')
                if ref_num and ref_num in markers_by_number:
                    marker_info = markers_by_number[ref_num]
                    marker_y, next_marker_y = marker_info['y'], marker_info.get('next_y')
                    for wi, w in enumerate(words_on_page):
                        word_y = w[1]
                        if word_y >= marker_y - 5:
                            if next_marker_y is None or word_y < next_marker_y - 5:
                                used_word_indices.add(wi)
                
                next_word_text = ""
                if last_matched_word_index + 1 < len(words_on_page):
                    next_word_text = words_on_page[last_matched_word_index + 1][4]
                if next_word_text.lower() in ['in', 'proceedings', 'conference', 'symposium', 'report', 'book']: continue
                if last_word_of_match_text.endswith('.') and next_word_text.lower() == 'in': continue
                if _is_within_quotes(match_indices) or _is_within_quotes_extended(match_indices): continue
                if _has_any_quotes_nearby(match_indices) and not _appears_after_closing_quote(match_indices): continue
                
                used_word_indices.update(match_indices)
                try:
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
                break
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
                    ref_num = result.get('reference_number')
                    if ref_num and ref_num in markers_by_number:
                        marker_info = markers_by_number[ref_num]
                        marker_y, next_marker_y = marker_info['y'], marker_info.get('next_y')
                        for wi, w in enumerate(words_on_page):
                            word_y = w[1]
                            if word_y >= marker_y - 5:
                                if next_marker_y is None or word_y < next_marker_y - 5:
                                    used_word_indices.add(wi)
                    for wi in unique_wi: used_word_indices.add(wi)
                except Exception as e:
                    logger.warning(f"Fallback highlight gagal untuk ref {result['reference_number']}: {e}")

    # BAGIAN 4: HIGHLIGHT TAHUN OUTDATED
    top_level_year = validation_results.get('year_range')
    min_year_threshold = int(top_level_year) if top_level_year else 5
    min_year = datetime.now().year - min_year_threshold
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
            return rect.y0 >= y_start_threshold
        elif not start_annotating: 
            return False
        return True

    def _is_year_in_quotes(word_idx):
        try:
            quote_open_chars = {'"', '“', 'ô'}
            quote_close_chars = {'"', '”', 'ö'}
            key = (words_on_page[word_idx][5], words_on_page[word_idx][6])
            line = by_line.get(key)
            if not line: 
                return False
            
            try: 
                rel_idx = line['word_indices'].index(word_idx)
            except ValueError: 
                return False
            
            def line_open_before(idx, lw): 
                return any(any(c in t for c in quote_open_chars) for t in lw[:idx])
            def line_close_after(idx, lw): 
                return any(any(c in t for c in quote_close_chars) for t in lw[idx+1:])
            
            cur_txt = str(words_on_page[word_idx][4])
            prev_txt = str(words_on_page[line['word_indices'][rel_idx-1]][4]) if rel_idx > 0 else ''
            next_txt = str(words_on_page[line['word_indices'][rel_idx+1]][4]) if rel_idx + 1 < len(line['word_indices']) else ''
            
            if '(' in cur_txt or ')' in cur_txt or prev_txt.endswith('(') or next_txt.startswith(')'): 
                return False
            if line_open_before(rel_idx, line['words']) and line_close_after(rel_idx, line['words']): 
                return True
        except Exception: 
            return False
        return False

    def _is_line_a_reference_entry(text_line: str):
        line = text_line.strip()
        if re.match(r'^(\[\d+\]|\(\d+\)|\d+\.)', line): 
            return True
        if re.match(r'^[A-Z][a-zA-Z\-\']{2,},\s+([A-Z]\.\s?)+', line): 
            return True
        return False

    highlighted_years_per_reference = {}
    for wi, w in enumerate(words_on_page):
        word_text = str(w[4])
        for match in year_pattern.finditer(word_text):
            year_str, year_int = match.group(0), int(match.group(0))
            if year_int >= min_year or _is_year_in_quotes(wi): 
                continue
            
            word_rect = fitz.Rect(w[:4])
            if not _is_in_reference_region(word_rect): 
                continue
            
            try:
                current_bno, current_lno = w[5], w[6]
                current_key = (current_bno, current_lno)
                is_part_of_reference_entry = False
                
                if by_line.get(current_key):
                    if _is_line_a_reference_entry(' '.join(by_line[current_key]['words'])): 
                        is_part_of_reference_entry = True
                    else:
                        prev_key = (current_bno, current_lno - 1)
                        if by_line.get(prev_key) and _is_line_a_reference_entry(' '.join(by_line[prev_key]['words'])): 
                            is_part_of_reference_entry = True
                
                if not is_part_of_reference_entry: 
                    continue
            except Exception: 
                continue
            
            try:
                reference_start_line = None
                bno, lno = w[5], w[6]
                for i in range(lno, max(-1, lno - 5), -1):
                    key = (bno, i)
                    if by_line.get(key) and _is_line_a_reference_entry(' '.join(by_line[key]['words'])):
                        reference_start_line = ' '.join(by_line[key]['words'])
                        break
                
                if not reference_start_line: 
                    reference_start_line = f"ref_at_y_{round(w[1], 1)}"
                
                if reference_start_line not in highlighted_years_per_reference: 
                    highlighted_years_per_reference[reference_start_line] = set()
                
                if year_str in highlighted_years_per_reference[reference_start_line]: 
                    continue
                
                highlighted_years_per_reference[reference_start_line].add(year_str)
            except Exception: 
                continue
            
            try:
                start_pos, end_pos, word_len = match.start(), match.end(), len(word_text)
                year_rect = word_rect
                
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
                
                h = page.add_highlight_annot(year_rect)
                h.set_colors(stroke=YEAR_RGB, fill=YEAR_RGB)
                h.update()
                
                note_text = f"Tahun: {year_str}\nMinimal: {min_year}\nStatus: Outdated"
                note = page.add_text_annot(fitz.Point(year_rect.x0, max(0, year_rect.y0 - 15)), note_text)
                note.set_info(title="Tahun Outdated")
                note.set_colors(stroke=YEAR_RGB, fill=YEAR_RGB)
                note.update()
            except Exception as e:
                logger.error(f"Error highlighting tahun: {e}")

    return start_annotating, added_references_summary, current_page_heading_rects


def create_annotated_pdf_from_file(original_filepath, validation_results):
    """
    Mengonversi dan menganotasi file PDF dengan deteksi layout otomatis
    untuk memanggil handler anotasi yang sesuai (satu kolom atau multi-kolom).
    """
    try:
        pdf = fitz.open(original_filepath)
        detailed_results = validation_results.get('detailed_results', [])
        
        colors = {
            "PATTENS_BLUE": (210/255.0, 236/255.0, 238/255.0),
            "INDEXED_RGB": (208/255.0, 233/255.0, 222/255.0),
            "PINK_RGB": (251/255.0, 215/255.0, 222/255.0),
            "YEAR_RGB": (255/255.0, 105/255.0, 97/255.0)
        }

        start_annotating = False
        added_references_summary = False

        for page_num, page in enumerate(pdf):
            # --- INI DIA BAGIAN DISPATCHER-NYA ---
            layout_type = _detect_layout(page)

            handler_function = None
            if layout_type == 'multi_column':
                # Panggil fungsi yang sudah sempurna untuk dua kolom
                handler_function = _annotate_multi_column_page
            else: # 'single_column'
                # Panggil fungsi BARU yang dirancang untuk satu kolom
                handler_function = _annotate_single_column_page

            # Panggil handler yang terpilih
            new_start_annotating, new_added_summary, _ = handler_function(
                page=page,
                page_num=page_num,
                detailed_results=detailed_results,
                validation_results=validation_results,
                start_annotating=start_annotating,
                added_references_summary=added_references_summary,
                colors=colors
            )
            
            # Perbarui state global dari hasil pemrosesan halaman
            start_annotating = new_start_annotating
            added_references_summary = new_added_summary

        # Finalisasi PDF
        pdf_bytes = pdf.tobytes()
        pdf.close()
        return pdf_bytes, None

    except Exception as e:
        logger.error(f"Error fatal di create_annotated_pdf: {e}", exc_info=True)
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