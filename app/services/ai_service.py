import logging
import json
import re
from datetime import datetime
import google.generativeai as genai
from config import Config

logger = logging.getLogger(__name__)

# Cache model agar tidak perlu re-initialize
_MODEL_CACHE = None


def get_generative_model():
    global _MODEL_CACHE
    if _MODEL_CACHE:
        return _MODEL_CACHE
    
    try:
        genai.configure(api_key=Config.GEMINI_API_KEY, transport='rest')
        available_models = [
            m.name for m in genai.list_models() 
            if 'generateContent' in m.supported_generation_methods
        ]
        
        preferred_models = [
            'models/gemini-flash-latest',
            'models/gemini-pro',
            'models/gemini-pro-latest'
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


def split_references_with_ai(references_block):
    try:
        model = get_generative_model()
        
        splitter_prompt = f"""
            Anda adalah AI ahli parsing daftar pustaka.

            TUGAS:
            Pisahkan blok teks daftar pustaka berikut menjadi entri-entri referensi individual.

            ATURAN:
            1. Satu referensi = satu elemen array, meskipun referensi itu multi-line
            2. Jaga semua teks asli (jangan ubah/edit)
            3. Nomor urut (1., 2., [1], dll) adalah penanda awal referensi baru
            4. Referensi minimal harus ada: Penulis + Tahun + Judul

            EDGE CASES:
            - Referensi dengan DOI/URL panjang → tetap satu referensi
            - Referensi multi-line → gabungkan menjadi satu string
            - Referensi tanpa nomor → pisahkan dengan indent atau line break

            CONTOH INPUT:
            1. Smith, J. (2023). Title here. Journal, 10(2), 1-10.
            2. Brown, A. (2022). Long title spanning
            multiple lines here. Another Journal, 5, 100-120.

            CONTOH OUTPUT:
            ["Smith, J. (2023). Title here. Journal, 10(2), 1-10.", "Brown, A. (2022). Long title spanning multiple lines here. Another Journal, 5, 100-120."]

            Teks untuk dipisahkan:
            ---
            {references_block}
            ---

            OUTPUT: Array JSON dari string.
        """
        
        logger.info("Meminta AI untuk memisahkan referensi dari blok teks...")
        response = model.generate_content(splitter_prompt)
        
        # Ekstraksi JSON yang lebih tangguh
        json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if not json_match:
            logger.error(f"AI gagal memisahkan referensi. Respons mentah: {response.text}")
            return None, "AI gagal memisahkan referensi ke dalam format JSON array."
        
        references_list = json.loads(json_match.group(0))
        logger.info(f"AI berhasil memisahkan menjadi {len(references_list)} referensi.")
        
        if not references_list:
            return None, "Tidak ada referensi individual yang dapat diidentifikasi oleh AI."
        
        return references_list, None
        
    except Exception as e:
        logger.error(f"Error saat split references dengan AI: {e}", exc_info=True)
        return None, f"Gagal memisahkan referensi: {e}"


def analyze_references_with_ai(references_list, style, year_range):
    try:
        model = get_generative_model()
        current_year = datetime.now().year
        year_threshold = current_year - year_range
        
        # Jika style adalah "Auto", minta AI untuk mendeteksi gaya sitasi
        detected_style = style
        if style.lower() == 'auto':
            logger.info("Mode Auto-Detect: Meminta AI untuk mendeteksi gaya sitasi...")
            detected_style = _detect_citation_style(references_list, model)
            logger.info(f"✅ AI mendeteksi gaya sitasi: {detected_style}")
        
        prompt = _construct_batch_gemini_prompt(references_list, detected_style, current_year, year_threshold, year_range)
        
        logger.info(f"Memulai analisis BATCH untuk {len(references_list)} referensi (Gaya: {detected_style}).")
        analysis_response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1}
        )
        
        analysis_json_match = re.search(r'\[.*\]', analysis_response.text, re.DOTALL)
        if not analysis_json_match:
            logger.error(f"AI gagal menganalisis referensi. Respons mentah: {analysis_response.text}")
            return None, detected_style, "AI gagal menganalisis referensi ke dalam format JSON array."
        
        batch_results_json = json.loads(analysis_json_match.group(0))
        return batch_results_json, detected_style, None
        
    except Exception as e:
        logger.error(f"Error saat analisis AI: {e}", exc_info=True)
        return None, style, f"Gagal menganalisis referensi: {e}"


