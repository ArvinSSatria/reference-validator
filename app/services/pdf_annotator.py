import logging
import re
import fitz
from datetime import datetime

logger = logging.getLogger(__name__)


def normalize_text_for_search(text):
    """
    Normalize text untuk pencarian PDF yang lebih fleksibel.
    Menghapus line breaks, normalize whitespace, dan karakter special.
    """
    if not text:
        return ""
    
    # Hapus line breaks dan ganti dengan spasi
    text = text.replace('\n', ' ').replace('\r', ' ')
    
    # Normalize multiple spaces menjadi single space
    text = re.sub(r'\s+', ' ', text)
    
    # Trim leading/trailing spaces
    text = text.strip()
    
    return text


def merge_close_rects(rects, max_distance=10):
    """
    Merge rects yang sangat dekat secara horizontal pada baris yang sama.
    Mengatasi masalah highlight terpecah untuk nama jurnal yang sama.
    
    Contoh: "Comput." dan "Linguist." di baris yang sama akan digabung jadi 1 highlight.
    
    Args:
        rects: List of fitz.Rect objects dari page.search_for()
        max_distance: Jarak horizontal maksimum (dalam PDF points) untuk dianggap satu unit
    
    Returns:
        List of merged fitz.Rect objects
    """
    if not rects:
        return []
    
    # Sort berdasarkan posisi: y0 (vertikal) lalu x0 (horizontal)
    rects = sorted(rects, key=lambda r: (r.y0, r.x0))
    merged = []
    current = rects[0]
    
    for r in rects[1:]:
        # Cek apakah di baris yang sama
        same_line = abs(r.y0 - current.y0) < 3
        # Cek apakah cukup dekat horizontal
        close_enough = (r.x0 - current.x1) < max_distance
        
        if same_line and close_enough:
            # Gabungkan rect (union)
            current = current | r
        else:
            # Simpan current dan mulai yang baru
            merged.append(current)
            current = r
    
    # Jangan lupa tambahkan yang terakhir
    merged.append(current)
    
    return merged


def group_rects_by_proximity(rects, max_vertical_distance=15, max_horizontal_gap=50):
    """
    Kelompokkan rects yang merupakan bagian dari satu kemunculan teks yang sama.
    Ini mengatasi masalah dimana nama jurnal terpotong ke beberapa baris berbeda.
    
    Contoh: "Comput." di baris 1 dan "Linguist." di baris 2 akan dijadikan satu grup.
    
    Args:
        rects: List of fitz.Rect objects dari page.search_for()
        max_vertical_distance: Jarak vertikal maksimum (tinggi baris) untuk dianggap satu grup
        max_horizontal_gap: Jarak horizontal maksimum untuk continuation ke baris berikutnya
    
    Returns:
        List of lists, dimana setiap inner list adalah grup rects yang saling berdekatan
    """
    if not rects:
        return []
    
    # Sort berdasarkan posisi vertikal (y0) lalu horizontal (x0)
    rects = sorted(rects, key=lambda r: (r.y0, r.x0))
    
    groups = []
    current_group = [rects[0]]
    
    for i in range(1, len(rects)):
        prev_rect = rects[i - 1]
        curr_rect = rects[i]
        
        # Hitung jarak vertikal (antar baris)
        vertical_distance = abs(curr_rect.y0 - prev_rect.y0)
        
        # Hitung jarak horizontal
        horizontal_distance = curr_rect.x0 - prev_rect.x1
        
        # Cek apakah rect ini bagian dari grup yang sama
        same_line = vertical_distance < 3  # Masih di baris yang sama
        next_line = 3 <= vertical_distance <= max_vertical_distance  # Baris berikutnya
        close_horizontally = horizontal_distance < max_horizontal_gap
        
        if same_line or (next_line and close_horizontally):
            # Masih satu grup
            current_group.append(curr_rect)
        else:
            # Grup baru
            groups.append(current_group)
            current_group = [curr_rect]
    
    # Jangan lupa tambahkan grup terakhir
    if current_group:
        groups.append(current_group)
    
    return groups


