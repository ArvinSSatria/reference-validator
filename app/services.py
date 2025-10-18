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
        
        REFERENCE_HEADINGS = ["daftar pustaka", "referensi", "bibliography", "references", "pustaka rujukan"]
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
    from datetime import datetime
    year_threshold = datetime.now().year - year_range
    formatted_references = "\n".join([f"{i+1}. {ref}" for i, ref in enumerate(references_list)])

    return f"""
    Anda adalah sistem AI ahli dalam validasi dan klasifikasi referensi ilmiah lintas gaya sitasi.
    Analisis DAFTAR REFERENSI berikut dan kembalikan hasil sebagai SEBUAH ARRAY JSON TUNGGAL yang valid.

    ATURAN VALIDASI:

    1. FORMAT: Sesuaikan dengan gaya sitasi '{style}'. Kenali perbedaan ciri khas 5 gaya utama berikut:
       - **APA (American Psychological Association)**
         • Ciri Khas: Nama, I. I., & Nama, I. I. (Tahun). Judul artikel. *Nama Jurnal*, *volume*(issue), halaman. Menggunakan '&' dan tanda kurung pada tahun. Judul jurnal dan volume dicetak miring.
       - **IEEE (Institute of Electrical and Electronics Engineers)**
         • Ciri Khas: [1] I. I. Nama, "Judul artikel," *Nama Jurnal*, vol. #, no. #, pp. #-#, Bulan. Tahun. Menggunakan nomor urut, judul dalam kutip ganda, dan tahun di akhir.
       - **MLA (Modern Language Association)**
         • Ciri Khas: Nama, Nama Depan. "Judul Artikel." *Nama Jurnal*, Volume, Nomor, Tahun, pp. #-#. Menggunakan kutip ganda pada judul, nama depan penulis ditulis penuh, dan tahun tanpa tanda kurung.
       - **Chicago (Author-Date)**
         • Ciri Khas: Nama, Nama Depan. Tahun. "Judul Artikel." *Nama Jurnal* volume, no. issue: halaman. Tahun langsung setelah nama penulis, judul dalam kutip ganda.
       - **Harvard**
         • Ciri Khas: Nama, I. I. and Nama, I. I. (Tahun) 'Judul Artikel', *Nama Jurnal*, volume(issue), pp. #-#. Sangat mirip APA, tetapi menggunakan 'and' (bukan '&') dan judul artikel dalam tanda kutip tunggal.

       Pastikan `is_format_correct` = true hanya jika struktur referensi SANGAT SESUAI dengan ciri khas gaya '{style}' yang diminta.

    2. KELENGKAPAN: Harus memuat elemen wajib berdasarkan jenis sumber:
       - Untuk 'journal': Penulis, Tahun, Judul Artikel, Nama Jurnal, Volume, Nomor Isu (jika ada), dan Rentang Halaman.
       - Untuk 'book': Penulis/Editor, Tahun, Judul Buku, Penerbit.
       - Untuk 'conference': Penulis, Tahun, Judul Paper, Nama Konferensi.
       Beri `false` pada `is_complete` dan tambahkan elemen yang hilang ke `missing_elements`.

    3. TAHUN TERBIT:
       - Untuk 'journal' dan 'conference': Dianggap terkini jika >= {year_threshold} ({year_range} tahun terakhir).
       - Untuk 'book': Aturan tahun lebih longgar; buku teks klasik atau edisi terbaru boleh `is_year_recent = true`.

    4. JENIS SUMBER: Identifikasi sumber sebagai 'journal', 'book', 'conference', 'website', atau 'other'. Gunakan hasil ini untuk `reference_type`.
       - `is_scientific_source` harus `true` untuk Jurnal peer-reviewed, Buku akademik, Prosiding konferensi, dan Website dari lembaga resmi (pemerintah, universitas, organisasi internasional).
       - `is_scientific_source` harus `false` untuk Blog pribadi, Wikipedia, media sosial, atau situs komersial tidak kredibel.

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
        "parsed_journal": "<string nama jurnal, seri buku, atau penerbit>" atau null,
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
    
    # --- DAFTAR TIPE YANG DIANGGAP VALID DARI SCIMAGO ---
    ACCEPTED_SCIMAGO_TYPES = {'journal', 'book series', 'trade journal', 'conference and proceeding'}

    for result_json in batch_results_json:
        # (Parsing data dasar)        
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
        
        # --- LOGIKA PENCOCOKAN SCIMAGO BARU YANG BERTINGKAT ---
        if journal_name and SCIMAGO_DATA["by_cleaned_title"]:
            cleaned_journal_name = _clean_scimago_title(journal_name)
            
            # Strategi 1: Pencocokan persis (paling akurat)
            if cleaned_journal_name in SCIMAGO_DATA["by_cleaned_title"]:
                is_indexed = True
                journal_info = SCIMAGO_DATA["by_cleaned_title"][cleaned_journal_name]
                
            # Strategi 2: Jika gagal, coba pencocokan "semua kata ada" dengan cek rasio
            else:
                journal_words = set(cleaned_journal_name.split())
                if len(journal_words) > 1:
                    best_match_info = None
                    highest_ratio = 0.8 # Harus minimal 80% mirip panjangnya

                    for cleaned_title_db, info in SCIMAGO_DATA["by_cleaned_title"].items():
                        db_title_words = set(cleaned_title_db.split())
                        if journal_words.issubset(db_title_words):
                            # Hitung rasio kemiripan panjang kata
                            ratio = len(journal_words) / len(db_title_words)
                            if ratio > highest_ratio:
                                highest_ratio = ratio
                                best_match_info = info
                    
                    if best_match_info:
                        is_indexed = True
                        journal_info = best_match_info

            # Jika berhasil ditemukan (dengan strategi apa pun)
            if is_indexed:
                scimago_link = f"https://www.scimagojr.com/journalsearch.php?q={journal_info['id']}&tip=sid"
                quartile = journal_info['quartile']
                ref_type = journal_info['type'] # Override tipe dari Scimago
        
        # Logika validitas keseluruhan
        ai_assessment_valid = all([
            result_json.get('is_format_correct', False),
            result_json.get('is_complete', False),
            result_json.get('is_year_recent', False),
        ])
        
        is_overall_valid = False
        final_feedback = result_json.get('feedback', 'Analisis AI selesai.')
        
        if is_indexed and ref_type in ACCEPTED_SCIMAGO_TYPES:
            # Jika terindeks DAN tipenya diterima (journal, book series, dll)
            if ai_assessment_valid:
                is_overall_valid = True
                final_feedback += f" Status: VALID (Sumber tipe '{ref_type}' terindeks di ScimagoJR dan memenuhi kriteria kualitas)."
            else:
                final_feedback += f" Status: INVALID (Meskipun sumber terindeks, format/kelengkapan/tahun tidak memenuhi syarat.)"
        elif is_indexed:
            # Jika terindeks tapi tipenya TIDAK diterima (misal 'other')
            final_feedback += f" Status: INVALID (Sumber ditemukan di ScimagoJR, namun tipenya ('{ref_type}') tidak umum digunakan sebagai referensi utama)."
        else:
            # Jika tidak terindeks sama sekali
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
        "count_validation": count_validation, "distribution_analysis": distribution, "style_used": style
    }
    recommendations = []
    if summary['validation_rate'] < 70: recommendations.append("⚠️ Tingkat validitas rendah. Banyak referensi perlu perbaikan format atau kelengkapan.")
    if not meets_journal_req: recommendations.append(f"📊 Proporsi jurnal ({journal_percentage:.1f}%) belum memenuhi syarat minimal yang Anda tentukan ({journal_percent_threshold}%).")
    if not count_validation['is_count_appropriate']: recommendations.append(f"📝 {count_validation['count_message']}")
    if not recommendations: recommendations.append("✅ Referensi sudah memenuhi standar kualitas umum. Siap untuk tahap selanjutnya.")
    return summary, recommendations

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

        return {
            "success": True,
            "summary": summary,
            "detailed_results": detailed_results,
            "recommendations": recommendations
        }

    except Exception as e:
        logger.error(f"Error kritis saat pemrosesan AI: {e}", exc_info=True)
        return {"error": f"Terjadi kesalahan saat pemrosesan AI. Detail: {e}"}