def _detect_citation_style(references_list, model):
    try:
        # Ambil max 5 referensi pertama sebagai sample
        sample_references = references_list[:min(5, len(references_list))]
        formatted_sample = "\n".join([f"{i+1}. {ref}" for i, ref in enumerate(sample_references)])
        
        detection_prompt = f"""
            Anda adalah AI ahli analisis gaya sitasi (citation style).

            Analisis 5 referensi berikut dan tentukan gaya sitasi yang PALING DOMINAN digunakan.

            REFERENSI SAMPLE:
            ---
            {formatted_sample}
            ---

            GAYA SITASI YANG UMUM:
            1. **APA (American Psychological Association)**
            - Format: Author, A. A. (Year). Title of article. Journal Name, volume(issue), pages.
            - Ciri khas: Tahun dalam kurung setelah nama, judul artikel tidak dikutip

            2. **IEEE**
            - Format: [1] A. Author, "Title of article," Journal Name, vol. X, no. Y, pp. Z-Z, Month Year.
            - Ciri khas: Nomor referensi [1], judul dalam quotes, vol./no./pp.

            3. **MLA (Modern Language Association)**
            - Format: Author, First. "Title of Article." Journal Name, vol. X, no. Y, Year, pp. Z-Z.
            - Ciri khas: Tahun di belakang, judul dalam quotes, tanpa issue kadang

            4. **Harvard**
            - Format: Author, A. (Year) 'Title of article', Journal Name, volume(issue), pp. Z-Z.
            - Ciri khas: Mirip APA tapi judul pakai single quote, pp. untuk halaman

            5. **Chicago**
            - Format: Author, First. Year. "Title of Article." Journal Name volume (issue): pages.
            - Ciri khas: Tahun setelah nama tanpa kurung, colon sebelum pages

            INSTRUKSI:
            1. Periksa pola penulisan: posisi tahun, format nama penulis, penggunaan quotes/italic
            2. Identifikasi ciri khas dari setiap gaya
            3. Tentukan gaya yang PALING BANYAK digunakan
            4. Jika ada campuran gaya atau tidak jelas, pilih "Mixed"

            OUTPUT:
            Kembalikan HANYA SATU KATA dari pilihan berikut (tanpa penjelasan tambahan):
            APA, IEEE, MLA, Harvard, Chicago, atau Mixed

            JAWABAN:
        """
        
        logger.info("🔍 Mendeteksi gaya sitasi dari sample referensi...")
        response = model.generate_content(
            detection_prompt,
            generation_config={"temperature": 0.1}
        )
        
        detected = response.text.strip().upper()
        
        # Validasi output
        valid_styles = ['APA', 'IEEE', 'MLA', 'HARVARD', 'CHICAGO', 'MIXED']
        
        # Extract style name dari response (case insensitive)
        for style in valid_styles:
            if style in detected:
                return style.title() if style != 'IEEE' else 'IEEE'
        
        # Fallback ke APA jika deteksi gagal
        logger.warning(f"⚠️ AI mengembalikan style tidak valid: '{detected}', fallback ke APA")
        return "APA"
        
    except Exception as e:
        logger.error(f"Error saat deteksi citation style: {e}", exc_info=True)
        # Fallback ke APA
        return "APA"


