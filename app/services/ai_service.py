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
Diberikan blok teks daftar pustaka berikut, pisahkan menjadi entri-entri referensi individual.
Pastikan setiap entri adalah referensi yang lengkap.
Kembalikan hasilnya sebagai sebuah array JSON dari string.
Contoh output: ["Referensi lengkap pertama...", "Referensi lengkap kedua...", "Referensi lengkap ketiga..."]

Teks untuk dipisahkan:
---
{references_block}
---
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
    """
    Menganalisis list referensi menggunakan AI untuk validasi format,
    kelengkapan, dan ekstraksi metadata.
    
    Args:
        references_list (list): List of reference strings
        style (str): Citation style (APA, IEEE, MLA, etc.)
        year_range (int): Minimum year threshold
        
    Returns:
        tuple: (batch_results: list, error: str or None)
    """
    try:
        model = get_generative_model()
        year_threshold = datetime.now().year - year_range
        
        prompt = _construct_batch_gemini_prompt(references_list, style, year_threshold)
        
        logger.info(f"Memulai analisis BATCH untuk {len(references_list)} referensi (Gaya: {style}).")
        analysis_response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1}
        )
        
        analysis_json_match = re.search(r'\[.*\]', analysis_response.text, re.DOTALL)
        if not analysis_json_match:
            logger.error(f"AI gagal menganalisis referensi. Respons mentah: {analysis_response.text}")
            return None, "AI gagal menganalisis referensi ke dalam format JSON array."
        
        batch_results_json = json.loads(analysis_json_match.group(0))
        return batch_results_json, None
        
    except Exception as e:
        logger.error(f"Error saat analisis AI: {e}", exc_info=True)
        return None, f"Gagal menganalisis referensi: {e}"


def _construct_batch_gemini_prompt(references_list, style, year_threshold):
    formatted_references = "\n".join([
        f"{i+1}. {ref}" for i, ref in enumerate(references_list)
    ])

    style_examples = {
        "APA": "Contoh APA: Smith, J. (2023). Judul artikel. Nama Jurnal, 10(2), 1-10.",
        "Harvard": "Contoh Harvard: Smith, J. (2023) 'Judul artikel', Nama Jurnal, 10(2), pp. 1-10.",
        "IEEE": "Contoh IEEE: [1] J. Smith, \"Judul artikel,\" Nama Jurnal, vol. 10, no. 2, pp. 1-10, Jan. 2023.",
        "MLA": "Contoh MLA: Smith, John. \"Judul Artikel.\" Nama Jurnal, vol. 10, no. 2, 2023, pp. 1-10.",
        "Chicago": "Contoh Chicago: Smith, John. 2023. \"Judul Artikel.\" Nama Jurnal 10 (2): 1-10."
    }
    
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
   - Jika ada kekurangan → jelaskan ringkas tanpa menyebut "INVALID", cukup "perlu ditambahkan...".

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
- `parsed_journal` harus HANYA nama jurnal/sumber, misalnya "Nature", "PLOS ONE", "Journal of Machine Learning Research"
- JANGAN sertakan volume, issue, halaman, atau DOI dalam `parsed_journal`
- Contoh BENAR: "parsed_journal": "International Journal of Electronic Commerce"
- Contoh SALAH: "parsed_journal": "International Journal of Electronic Commerce, Vol. 2(8), 8-22."
"""
