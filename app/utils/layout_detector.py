import logging
from statistics import median

logger = logging.getLogger(__name__)


def detect_layout(page, width_threshold=0.65):
    """
    Mendeteksi tata letak halaman (satu atau multi-kolom) berdasarkan
    lebar median dari blok-blok teks.

    Args:
        page: PyMuPDF page object
        width_threshold (float): Threshold untuk menentukan multi-column (default 0.65)
        
    Returns:
        str: 'single_column' atau 'multi_column'
    """
    page_width = page.rect.width
    if page_width == 0:
        return 'single_column'  # Fallback

    # Gunakan 'blocks' untuk mendapatkan grup paragraf yang lebih alami
    blocks = page.get_text("blocks", sort=True)
    if not blocks:
        return 'single_column'

    # Filter blok yang terlalu kecil (kemungkinan noise atau nomor halaman)
    block_widths = [
        b[2] - b[0] for b in blocks 
        if (b[3] - b[1]) > 8 and (b[2] - b[0]) > 20
    ]
    
    if not block_widths:
        return 'single_column'

    median_width = median(block_widths)

    # Jika lebar median blok teks kurang dari threshold, anggap multi-kolom
    if median_width < page_width * width_threshold:
        logger.info(
            f"Halaman {page.number+1}: Terdeteksi layout multi-kolom "
            f"(lebar median: {median_width:.1f} vs lebar halaman: {page_width:.1f})"
        )
        return 'multi_column'
    else:
        logger.info(
            f"Halaman {page.number+1}: Terdeteksi layout satu kolom "
            f"(lebar median: {median_width:.1f} vs lebar halaman: {page_width:.1f})"
        )
        return 'single_column'
