import logging
import os
import io
import shutil
import subprocess
import docx
import xml.etree.ElementTree as ET
from docx2pdf import convert
from app.utils.text_utils import is_likely_reference

logger = logging.getLogger(__name__)


def get_paragraph_text(paragraph):
    WORD_NAMESPACE = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    TEXT = WORD_NAMESPACE + 't'
    xml_string = paragraph._p.xml
    
    try:
        xml_tree = ET.fromstring(xml_string)
        text_nodes = xml_tree.findall('.//' + TEXT)
        if text_nodes:
            return "".join(node.text for node in text_nodes if node.text)
    except ET.ParseError:
        return paragraph.text
    
    return ""


def extract_references_from_docx(file_stream):
    try:
        doc = docx.Document(io.BytesIO(file_stream.read()))
        
        # Gunakan pembaca XML untuk menangani field codes Mendeley
        all_paragraphs = [get_paragraph_text(p).strip() for p in doc.paragraphs]
        paragraphs = [p for p in all_paragraphs if p]  # Filter baris kosong

        REFERENCE_HEADINGS = [
            "daftar pustaka", "daftar referensi", "referensi",
            "bibliography", "references", "pustaka rujukan", "reference"
        ]
        
        start_index = -1
        
        # Cari judul dari depan
        for i, para in enumerate(paragraphs):
            if any(h == para.lower() for h in REFERENCE_HEADINGS):
                # Verifikasi konteks
                for j in range(i + 1, min(i + 6, len(paragraphs))):
                    if is_likely_reference(paragraphs[j]):
                        start_index = j
                        break
                if start_index != -1:
                    break
        
        if start_index == -1:
            return None, "Bagian 'Daftar Pustaka' tidak ditemukan atau tidak diikuti konten valid di file DOCX."

        # PENTING: Deteksi AKHIR section references (seperti teman)
        END_KEYWORDS = [
            'acknowledgments', 'acknowledgements', 'acknowledgment',
            'ucapan terima kasih', 'terima kasih',
            'appendix', 'appendices', 'lampiran',
            'about the authors', 'about authors', 'author information',
            'tentang penulis', 'biography', 'biografi',
            'author contributions', 'kontribusi penulis',
            'funding', 'pendanaan',
            'conflict of interest', 'conflicts of interest', 'konflik kepentingan',
            'competing interests',
            'data availability', 'ketersediaan data',
        ]
        
        end_index = len(paragraphs)  # Default: sampai akhir
        
        # Cari section setelah references
        for i in range(start_index, len(paragraphs)):
            para_lower = paragraphs[i].lower().strip()
            # Cek apakah ini heading (pendek dan match keyword)
            if len(para_lower.split()) <= 5:
                if any(keyword in para_lower for keyword in END_KEYWORDS):
                    end_index = i
                    logger.info(f"✂️ Berhenti di section: '{paragraphs[i]}' (baris #{i})")
                    break
        
        # Ambil paragraf dari start sampai end (BUKAN sampai akhir dokumen!)
        references_block = "\n".join(paragraphs[start_index:end_index])
        
        if not references_block.strip():
            return None, "Bagian 'Daftar Pustaka' ditemukan di DOCX, tetapi isinya kosong."
        
        logger.info(f"✅ Berhasil mengekstrak blok teks referensi dari DOCX")
        logger.info(f"   📄 Total paragraf: {len(paragraphs[start_index:end_index])}")
        logger.info(f"   📏 Panjang teks: {len(references_block)} karakter")
        return references_block, None
        
    except Exception as e:
        logger.error(f"Gagal memproses file .docx: {e}", exc_info=True)
        return None, f"Gagal memproses file .docx: {e}"


def convert_docx_to_pdf(docx_path):
    try:
        # Tentukan path output
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
                            subprocess.check_call([
                                shutil.which('soffice'),
                                '--headless',
                                '--convert-to', 'pdf',
                                '--outdir', os.path.dirname(pdf_path),
                                docx_path
                            ])
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
                        subprocess.check_call([
                            shutil.which('soffice'),
                            '--headless',
                            '--convert-to', 'pdf',
                            '--outdir', os.path.dirname(pdf_path),
                            docx_path
                        ])
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
        logger.error(f"Error saat mengonversi DOCX ke PDF: {e}", exc_info=True)
        help_msg = (
            "Gagal mengonversi DOCX ke PDF. Jika Anda menggunakan Windows, pastikan Microsoft Word terinstal "
            "dan aplikasi berjalan setidaknya sekali. Jika server/headless, pasang LibreOffice dan coba lagi. "
            f"Detail teknis: {e}"
        )
        return None, help_msg
