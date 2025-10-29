import logging
import re
import fitz  # PyMuPDF
from datetime import datetime
from app.utils.text_utils import is_likely_reference

logger = logging.getLogger(__name__)


def extract_references_from_pdf(file_stream):
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
                ref_like = sum(1 for p in window if is_likely_reference(p))
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


def create_annotated_pdf(original_filepath, validation_results):
    try:
        pdf = fitz.open(original_filepath)
        detailed_results = validation_results.get('detailed_results', [])
        
        # Define colors
        colors = {
            "PATTENS_BLUE": (210/255.0, 236/255.0, 238/255.0),
            "INDEXED_RGB": (208/255.0, 233/255.0, 222/255.0),
            "PINK_RGB": (251/255.0, 215/255.0, 222/255.0),
            "YEAR_RGB": (255/255.0, 105/255.0, 97/255.0),
            "MISSING_RGB": (255/255.0, 179/255.0, 71/255.0)
        }

        # Extract full text dari PDF untuk mencari references section
        full_text = ''.join(page.get_text() for page in pdf)
        
        # Import annotator baru
        from app.services.pdf_annotator import find_references_section_in_text, annotate_pdf_page
        
        # Cari keyword references section
        found_line_num, found_keyword = find_references_section_in_text(full_text)
        
        if found_line_num == -1:
            logger.warning("⚠️ Tidak ditemukan bagian referensi, akan mencoba annotate semua halaman")
            found_keyword = None
        else:
            lines = full_text.splitlines()
            total_lines = len(lines)
            percentage = (found_line_num / total_lines) * 100 if total_lines > 0 else 0
            logger.info(f"✅ Menemukan bagian referensi menggunakan keyword: '{found_keyword}'")
            logger.info(f"   Baris: {found_line_num + 1}/{total_lines} ({percentage:.1f}% dari awal dokumen)")

        start_annotating = False
        added_references_summary = False
        
        for page_num, page in enumerate(pdf):
            # Panggil annotator baru
            start_annotating, added_references_summary = annotate_pdf_page(
                page=page,
                page_num=page_num,
                detailed_results=detailed_results,
                validation_results=validation_results,
                start_annotating=start_annotating,
                added_references_summary=added_references_summary,
                found_keyword=found_keyword,
                found_line_num=found_line_num,
                colors=colors,
                full_pdf_text=full_text
            )

        # Finalisasi PDF
        pdf_bytes = pdf.tobytes()
        pdf.close()
        return pdf_bytes, None

    except Exception as e:
        logger.error(f"Error fatal di create_annotated_pdf: {e}", exc_info=True)
        return None, "Gagal total saat proses anotasi PDF."
