"""
DEEP DEBUG: Analisis kenapa highlight masih tidak lengkap
"""

from app.services import _clean_scimago_title

# Test cases dari screenshot
test_cases = [
    {
        "ref_num": 31,
        "journal": "Elinvo (Electronics, Informatics, and Vocational Education)",
        "expected_tokens": "elinvo electronics informatics and vocational education"
    },
    {
        "ref_num": 32,
        "journal": "ACM Comput Surv",
        "expected_tokens": "acm comput surv"
    },
    {
        "ref_num": 33,
        "journal": "International Journal of Software Engineering and its Applications",
        "expected_tokens": "international journal of software engineering and its applications"
    }
]

print("=" * 80)
print("ANALISIS TOKENISASI NAMA JURNAL")
print("=" * 80)

for case in test_cases:
    print(f"\n[{case['ref_num']}] {case['journal']}")
    print("-" * 80)
    
    cleaned = _clean_scimago_title(case['journal'])
    tokens = cleaned.split()
    
    print(f"📝 Original: {case['journal']}")
    print(f"🧹 Cleaned:  {cleaned}")
    print(f"🔢 Tokens:   {tokens}")
    print(f"📊 Count:    {len(tokens)} tokens")
    print(f"✅ Expected: {case['expected_tokens']}")
    print(f"🔍 Match:    {cleaned == case['expected_tokens']}")
    
    # Analisis karakter khusus
    special_chars = set()
    for char in case['journal']:
        if not char.isalnum() and not char.isspace():
            special_chars.add(char)
    
    if special_chars:
        print(f"⚠️  Special chars found: {special_chars}")

print("\n" + "=" * 80)
print("KESIMPULAN:")
print("=" * 80)
print("Jika tokenisasi benar, masalah ada di:")
print("1. Logika matching window (sliding window tidak jalan)")
print("2. Quote detection yang terlalu agresif")
print("3. Stop word detection")
print("4. used_word_indices masih terisi prematur")