def find_references_section_in_text(full_text):
    """
    Find the references/bibliography section using smart heuristics.
    
    Strategy:
    1. Find keyword (REFERENCES, DAFTAR PUSTAKA, etc.) that stands ALONE on a line
    2. Validate it's actually a references section (has years, citations pattern)
    3. Pick the one closest to END of document (usually > 50%)
    
    Returns (line_number, keyword_found) or (-1, None)
    """
    # Daftar kata kunci untuk bagian referensi
    keywords = [
        'REFERENCES',
        'REFERENCE',
        'REFERENSI',
        'DAFTAR REFERENSI',
        'DAFTAR PUSTAKA',
        'DAFTAR RUJUKAN',
        'DAFTAR BACAAN',
        'SUMBER PUSTAKA',
        'SUMBER RUJUKAN',
        'BIBLIOGRAPHY',
        'BIBLIOGRAFI',
        'PUSTAKA',
        'RUJUKAN',
        'LITERATURE CITED',
        'LIST OF REFERENCES',
        'WORKS CITED',
    ]
    
    lines = full_text.splitlines()
    total_lines = len(lines)
    
    candidates = []
    
    # Build keyword pattern - kata kunci berdiri sendiri di satu baris
    keyword_pattern = '|'.join(keywords)
    pattern = re.compile(rf'^\s*({keyword_pattern})\s*$', re.IGNORECASE)
    
    # Cari semua kandidat yang match pattern
    for line_num, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            keyword_found = match.group(1)
            
            # Hitung posisi persentase dalam dokumen
            percentage = (line_num / total_lines) * 100
            
            # ✅ ATURAN 1: Kata kunci berdiri sendiri di baris tersendiri ✓
            # (sudah dicek dengan regex pattern)
            
            # ✅ ATURAN 2: Validasi ada banyak tahun di bawahnya
            # Ambil 50 baris berikutnya untuk validasi
            sample_lines = lines[line_num:line_num + 50]
            sample_text = "\n".join(sample_lines)
            
            # Cari pola tahun (19xx atau 20xx)
            year_matches = re.findall(r'\b(19|20)\d{2}\b', sample_text)
            year_count = len(year_matches)
            
            # Cari pola DOI atau URL (indikasi referensi)
            doi_count = len(re.findall(r'doi\.org|DOI:|https?://', sample_text, re.IGNORECASE))
            
            # Cari pola nama penulis (kapitalisasi seperti "Smith, J." atau "A. B. Smith")
            author_pattern = r'\b[A-Z][a-z]+,\s*[A-Z]\.|[A-Z]\.\s*[A-Z]\.\s*[A-Z][a-z]+'
            author_count = len(re.findall(author_pattern, sample_text))
            
            # Cari pola citation patterns (e.g., [1], 1. , (2023), [2023a])
            citation_matches = re.findall(r'^\s*\[\d+\]|^\s*\d+\.\s+[A-Z]|[\[\(]\d{4}[a-z]?\)', sample_text, re.MULTILINE)
            citation_count = len(citation_matches)
            
            # Skor validasi
            validation_score = 0
            content_score = 0
            position_score = 0
            format_score = 0
            
            # Content validation (apakah ada ciri-ciri referensi?)
            if year_count >= 3:
                content_score += 3  # Banyak tahun = kuat
            if year_count >= 5:
                content_score += 2  # Sangat banyak tahun = sangat kuat
            if doi_count >= 1:
                content_score += 4  # Ada DOI/URL = sangat kuat
            if author_count >= 2:
                content_score += 2  # Ada pola author
            if citation_count >= 2:
                content_score += 4  # Ada pola citation numbering = sangat kuat
            
            # Position validation (harus di akhir dokumen)
            if percentage < 40:
                position_score = -20  # HEAVY PENALTY untuk keyword di awal dokumen
            elif percentage >= 40 and percentage < 60:
                position_score = -5  # Penalty sedang untuk keyword di tengah
            elif percentage >= 60 and percentage < 80:
                position_score = 5  # Bonus untuk keyword di akhir
            elif percentage >= 80:
                position_score = 10  # BONUS BESAR untuk keyword di akhir sekali
            
            # Format validation (apakah benar-benar header?)
            clean_line = line.strip()
            
            # Bonus besar untuk ALL CAPS headers
            if clean_line == clean_line.upper() and len(clean_line) > 1:
                format_score += 5
            
            # Bonus jika didahului blank line (ciri header)
            if line_num > 0 and not lines[line_num - 1].strip():
                format_score += 3
            
            # Bonus jika diikuti blank line (ciri header)
            if line_num < total_lines - 1 and not lines[line_num + 1].strip():
                format_score += 2
            
            # CRITICAL: Heavy penalty jika line mengandung teks lain (bukan standalone header)
            if clean_line.lower() != keyword_found.lower():
                format_score -= 15  # HEAVY PENALTY - ini bukan header standalone
            
            # Penalty jika line dimulai dengan citation pattern (e.g., "[1]", "(a)")
            if re.match(r'^\s*[\(\[\d]', line):
                format_score -= 10
            
            # Penalty jika ada banyak kata lain di baris yang sama
            word_count = len(clean_line.split())
            if word_count > 3:  # "DAFTAR PUSTAKA" = 2 kata, masih OK
                format_score -= 5
            
            validation_score = content_score + position_score + format_score
            
            candidates.append({
                'line_num': line_num,
                'keyword': keyword_found,
                'percentage': percentage,
                'year_count': year_count,
                'doi_count': doi_count,
                'author_count': author_count,
                'citation_count': citation_count,
                'content_score': content_score,
                'position_score': position_score,
                'format_score': format_score,
                'validation_score': validation_score
            })
    
    if not candidates:
        return -1, None
    
    # Sort kandidat berdasarkan:
    # 1. Validation score (descending) - yang paling valid
    # 2. Percentage (descending) - yang paling akhir
    candidates.sort(key=lambda x: (x['validation_score'], x['percentage']), reverse=True)
    
    # Log semua kandidat untuk debugging
    logger.info(f"📋 Found {len(candidates)} reference section candidate(s):")
    for i, cand in enumerate(candidates[:5]):  # Tampilkan top 5
        logger.info(
            f"  #{i+1}: Line {cand['line_num']} ({cand['percentage']:.1f}%) - "
            f"'{cand['keyword']}' | "
            f"Score: {cand['validation_score']} "
            f"(content:{cand['content_score']}, pos:{cand['position_score']}, fmt:{cand['format_score']}) | "
            f"Years:{cand['year_count']}, Citations:{cand['citation_count']}, DOIs:{cand['doi_count']}"
        )
    
    # Ambil kandidat terbaik
    best = candidates[0]
    
    logger.info(
        f"✅ Selected: Line {best['line_num']} ({best['percentage']:.1f}%) - "
        f"'{best['keyword']}' with score {best['validation_score']}"
    )
    
    # Hitung character index
    char_index = sum(len(line) + 1 for line in lines[:best['line_num']])
    
    return best['line_num'], best['keyword'], char_index


