import re
import logging

logger = logging.getLogger(__name__)


def is_likely_reference(text):
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


def find_references_section(paragraphs):
    REFERENCE_HEADINGS = [
        "daftar pustaka", "daftar referensi", "referensi", 
        "reference", "references", "bibliography", "pustaka rujukan"
    ]
    STOP_HEADINGS = [
        "lampiran", "appendix", "biodata", 
        "curriculum vitae", "riwayat hidup"
    ]

    start_index = -1
    
    # Cari judul daftar pustaka dari belakang
    for i in range(len(paragraphs) - 1, -1, -1):
        para = paragraphs[i].strip()
        para_lower = para.lower()
        
        if any(h in para_lower for h in REFERENCE_HEADINGS) and len(para.split()) < 5:
            if i + 1 < len(paragraphs) and is_likely_reference(paragraphs[i + 1]):
                start_index = i + 1
                break

    # Jika tidak ketemu, cari dari belakang tanpa validasi
    if start_index == -1:
        for i in range(len(paragraphs) - 1, -1, -1):
            para = paragraphs[i].strip()
            if any(h in para.lower() for h in REFERENCE_HEADINGS) and len(para.split()) < 5:
                start_index = i + 1
                break

    if start_index == -1:
        return None, "Bagian 'Daftar Pustaka' tidak ditemukan."

    # Tangkap paragraf referensi
    captured_paragraphs = []
    consecutive_non_ref_count = 0

    for j in range(start_index, len(paragraphs)):
        para = paragraphs[j]

        # Jika menemukan judul STOP_HEADINGS, berhenti
        if any(stop in para.lower() for stop in STOP_HEADINGS):
            logger.info(f"Berhenti karena menemukan judul stop: '{para}'")
            break

        # Logika utama: deteksi referensi
        if is_likely_reference(para):
            captured_paragraphs.append(para)
            consecutive_non_ref_count = 0
        else:
            # Tambahkan ke baris sebelumnya (baris lanjutan)
            if captured_paragraphs:
                captured_paragraphs[-1] += " " + para.strip()
            consecutive_non_ref_count += 1

        # Berhenti jika pola tidak menyerupai referensi
        if consecutive_non_ref_count >= 5 or (
            consecutive_non_ref_count >= 3 and len(para.strip()) < 30
        ):
            logger.info("Berhenti menangkap karena pola teks tidak lagi menyerupai referensi.")
            break

    # Bersihkan trailing paragraf yang tidak mengandung tahun atau DOI
    while captured_paragraphs and not re.search(r'\(\d{4}\)|doi\.org', captured_paragraphs[-1]):
        captured_paragraphs.pop()

    references_block = "\n".join(captured_paragraphs).strip()
    if not references_block:
        return None, "Bagian 'Daftar Pustaka' ditemukan, tetapi kosong."

    return references_block, None


def collect_reference_markers(words):
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
                        'x': (w[0] + w[2]) / 2.0,
                        'wi': wi
                    })
                except Exception:
                    pass
                break
    
    markers.sort(key=lambda d: d['y'])
    
    # Tambahkan next_y untuk setiap marker
    for idx, mk in enumerate(markers):
        mk_next_y = markers[idx + 1]['y'] if idx + 1 < len(markers) else None
        mk['next_y'] = mk_next_y
    
    return markers
