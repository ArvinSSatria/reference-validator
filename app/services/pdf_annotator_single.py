import logging
import re
import fitz
from datetime import datetime
from app.services.scimago_service import clean_scimago_title

logger = logging.getLogger(__name__)

from app.utils.text_utils import is_likely_reference, collect_reference_markers

def annotate_single_column_page(
    page,
    page_num,
    detailed_results,
    validation_results,
    start_annotating,
    added_references_summary,
    colors
):
    # Ekstrak warna dari dictionary - PERBAIKAN: gunakan key access seperti multi-column
    PATTENS_BLUE = colors['PATTENS_BLUE']
    INDEXED_RGB = colors['INDEXED_RGB']
    PINK_RGB = colors['PINK_RGB']
    YEAR_RGB = colors['YEAR_RGB']
    
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
            for li, line in enumerate(lines):  # ← PERBAIKAN: Cari dari DEPAN seperti multi-column
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
        cleaned = clean_scimago_title(w[4])
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
            
            # HANYA cek baris SAAT INI, bukan neighbor lines
            key = (bno, lno)
            if key not in by_line:
                return False
            
            current_line_text = ' '.join(by_line[key]['words'])
            quote_chars = ['"', '"', '"', ''', ''', "'"]
            
            # Hitung quotes hanya di baris saat ini
            quote_count = sum(current_line_text.count(ch) for ch in quote_chars)
            
            # Return True HANYA jika ada opening DAN closing quote di baris yang SAMA
            # dan match berada di ANTARA keduanya
            if quote_count >= 2:
                # Cari posisi opening dan closing quotes
                first_quote_pos = -1
                last_quote_pos = -1
                for i, char in enumerate(current_line_text):
                    if char in quote_chars:
                        if first_quote_pos == -1:
                            first_quote_pos = i
                        last_quote_pos = i
                
                # Cek posisi kata match relatif terhadap quotes
                if first_quote_pos != -1 and last_quote_pos != -1 and first_quote_pos != last_quote_pos:
                    try:
                        rel_indices = [by_line[key]['word_indices'].index(idx) for idx in match_word_indices if idx in by_line[key]['word_indices']]
                        if rel_indices:
                            # Estimasi posisi kata dalam string
                            words = by_line[key]['words']
                            match_start_word_idx = min(rel_indices)
                            chars_before_match = sum(len(w) + 1 for w in words[:match_start_word_idx])
                            
                            # Return True hanya jika match berada ANTARA quotes
                            return first_quote_pos < chars_before_match < last_quote_pos
                    except (ValueError, KeyError):
                        pass
            
            return False
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
                        cleaned = clean_scimago_title(nxt)
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
    # Sort results by journal name length (descending) to prioritize longer names
    # This prevents shorter journal names from blocking longer ones
    # Example: "Appl. Soft Comput. J." (4 tokens) before "Soft Comput." (2 tokens)
    sorted_results = sorted(
        detailed_results,
        key=lambda r: len(clean_scimago_title(r.get('parsed_journal', '')).split()),
        reverse=True
    )
    
    for result in sorted_results:
        is_journal_or_indexed = (result.get('reference_type') == 'journal') or result.get('is_indexed')
        if not is_journal_or_indexed: continue
        journal_name = result.get('parsed_journal')
        if not journal_name or len(journal_name) < 2: continue
        search_tokens = clean_scimago_title(journal_name).split()
        if not search_tokens: continue
        plen = len(search_tokens)
        matched = False
        
        logger.info(f"🔍 Single-column: Mencari jurnal '{journal_name}' dengan {plen} tokens")
        
        for i in range(len(expanded_tokens) - max(plen, 1) + 1):
            potential_match_tokens = [t['token'] for t in expanded_tokens[i:i+plen]]
            matched_window_len = None
            if potential_match_tokens == search_tokens: 
                matched_window_len = plen
                logger.info(f"✅ Match found at expanded_token index {i}, window_len={plen}")
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
                logger.info(f"   Match word indices: {match_indices}")
                logger.info(f"   Matched words: {[words_on_page[idx][4] for idx in match_indices if idx < len(words_on_page)]}")
                
                if any(idx in used_word_indices for idx in match_indices):
                    logger.warning(f"   ⚠️ SKIP: Some indices already in used_word_indices")
                    continue
                
                last_matched_word_index = expanded_tokens[i + matched_window_len - 1]['word_index']
                last_word_of_match_text = words_on_page[last_matched_word_index][4]
                
                # MARKER CODE DIHAPUS - Menyebabkan premature marking yang skip matching window berikutnya
                # ref_num = result.get('reference_number')
                # if ref_num and ref_num in markers_by_number:
                #     marker_info = markers_by_number[ref_num]
                #     marker_y, next_marker_y = marker_info['y'], marker_info.get('next_y')
                #     for wi, w in enumerate(words_on_page):
                #         word_y = w[1]
                #         if word_y >= marker_y - 5:
                #             if next_marker_y is None or word_y < next_marker_y - 5:
                #                 used_word_indices.add(wi)
                
                next_word_text = ""
                if last_matched_word_index + 1 < len(words_on_page):
                    next_word_text = words_on_page[last_matched_word_index + 1][4]
                    
                logger.info(f"   Last matched word: '{last_word_of_match_text}', Next word: '{next_word_text}'")

                
                if next_word_text.lower() in ['in', 'proceedings', 'conference', 'symposium', 'report', 'book']:
                    logger.warning(f"   ⚠️ SKIP: Next word '{next_word_text}' in stop list")
                    continue
                if last_word_of_match_text.endswith('.') and next_word_text.lower() == 'in':
                    logger.warning(f"   ⚠️ SKIP: Last word ends with '.' and next is 'in'")
                    continue
                    
                in_quotes = _is_within_quotes(match_indices)
                in_quotes_ext = _is_within_quotes_extended(match_indices)
                
                if in_quotes or in_quotes_ext:
                    logger.warning(f"   ⚠️ SKIP: Within quotes (in_quotes={in_quotes}, extended={in_quotes_ext})")
                    continue
                    
                has_quotes = _has_any_quotes_nearby(match_indices)
                after_quote = _appears_after_closing_quote(match_indices)
                
                # Check if this is likely a continuation from previous page
                # (journal name appears near top of page)
                first_match_word_y = words_on_page[match_indices[0]][1] if match_indices else 999
                is_near_top_of_page = first_match_word_y < 150  # Within first 150 points from top
                
                logger.info(f"   Quote checks: has_nearby={has_quotes}, after_closing={after_quote}, near_top={is_near_top_of_page} (y={first_match_word_y:.1f})")
                
                # Skip quote check if journal name is near top of page (likely continuation)
                if has_quotes and not after_quote and not is_near_top_of_page:
                    logger.warning(f"   ⚠️ SKIP: Has quotes nearby but NOT after closing quote")
                    continue
                
                logger.info(f"   ✅ ALL CHECKS PASSED! Highlighting {len(match_indices)} words")
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
                                     f"Kuartil: {result.get('quartile','N/A')}\n"
                                     f"Link: {result.get('scimago_link','N/A')}")
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
                    # MARKER CODE DIHAPUS - Menyebabkan premature marking di fallback
                    # ref_num = result.get('reference_number')
                    # if ref_num and ref_num in markers_by_number:
                    #     marker_info = markers_by_number[ref_num]
                    #     marker_y, next_marker_y = marker_info['y'], marker_info.get('next_y')
                    #     for wi, w in enumerate(words_on_page):
                    #         word_y = w[1]
                    #         if word_y >= marker_y - 5:
                    #             if next_marker_y is None or word_y < next_marker_y - 5:
                    #                 used_word_indices.add(wi)
                    
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

    def _is_year_in_doi(word_index: int) -> bool:
        """Check if year is part of a DOI identifier"""
        try:
            # Ambil kata saat ini
            current_word = str(words_on_page[word_index][4])
            
            # Cek apakah kata ini sudah mengandung "doi:" atau dimulai dengan "10."
            if 'doi:' in current_word.lower() or current_word.startswith('10.'):
                return True
            
            # Cek beberapa kata sebelumnya untuk melihat apakah ada "doi:" atau pattern DOI
            for offset in range(1, 6):  # Cek hingga 5 kata sebelumnya
                if word_index - offset < 0:
                    break
                prev_word = str(words_on_page[word_index - offset][4]).lower()
                
                # Jika ada kata "doi:" dalam 5 kata sebelumnya
                if 'doi:' in prev_word or 'doi' in prev_word:
                    return True
                
                # Jika ada pattern DOI seperti "10.xxxx/"
                if re.match(r'10\.\d{4,}', prev_word):
                    return True
            
            return False
        except Exception:
            return False

    # Debug: Log semua kata yang mengandung "2019" atau "[16]" untuk troubleshooting
    for wi, w in enumerate(words_on_page):
        word_text = str(w[4])
        bno, lno = w[5], w[6]
        if '2019' in word_text:
            logger.info(f"🔍 Word containing '2019': '{word_text}' at word_index={wi}, block={bno}, line={lno}, page_num={page.number}")
        if '[16]' in word_text:
            logger.info(f"🔍 Found reference marker '[16]': '{word_text}' at word_index={wi}, block={bno}, line={lno}, page_num={page.number}")
    
    highlighted_years_per_reference = {}
    for wi, w in enumerate(words_on_page):
        word_text = str(w[4])
        for match in year_pattern.finditer(word_text):
            year_str, year_int = match.group(0), int(match.group(0))
            
            # Debug logging untuk year detection
            is_year_in_quotes = _is_year_in_quotes(wi)
            is_recent = year_int >= min_year
            
            # Log semua tahun yang ditemukan untuk debugging
            if year_int == 2019:
                logger.info(f"🔍 FOUND Year {year_str} (word: '{word_text}', recent: {is_recent}, in_quotes: {is_year_in_quotes})")
            
            if is_recent:
                logger.info(f"📅 Year {year_str} SKIP: Recent (>= {min_year})")
                continue
            
            if is_year_in_quotes:
                logger.info(f"📅 Year {year_str} SKIP: In quotes (word: '{word_text}')")
                continue
            
            # Cek apakah tahun ini bagian dari DOI
            if _is_year_in_doi(wi):
                logger.info(f"📅 Year {year_str} SKIP: Part of DOI (word: '{word_text}')")
                continue
            
            word_rect = fitz.Rect(w[:4])
            if not _is_in_reference_region(word_rect): 
                logger.info(f"📅 Year {year_str} SKIP: Not in reference region (y={word_rect.y0:.1f})")
                continue
            
            try:
                current_bno, current_lno = w[5], w[6]
                current_key = (current_bno, current_lno)
                is_part_of_reference_entry = False
                
                if by_line.get(current_key):
                    # Cek baris saat ini
                    if _is_line_a_reference_entry(' '.join(by_line[current_key]['words'])): 
                        is_part_of_reference_entry = True
                    else:
                        # Cek hingga 5 baris sebelumnya dalam block yang sama
                        for offset in range(1, 6):
                            prev_key = (current_bno, current_lno - offset)
                            if by_line.get(prev_key) and _is_line_a_reference_entry(' '.join(by_line[prev_key]['words'])): 
                                is_part_of_reference_entry = True
                                break
                        
                        # Jika belum ketemu, cek juga block sebelumnya (untuk multi-block references)
                        if not is_part_of_reference_entry:
                            for block_offset in range(1, 4):  # Cek 3 block sebelumnya
                                prev_block_no = current_bno - block_offset
                                # Cek semua line di block sebelumnya
                                for line_no in range(10):  # Max 10 lines per block
                                    prev_key = (prev_block_no, line_no)
                                    if by_line.get(prev_key) and _is_line_a_reference_entry(' '.join(by_line[prev_key]['words'])):
                                        is_part_of_reference_entry = True
                                        break
                                if is_part_of_reference_entry:
                                    break
                
                if not is_part_of_reference_entry:
                    logger.info(f"📅 Year {year_str} SKIP: Not part of reference entry (word: '{word_text}')")
                    continue
            except Exception as e:
                logger.warning(f"📅 Year {year_str} SKIP: Exception in reference entry check - {e}")
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
                
                logger.info(f"✅ Year {year_str} HIGHLIGHTED (word: '{word_text}', min_year: {min_year})")
                
                note_text = f"Tahun: {year_str}\nMinimal: {min_year}\nStatus: Outdated"
                note = page.add_text_annot(fitz.Point(year_rect.x0, max(0, year_rect.y0 - 15)), note_text)
                note.set_info(title="Tahun Outdated")
                note.set_colors(stroke=YEAR_RGB, fill=YEAR_RGB)
                note.update()
            except Exception as e:
                logger.error(f"❌ Error highlighting tahun {year_str}: {e}")

    return start_annotating, added_references_summary, current_page_heading_rects