def find_end_of_references(text, start_index):
    """
    Find the end of references section by looking for common section headers that come after references.
    
    Keywords to look for:
    - ACKNOWLEDGMENTS / ACKNOWLEDGEMENTS / UCAPAN TERIMA KASIH
    - APPENDIX / APPENDICES / LAMPIRAN
    - ABOUT AUTHORS / TENTANG PENULIS
    - AUTHOR CONTRIBUTIONS / KONTRIBUSI PENULIS
    - FUNDING / PENDANAAN
    - CONFLICT OF INTEREST / KONFLIK KEPENTINGAN
    - BIOGRAPHY / BIOGRAFI
    
    Returns character index of end section, or -1 if not found
    """
    # List of keywords for sections after references
    end_keywords = [
        'ACKNOWLEDGMENTS',
        'ACKNOWLEDGEMENTS',
        'ACKNOWLEDGMENT',
        'ACKNOWLEDGEMENT',
        'UCAPAN TERIMA KASIH',
        'TERIMA KASIH',
        'APPENDIX',
        'APPENDICES',
        'LAMPIRAN',
        'ABOUT THE AUTHORS',
        'ABOUT AUTHORS',
        'AUTHOR INFORMATION',
        'TENTANG PENULIS',
        'AUTHOR CONTRIBUTIONS',
        'KONTRIBUSI PENULIS',
        'FUNDING',
        'PENDANAAN',
        'CONFLICT OF INTEREST',
        'CONFLICTS OF INTEREST',
        'KONFLIK KEPENTINGAN',
        'COMPETING INTERESTS',
        'BIOGRAPHY',
        'BIOGRAFI',
        'AUTHOR BIOGRAPHY',
        'AUTHORS BIOGRAPHY',
    ]
    
    search_text = text[start_index:]
    
    earliest_index = -1
    found_keyword = None
    
    for keyword in end_keywords:
        # Case-insensitive search
        pattern = re.compile(keyword, re.IGNORECASE)
        match = pattern.search(search_text)
        
        if match:
            absolute_index = start_index + match.start()
            
            if earliest_index == -1 or absolute_index < earliest_index:
                earliest_index = absolute_index
                found_keyword = keyword
    
    if found_keyword:
        logger.info(f"Found end section keyword: '{found_keyword}' at index {earliest_index}")
    else:
        logger.info("No section found after references, using end of document")
    
    return earliest_index