def _construct_batch_gemini_prompt(references_list, style, year, year_threshold, year_range):
    formatted_references = "\n".join([
        f"{i+1}. {ref}" for i, ref in enumerate(references_list)
    ])

    style_examples = {
        "APA": "Contoh APA: Smith, J. (2023). Judul artikel. Nama Jurnal, 10(2), 1-10.",
        "Harvard": "Contoh Harvard: Smith, J. (2023) 'Judul artikel', Nama Jurnal, 10(2), pp. 1-10.",
        "IEEE": "Contoh IEEE: [1] J. Smith, \"Judul artikel,\" Nama Jurnal, vol. 10, no. 2, pp. 1-10, Jan. 2023.",
        "MLA": "Contoh MLA: Smith, John. \"Judul Artikel.\" Nama Jurnal, vol. 10, no. 2, 2023, pp. 1-10.",
        "Chicago": "Contoh Chicago: Smith, John. 2023. \"Judul Artikel.\" Nama Jurnal 10 (2): 1-10.",
        "Mixed": "Gaya campuran terdeteksi - Validasi berdasarkan struktur umum (penulis, tahun, judul, sumber)."
    }
    
    # Tentukan instruksi format berdasarkan style
    if style.upper() == "MIXED":
        style_instruction = """
            **GAYA SITASI: MIXED (Campuran)**
            Karena referensi menggunakan gaya campuran, validasi berdasarkan STRUKTUR UMUM:
            - `is_format_correct` = true jika memiliki urutan logis: Penulis → Tahun → Judul → Sumber
            - TIDAK perlu mengikuti format strict dari satu gaya tertentu
            - Fokus pada kelengkapan elemen, bukan konsistensi format
        """
    else:
        style_instruction = f"""
            Analisis setiap referensi berdasarkan gaya sitasi: **{style}**.
            {style_examples.get(style, '')}
            - `is_format_correct` hanya mengecek URUTAN UTAMA (penulis → tahun → judul).
            - Variasi kecil gaya tanda baca / italic / huruf besar TIDAK mempengaruhi.
        """
    
    return f"""
        Anda adalah AI ahli analisis daftar pustaka. Jawab SEMUA feedback dalam BAHASA INDONESIA.
        {style_instruction}

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
        7. **Feedback (Gunakan Template):**
        - Jika SEMPURNA → "VALID"
        - Jika kurang elemen → "Perlu ditambahkan: [elemen]. Contoh: Perlu ditambahkan: volume dan halaman."
        - Jika format salah → "Format kurang sesuai {style}. Seharusnya: [contoh format yang benar]"
        - Jika tahun lama → "Tahun publikasi ({year}) lebih dari {year_range} tahun. Pertimbangkan referensi lebih baru."
        - JANGAN gunakan kata "INVALID" atau "TIDAK VALID"

        DAFTAR REFERENSI:
        ---
        {formatted_references}
        ---

        INSTRUKSI OUTPUT:
        Kembalikan sebagai ARRAY JSON TUNGGAL dengan struktur berikut:
        {{
            "reference_number": <int>,
            "full_reference": "<TEKS REFERENSI LENGKAP SEPERTI YANG DIBERIKAN>",
            "parsed_authors": ["Penulis 1"],
            "parsed_year": <int>,
            "parsed_title": "<string>",
            "parsed_journal": "<HANYA NAMA JURNAL/SUMBER, TANPA volume/issue/halaman>",
            "reference_type": "journal/book/conference/website/other",
            "is_format_correct": <boolean>,
            "is_complete": <boolean>,
            "is_year_recent": <boolean>,
            "is_scientific_source": <boolean>,
            "missing_elements": ["elemen_hilang"],
            "feedback": "<Saran perbaikan dalam BAHASA INDONESIA, atau 'OK' jika sempurna>"
        }}

        PENTING: 
        - `full_reference` harus berisi TEKS REFERENSI ASLI LENGKAP persis seperti yang diberikan (untuk keperluan highlighting di PDF)
        - `parsed_journal` harus HANYA nama jurnal/sumber, misalnya "Nature", "PLOS ONE", "Journal of Machine Learning Research"
        - JANGAN sertakan volume, issue, halaman, atau DOI dalam `parsed_journal`
        - Contoh BENAR: "parsed_journal": "International Journal of Electronic Commerce"
        - Contoh SALAH: "parsed_journal": "International Journal of Electronic Commerce, Vol. 2(8), 8-22."
    """
