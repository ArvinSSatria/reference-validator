"""
Debug script untuk memeriksa kenapa highlight tidak full
"""
import re

# Simulasi referensi dari gambar
reference_text = '''M. E. Khan, "Different approaches to white box testing technique for finding errors," International Journal of Software Engineering and its Applications, vol. 5, no. 3, pp. 1–14, 2011, doi: 10.5121/ijsea.2011.2404.'''

# Fungsi cleaning dari services.py
def _clean_scimago_title(title):
    if not isinstance(title, str): 
        return ""
    s = title.lower()
    s = re.sub(r'[^a-z0-9]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

# Target jurnal
journal_name = "International Journal of Software Engineering and its Applications"
search_tokens = _clean_scimago_title(journal_name).split()

print("="*70)
print("TARGET JURNAL:")
print(f"  Nama: {journal_name}")
print(f"  Search tokens: {search_tokens}")
print(f"  Jumlah tokens: {len(search_tokens)}")
print()

# Simulasi words dari PDF
words_simulation = [
    "M.", "E.", "Khan,", '"Different', "approaches", "to", "white", "box",
    "testing", "technique", "for", "finding", 'errors,"',  # ← Closing quote di sini
    "International", "Journal", "of", "Software", "Engineering",  # ← Highlight berhenti di sini?
    "and", "its", "Applications,",  # ← Tidak ter-highlight
    "vol.", "5,", "no.", "3,", "pp.", "1–14,", "2011,"
]

print("WORDS SIMULATION:")
for idx, word in enumerate(words_simulation):
    print(f"  [{idx:2d}] {word}")
print()

# Tokenisasi
expanded_tokens = []
for wi, word in enumerate(words_simulation):
    cleaned = _clean_scimago_title(word)
    if cleaned:
        for part in cleaned.split():
            expanded_tokens.append({
                'token': part,
                'word_index': wi,
                'original_word': word
            })

print("EXPANDED TOKENS:")
for idx, et in enumerate(expanded_tokens):
    print(f"  [{idx:2d}] token='{et['token']}' word_idx={et['word_index']} orig='{et['original_word']}'")
print()

# Cari matching window
print("="*70)
print("MENCARI MATCHING WINDOW:")
plen = len(search_tokens)

for i in range(len(expanded_tokens) - plen + 1):
    potential_match = [t['token'] for t in expanded_tokens[i:i+plen]]
    
    if potential_match == search_tokens:
        print(f"\n✅ FOUND MATCH at index {i}!")
        print(f"  Match tokens: {potential_match}")
        print(f"  Match window: {i} to {i+plen-1}")
        
        match_indices = [expanded_tokens[i+k]['word_index'] for k in range(plen)]
        print(f"  Word indices: {match_indices}")
        
        matched_words = [words_simulation[idx] for idx in match_indices]
        print(f"  Matched words: {matched_words}")
        
        # Cek kondisi yang mungkin menyebabkan skip
        print("\n  CHECKING CONDITIONS:")
        
        # 1. Cek next word
        last_word_index = match_indices[-1]
        next_word_text = words_simulation[last_word_index + 1] if last_word_index + 1 < len(words_simulation) else ""
        print(f"    1. Next word after match: '{next_word_text}'")
        print(f"       Is in ['in', 'proceedings', ...]? {next_word_text.lower() in ['in', 'proceedings', 'conference', 'symposium', 'report', 'book']}")
        
        # 2. Cek quotes nearby
        first_word_index = match_indices[0]
        # Cari quotes di sekitar (3 kata sebelum dan sesudah)
        context_start = max(0, first_word_index - 3)
        context_end = min(len(words_simulation), last_word_index + 4)
        context_words = words_simulation[context_start:context_end]
        
        print(f"    2. Context words: {context_words}")
        
        has_quotes = any('"' in w or '"' in w or '"' in w or "'" in w or "'" in w for w in context_words)
        print(f"       Has quotes nearby? {has_quotes}")
        
        # Cek posisi closing quote
        closing_quote_before = False
        for idx in range(first_word_index - 1, max(0, first_word_index - 10), -1):
            if '"' in words_simulation[idx] or '"' in words_simulation[idx] or 'errors,"' in words_simulation[idx]:
                closing_quote_before = True
                print(f"       Closing quote found at word index {idx}: '{words_simulation[idx]}'")
                break
        
        print(f"       Appears after closing quote? {closing_quote_before}")
        
        break

print("\n" + "="*70)
print("ANALISIS:")
print("""
Dari hasil di atas, kita bisa lihat:

1. Matching window SEHARUSNYA menemukan semua 8 token
2. JIKA matching ditemukan tapi di-SKIP, kemungkinan penyebabnya:
   
   a) Kondisi quotes detection yang terlalu ketat:
      - _has_any_quotes_nearby() return TRUE (karena ada closing quote sebelumnya)
      - _appears_after_closing_quote() mungkin return FALSE
      - Kombinasi: has_quotes AND NOT after_quote = SKIP! ❌
      
   b) Atau matching window tidak full karena:
      - Word indices sudah ter-mark di used_word_indices
      - Ada line break di tengah nama jurnal
      
SOLUSI:
   - Periksa apakah logika quote detection terlalu agresif
   - Pastikan matching window mencakup SEMUA 8 token
   - Debug dengan logging di fungsi asli
""")