def annotate_pdf_page(
    page,
    page_num,
    detailed_results,
    validation_results,
    start_annotating,
    added_references_summary,
    found_keyword,
    found_line_num,
    colors,
    full_pdf_text
):
    """
    Annotate satu halaman PDF dengan highlight untuk:
    1. Heading "References" / "Daftar Pustaka"
    2. Nama jurnal (hijau jika terindeks, pink jika tidak)
    3. Tahun yang outdated (merah)
    
    Menggunakan strategi pencarian bertingkat untuk menghindari tumpang tindih highlight.
    """
    # Ekstrak warna dari dictionary
    PATTENS_BLUE = colors['PATTENS_BLUE']
    INDEXED_RGB = colors['INDEXED_RGB']
    PINK_RGB = colors['PINK_RGB']
    YEAR_RGB = colors['YEAR_RGB']
    MISSING_RGB = colors['MISSING_RGB']

    # BAGIAN 1: DETEKSI HEADING DAN SUMMARY
    # Cari keyword references di halaman ini HANYA jika line_num sudah tervalidasi
    page_text = page.get_text()
    
    # Hitung halaman mana yang seharusnya mengandung found_line_num
    if found_keyword and found_line_num >= 0 and not added_references_summary:
        # Hitung line offset untuk setiap halaman
        lines = full_pdf_text.splitlines()
        
        # Cari character offset dari found_line_num
        target_char_offset = sum(len(line) + 1 for line in lines[:found_line_num])
        
        # Hitung apakah halaman ini mengandung target_char_offset
        current_char_offset = 0
        is_target_page = False
        
        # Iterasi semua halaman untuk menemukan halaman yang tepat
        # (kita tidak bisa iterate di sini karena sudah dalam loop page)
        # Jadi kita hitung dari full_pdf_text
        
        # Alternatif: Cek apakah keyword ada di halaman ini DAN dekat dengan posisi yang diharapkan
        if found_keyword.upper() in page_text.upper():
            # Cari posisi keyword di halaman
            page_results_raw = page.search_for(found_keyword)
            
            if page_results_raw:
                # Hitung persentase halaman ini dalam dokumen
                # Untuk validasi apakah ini halaman yang tepat
                
                # Kelompokkan rects untuk keyword (jika terpotong multi-baris)
                rect_groups = group_rects_by_proximity(page_results_raw, max_vertical_distance=15, max_horizontal_gap=50)
                
                # Filter: Pilih grup yang paling akhir (terdekat dengan daftar pustaka sebenarnya)
                if rect_groups:
                    # Sort berdasarkan posisi vertikal (y0) - ambil yang paling bawah di halaman
                    rect_groups_sorted = sorted(rect_groups, key=lambda g: g[0].y0, reverse=True)
                    
                    # Cek semua kemunculan keyword di halaman ini
                    for group_idx, group_rects in enumerate(rect_groups_sorted):
                        # Validasi tambahan: Cek apakah ada konten referensi di bawah keyword ini
                        keyword_y_position = group_rects[0].y0
                        
                        # Ekstrak teks di bawah keyword (100 karakter berikutnya)
                        words_below = []
                        words_on_page = page.get_text("words")
                        for w in words_on_page:
                            if w[1] > keyword_y_position:  # y0 > keyword position
                                words_below.append(str(w[4]))
                            if len(words_below) >= 50:  # Cukup 50 kata
                                break
                        
                        text_below = ' '.join(words_below)
                        
                        # Validasi: Cek apakah ada pola referensi di bawah keyword
                        years_below = len(re.findall(r'\b(19|20)\d{2}\b', text_below))
                        citations_below = len(re.findall(r'\[\d+\]|\(\d{4}\)', text_below))
                        
                        # Jika validasi lolos, gunakan grup ini
                        if years_below >= 2 or citations_below >= 1:
                            # Ini kemungkinan besar keyword yang benar!
                            
                            # Hitung statistik
                            total = len(detailed_results)
                            journal_count = sum(1 for r in detailed_results if r.get('reference_type') == 'journal')
                            book_count = sum(1 for r in detailed_results if r.get('reference_type') == 'book')
                            conference_count = sum(1 for r in detailed_results if r.get('reference_type') == 'conference')
                            other_count = total - journal_count - book_count - conference_count
                            
                            # Hitung yang terindeks di ScimagoJR dan Scopus
                            sjr_count = sum(1 for r in detailed_results if r.get('is_indexed_scimago'))
                            scopus_count = sum(1 for r in detailed_results if r.get('is_indexed_scopus'))
                            both_count = sum(1 for r in detailed_results if r.get('is_indexed_scimago') and r.get('is_indexed_scopus'))
                            
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
                                f"• Jurnal: {journal_count} ({(journal_count/total*100) if total else 0:.1f}%)\n"
                                f"• Buku: {book_count} ({(book_count/total*100) if total else 0:.1f}%)\n"
                                f"• Konferensi: {conference_count} ({(conference_count/total*100) if total else 0:.1f}%)\n"
                                f"• Lainnya: {other_count}\n\n"
                                f"Terindeks:\n"
                                f"• ScimagoJR: {sjr_count} ({(sjr_count/total*100) if total else 0:.1f}%)\n"
                                f"• Scopus: {scopus_count} ({(scopus_count/total*100) if total else 0:.1f}%)\n"
                                f"• Keduanya: {both_count} ({(both_count/total*100) if total else 0:.1f}%)\n\n"
                                f"Validitas Tahun (Recent): {year_approved} dari {total}\n"
                                f"Kuartil SJR:\n"
                                f"• Q1:{q_counts['Q1']}\n"
                                f"• Q2:{q_counts['Q2']}\n"
                                f"• Q3:{q_counts['Q3']}\n"
                                f"• Q4:{q_counts['Q4']}\n"
                                f"• Tidak Ditemukan:{q_counts['Not Found']}\n"
                                f"Dibuat pada {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                            
                            # Highlight keyword dengan warna biru
                            highlight = page.add_highlight_annot(group_rects)
                            highlight.set_colors(stroke=PATTENS_BLUE, fill=PATTENS_BLUE)
                            highlight.set_info(title="Ringkasan Validasi", content=summary_content)
                            highlight.update()
                            
                            added_references_summary = True
                            start_annotating = True
                            logger.info(f"✅ Summary highlight ditambahkan pada keyword '{found_keyword}' di halaman {page_num + 1} (grup #{group_idx+1}, years_below={years_below}, citations_below={citations_below})")
                            
                            break  # Keluar dari loop rect_groups setelah menemukan yang tepat

    # BAGIAN 2: HIGHLIGHT SEMUA REFERENSI (JOURNAL, BOOK, DLL)
    # Kumpulkan semua kemunculan full_reference_text di halaman ini
    all_search_results = {}
    
    if start_annotating:
        # Sort results berdasarkan panjang full_reference (descending) untuk prioritas
        sorted_results = sorted(
            detailed_results,
            key=lambda r: len(r.get('full_reference', '')),
            reverse=True
        )
        
        for result in sorted_results:
            # PERBAIKAN: Highlight SEMUA tipe referensi (journal, book, conference, dll)
            # Tidak hanya journal yang terindeks
                
            ref_number = result.get('reference_number')
            journal_name = result.get('parsed_journal', '')
            raw_ref_text = result.get('raw_reference', '')
            full_ref_text = result.get('full_reference', '')
            ref_type = result.get('reference_type', 'other')
            
            if not full_ref_text or len(full_ref_text) < 10:
                logger.warning(f"⚠️ Ref #{ref_number} ({ref_type}): Full reference text terlalu pendek atau kosong")
                continue
            
            # Strategi pencarian bertingkat
            page_results_raw = []
            search_strategy = None
            
            # PRIORITAS 1: Coba raw_reference_text dulu (paling akurat untuk PDF)
            if raw_ref_text and len(raw_ref_text) > 20:
                page_results_raw = page.search_for(raw_ref_text)
                if page_results_raw:
                    search_strategy = "raw_full_text"
            
            # PRIORITAS 2: 150 karakter pertama dari raw_reference_text
            if not page_results_raw and raw_ref_text and len(raw_ref_text) > 150:
                text_150 = normalize_text_for_search(raw_ref_text[:150])
                page_results_raw = page.search_for(text_150)
                if page_results_raw:
                    search_strategy = "raw_start_150"
            
            # PRIORITAS 3: 80 karakter pertama dari raw_reference_text
            if not page_results_raw and raw_ref_text and len(raw_ref_text) > 80:
                text_80 = normalize_text_for_search(raw_ref_text[:80])
                page_results_raw = page.search_for(text_80)
                if page_results_raw:
                    search_strategy = "raw_start_80"
            
            # PRIORITAS 4: 40 karakter pertama dari raw_reference_text
            if not page_results_raw and raw_ref_text and len(raw_ref_text) > 40:
                text_40 = normalize_text_for_search(raw_ref_text[:40])
                page_results_raw = page.search_for(text_40)
                if page_results_raw:
                    search_strategy = "raw_start_40"
            
            # FALLBACK 1: Coba full_reference (teks bersih) jika raw_reference gagal
            if not page_results_raw and len(full_ref_text) > 20:
                page_results_raw = page.search_for(full_ref_text)
                if page_results_raw:
                    search_strategy = "full_text"
            
            # FALLBACK 2: 150 karakter pertama (normalized) dari full_reference
            if not page_results_raw and len(full_ref_text) > 150:
                text_150 = normalize_text_for_search(full_ref_text[:150])
                page_results_raw = page.search_for(text_150)
                if page_results_raw:
                    search_strategy = "start_150"
            
            # FALLBACK 3: 80 karakter pertama (normalized)
            if not page_results_raw and len(full_ref_text) > 80:
                text_80 = normalize_text_for_search(full_ref_text[:80])
                page_results_raw = page.search_for(text_80)
                if page_results_raw:
                    search_strategy = "start_80"
            
            # FALLBACK 4: 40 karakter pertama (normalized)
            if not page_results_raw and len(full_ref_text) > 40:
                text_40 = normalize_text_for_search(full_ref_text[:40])
                page_results_raw = page.search_for(text_40)
                if page_results_raw:
                    search_strategy = "start_40"
            
            # FALLBACK 5: 30 karakter pertama (normalized)
            if not page_results_raw and len(full_ref_text) > 30:
                text_30 = normalize_text_for_search(full_ref_text[:30])
                page_results_raw = page.search_for(text_30)
                if page_results_raw:
                    search_strategy = "start_30"
            
            # Skip jika tidak ada hasil
            if not page_results_raw:
                logger.warning(f"❌ Ref #{ref_number}: Tidak ditemukan di halaman {page_num + 1}")
                if full_ref_text:
                    preview = full_ref_text[:50] if len(full_ref_text) > 50 else full_ref_text
                    logger.info(f"   Teks dicari (50 char): '{preview}...'")
                continue
            
            # OPTIMASI: Merge rects yang sangat dekat di baris yang sama
            # Untuk mengatasi highlight terpecah (misal: "Comput." dan "Linguist." jadi 1 box)
            page_results_merged = merge_close_rects(page_results_raw, max_distance=10)
            
            # Kelompokkan rects yang merupakan satu kemunculan yang sama
            rect_groups = group_rects_by_proximity(page_results_merged, max_vertical_distance=15, max_horizontal_gap=50)
            
            # Untuk setiap grup (satu kemunculan), simpan untuk diproses
            if ref_number not in all_search_results:
                all_search_results[ref_number] = []
            
            for group in rect_groups:
                # Hitung total area dari grup rects ini
                total_area = sum(abs((r.x1 - r.x0) * (r.y1 - r.y0)) for r in group)
                
                all_search_results[ref_number].append({
                    'page': page,
                    'rects': group,
                    'used': False,
                    'strategy': search_strategy,
                    'total_area': total_area,
                    'result': result
                })
    
    # Track highlighted areas untuk menghindari tumpang tindih
    highlighted_areas = []
    
    def rects_overlap(rects1, rects2, threshold=30):
        """Check if two groups of rects overlap significantly."""
        for r1 in rects1:
            for r2 in rects2:
                intersection = r1 & r2
                if not intersection.is_empty:
                    area1 = abs((r1.x1 - r1.x0) * (r1.y1 - r1.y0))
                    area2 = abs((r2.x1 - r2.x0) * (r2.y1 - r2.y0))
                    area_intersection = abs((intersection.x1 - intersection.x0) * (intersection.y1 - intersection.y0))
                    
                    smaller_area = min(area1, area2)
                    overlap_percentage = (area_intersection / smaller_area * 100) if smaller_area > 0 else 0
                    
                    if overlap_percentage > threshold:
                        return True
        return False
    
    # Assign highlight berdasarkan urutan referensi
    for ref_number in sorted(all_search_results.keys()):
        candidates = all_search_results[ref_number]
        
        if not candidates:
            continue
        
        # Sort kandidat berdasarkan area (terbesar dulu = paling lengkap)
        unused_results = [c for c in candidates if not c['used']]
        unused_results.sort(key=lambda x: x.get('total_area', 0), reverse=True)
        
        target = None
        for candidate in unused_results:
            candidate_rects = candidate['rects']
            candidate_area = candidate.get('total_area', 0)
            
            # Cek apakah overlap dengan highlight yang sudah ada
            has_blocking_overlap = False
            for existing in highlighted_areas:
                existing_rects = existing['rects']
                existing_area = existing.get('total_area', 0)
                
                if rects_overlap(candidate_rects, existing_rects, threshold=30):
                    if existing_area >= candidate_area:
                        has_blocking_overlap = True
                        break
            
            if not has_blocking_overlap:
                target = candidate
                break
        
        # Jika tidak ada kandidat yang cocok, ambil yang terbesar (fallback)
        if target is None and unused_results:
            target = unused_results[0]
            logger.warning(f"⚠️ Ref #{ref_number}: Menggunakan highlight terlebar meski ada overlap")
        
        if target:
            target['used'] = True
            target_rects = target['rects']
            target_area = target.get('total_area', 0)
            result = target['result']
            
            # Hapus highlight yang lebih kecil dan overlap
            highlighted_areas_to_keep = []
            for existing in highlighted_areas:
                existing_rects = existing['rects']
                existing_area = existing.get('total_area', 0)
                
                if rects_overlap(target_rects, existing_rects, threshold=30) and existing_area < target_area:
                    logger.info(f"🗑️ Menghapus highlight parsial yang overlap (area: {existing_area:.0f} < {target_area:.0f})")
                    continue
                
                highlighted_areas_to_keep.append(existing)
            
            highlighted_areas[:] = highlighted_areas_to_keep
            
            # Track highlighted area
            highlighted_areas.append({
                'rects': target_rects,
                'total_area': target_area,
                'ref_number': ref_number
            })
            
            # Buat highlight
            highlight = page.add_highlight_annot(target_rects)
            
            # Set warna berdasarkan status dan tipe
            is_indexed_scimago = result.get('is_indexed_scimago', False)
            is_indexed_scopus = result.get('is_indexed_scopus', False)
            is_indexed = result.get('is_indexed', False)  # Gabungan dari keduanya
            ref_type = result.get('reference_type', 'other')
            status = result.get('status', 'invalid')
            
            # Logika warna:
            # - Hijau (INDEXED_RGB): Journal terindeks di Scimago atau Scopus
            # - Pink (PINK_RGB): Journal tidak terindeks
            # - Kuning (YEAR_RGB): Book, Conference, dan tipe lainnya
            if is_indexed:
                color = INDEXED_RGB  # Hijau untuk yang terindeks
            elif ref_type == 'journal':
                color = PINK_RGB  # Pink untuk journal tidak terindeks
            else:
                color = MISSING_RGB  # Kuning untuk book, conference, website, dll
            
            highlight.set_colors(stroke=color, fill=color)
            
            # Set info
            journal_name = result.get('parsed_journal', 'N/A')
            quartile = result.get('quartile', 'N/A')
            scimago_link = result.get('scimago_link', '')
            scopus_link = result.get('scopus_link', '')
            parsed_year = result.get('parsed_year', 'N/A')
            
            # Build comment text berdasarkan tipe
            if ref_type == 'journal':
                # Buat badge text
                index_badges = []
                if is_indexed_scimago:
                    index_badges.append(f"ScimagoJR (Q{quartile})" if quartile and quartile != 'N/A' else "ScimagoJR")
                if is_indexed_scopus:
                    index_badges.append("Scopus")
                
                badge_text = " & ".join(index_badges) if index_badges else "Tidak Terindeks"
                
                # Format tahun dengan status INVALID jika outdated
                year_display = f"{parsed_year} [INVALID]" if status == 'invalid' else str(parsed_year)
                
                comment_text = (
                    f"[{ref_number}] Journal - {status.upper()}\n"
                    f"Jurnal: {journal_name}\n"
                    f"Tahun: {year_display}\n"
                    f"Indeks: {badge_text}\n"
                )
                if scimago_link:
                    comment_text += f"ScimagoJR: {scimago_link}\n"
                if scopus_link:
                    comment_text += f"Scopus: {scopus_link}\n"
            else:
                # Untuk book, conference, website, dll
                note_text = ""
                if is_indexed_scimago or is_indexed_scopus:
                    # Jika selain jurnal tapi terindeks, beri keterangan
                    index_info = []
                    if is_indexed_scimago:
                        index_info.append("ScimagoJR")
                    if is_indexed_scopus:
                        index_info.append("Scopus")
                    note_text = f"\nCatatan: Terindeks di {' & '.join(index_info)}"
                
                # Format tahun dengan status INVALID jika outdated
                year_display = f"{parsed_year} [INVALID]" if status == 'invalid' else str(parsed_year)
                
                comment_text = (
                    f"[{ref_number}] {ref_type.title()}\n"
                    f"Sumber: {journal_name}\n"
                    f"Tahun: {year_display}\n"
                    f"Status: {status.upper()}{note_text}\n"
                )
            
            # Title untuk annotation
            if is_indexed_scimago and is_indexed_scopus:
                title = "Terindeks ScimagoJR & Scopus"
            elif is_indexed_scimago:
                title = "Terindeks ScimagoJR"
            elif is_indexed_scopus:
                title = "Terindeks Scopus"
            elif ref_type == 'journal':
                title = "Journal (Tidak Terindeks)"
            else:
                title = f"{ref_type.title()}"
            
            highlight.set_info(title=title, content=comment_text)
            highlight.update()
            
            strategy = target.get('strategy', 'unknown')
            strategy_label = {
                'raw_full_text': '✓ Raw Full',
                'raw_start_150': '⚠️ Raw 150 Chars',
                'raw_start_80': '⚠️ Raw 80 Chars',
                'raw_start_40': '⚠️ Raw 40 Chars',
                'full_text': '✓ Cleaned Full',
                'start_150': '⚠️ Cleaned 150 Chars',
                'start_80': '⚠️ Cleaned 80 Chars',
                'start_40': '⚠️ Cleaned 40 Chars',
                'start_30': '⚠️ Cleaned 30 Chars'
            }.get(strategy, '❓ Unknown')
            
            # Emoji berdasarkan status
            if is_indexed:
                status_emoji = "🟢"  # Hijau - terindeks
            elif ref_type == 'journal':
                status_emoji = "🔴"  # Merah - journal tidak terindeks
            else:
                status_emoji = "�"  # Kuning - book/conference/dll
            
            logger.info(f"{status_emoji} Ref #{ref_number} ({ref_type}): {strategy_label} (area: {target_area:.0f})")

    # BAGIAN 3: HIGHLIGHT TAHUN OUTDATED
    if start_annotating:
        top_level_year = validation_results.get('year_range')
        min_year_threshold = int(top_level_year) if top_level_year else 5
        min_year = datetime.now().year - min_year_threshold
        year_pattern = re.compile(r'\b(19\d{2}|20\d{2})\b')
        
        words_on_page = page.get_text("words")
        
        # Build struktur by_line
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
        
        def _is_year_in_quotes(word_idx):
            """Check if year is within quotes (article title)"""
            try:
                quote_chars = {'"', '"', '"', ''', ''', "'"}
                key = (words_on_page[word_idx][5], words_on_page[word_idx][6])
                line = by_line.get(key)
                if not line:
                    return False
                
                line_text = ' '.join(line['words'])
                
                # Hitung quotes di baris
                quote_count = sum(line_text.count(ch) for ch in quote_chars)
                
                if quote_count >= 2:
                    # Cari posisi opening dan closing quotes
                    first_quote_pos = -1
                    last_quote_pos = -1
                    for i, char in enumerate(line_text):
                        if char in quote_chars:
                            if first_quote_pos == -1:
                                first_quote_pos = i
                            last_quote_pos = i
                    
                    # Cek posisi kata match
                    if first_quote_pos != -1 and last_quote_pos != -1 and first_quote_pos != last_quote_pos:
                        try:
                            rel_idx = line['word_indices'].index(word_idx)
                            words = line['words']
                            chars_before_match = sum(len(w) + 1 for w in words[:rel_idx])
                            
                            return first_quote_pos < chars_before_match < last_quote_pos
                        except (ValueError, KeyError):
                            pass
                
                return False
            except Exception:
                return False
        
        def _is_year_in_doi(word_index):
            """Check if year is part of a DOI identifier"""
            try:
                current_word = str(words_on_page[word_index][4])
                
                if 'doi:' in current_word.lower() or current_word.startswith('10.'):
                    return True
                
                for offset in range(1, 6):
                    if word_index - offset < 0:
                        break
                    prev_word = str(words_on_page[word_index - offset][4]).lower()
                    
                    if 'doi:' in prev_word or 'doi' in prev_word:
                        return True
                    
                    if re.match(r'10\.\d{4,}', prev_word):
                        return True
                
                return False
            except Exception:
                return False
        
        def _is_line_a_reference_entry(text_line):
            """Check if line is a reference entry"""
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
                year_str = match.group(0)
                year_int = int(year_str)
                
                # Skip jika tahun recent
                if year_int >= min_year:
                    continue
                
                # Skip jika dalam quotes
                if _is_year_in_quotes(wi):
                    continue
                
                # Skip jika bagian dari DOI
                if _is_year_in_doi(wi):
                    continue
                
                # Cek apakah bagian dari reference entry
                try:
                    current_bno, current_lno = w[5], w[6]
                    current_key = (current_bno, current_lno)
                    is_part_of_reference_entry = False
                    
                    if by_line.get(current_key):
                        if _is_line_a_reference_entry(' '.join(by_line[current_key]['words'])):
                            is_part_of_reference_entry = True
                        else:
                            # Cek baris sebelumnya
                            for offset in range(1, 6):
                                prev_key = (current_bno, current_lno - offset)
                                if by_line.get(prev_key) and _is_line_a_reference_entry(' '.join(by_line[prev_key]['words'])):
                                    is_part_of_reference_entry = True
                                    break
                    
                    if not is_part_of_reference_entry:
                        continue
                except Exception:
                    continue
                
                # Cari reference start line untuk deduplication
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
                
                # Highlight tahun
                try:
                    word_rect = fitz.Rect(w[:4])
                    start_pos = match.start()
                    end_pos = match.end()
                    word_len = len(word_text)
                    
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
                    
                    note_text = f"Tahun: {year_str} [INVALID]\nMinimal: {min_year}\nStatus: Outdated"
                    h.set_info(title="Tahun Outdated", content=note_text)
                    h.update()
                    
                    logger.info(f"✅ Year {year_str} HIGHLIGHTED (outdated, min_year: {min_year})")
                except Exception as e:
                    logger.error(f"❌ Error highlighting tahun {year_str}: {e}")

    return start_annotating, added_references_summary
