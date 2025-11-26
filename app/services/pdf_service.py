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
        
        # Gabung SEMUA teks dari semua halaman jadi 1 string (seperti teman)
        full_text = ''.join(page.get_text() for page in doc)
        doc.close()
        
        # Cari posisi "References" section menggunakan find_references_section
        from app.services.pdf_annotator import find_references_section_in_text, find_end_of_references
        
        line_num, found_keyword, references_index = find_references_section_in_text(full_text)
        
        if references_index == -1:
            return None, "Judul bagian 'Daftar Pustaka' / 'References' tidak ditemukan dalam dokumen PDF."
        
        logger.info(f"✅ Menemukan keyword '{found_keyword}' di character index {references_index}")
        
        # Cari akhir section references (stop di Acknowledgments, Appendix, dll)
        end_index = find_end_of_references(full_text, references_index)
        
        # Extract references text berdasarkan character index (seperti teman!)
        if end_index != -1:
            references_block = full_text[references_index:end_index]
            logger.info(f"✂️ Berhenti di character index {end_index}")
        else:
            references_block = full_text[references_index:]
            logger.info(f"📄 Mengambil sampai akhir dokumen")
        
        if not references_block.strip():
            return None, "Bagian 'Daftar Pustaka' ditemukan, tetapi tampaknya kosong."

        logger.info(f"✅ Berhasil mengekstrak blok teks referensi dari PDF.")
        logger.info(f"   📏 Panjang teks: {len(references_block)} karakter")
        
        # Hitung estimasi jumlah referensi
        import re
        estimated_count = len(re.findall(r'^\s*\d+\.\s|\[\d+\]', references_block, re.MULTILINE))
        if estimated_count > 0:
            logger.info(f"   🔢 Estimasi jumlah referensi: {estimated_count}")
        
        return references_block, None
        
    except Exception as e:
        logger.error(f"Gagal memproses file PDF: {e}", exc_info=True)
        # User-friendly error message
        error_msg = "Maaf, terjadi kesalahan saat memproses file PDF Anda. "
        
        if "password" in str(e).lower() or "encrypted" in str(e).lower():
            error_msg += "File PDF ter-enkripsi atau dilindungi password. Mohon gunakan file yang tidak terproteksi."
        elif "corrupt" in str(e).lower() or "damaged" in str(e).lower():
            error_msg += "File PDF tampaknya rusak atau tidak valid. Mohon coba file lain."
        elif "memory" in str(e).lower():
            error_msg += "File PDF terlalu besar untuk diproses. Mohon gunakan file yang lebih kecil."
        else:
            error_msg += "Pastikan file PDF Anda valid dan tidak rusak."
        
        return None, error_msg


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
        result = find_references_section_in_text(full_text)
        
        # Handle both old (2 values) and new (3 values) return formats
        if len(result) == 3:
            found_line_num, found_keyword, found_char_index = result
        else:
            found_line_num, found_keyword = result
            found_char_index = -1
        
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
