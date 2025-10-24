"""
Script untuk menghapus marker code yang bermasalah di fungsi _annotate_single_column_page
"""

import re

file_path = r'c:\xampp\htdocs\pemrosesan-referensi-otomatis-terbaru\app\services.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern untuk mencari dan mengganti marker code di single-column (line ~1486)
# Cari pattern di dalam fallback section setelah "if not matched:"
pattern = r'(if not matched:.*?cand_indices, first_rect = _fallback_highlight_journal_after_quote.*?note\.update\(\)\s*)(ref_num = result\.get\(\'reference_number\'\)\s+if ref_num and ref_num in markers_by_number:.*?used_word_indices\.add\(wi\)\s+)(for wi in unique_wi: used_word_indices\.add\(wi\))'

replacement = r'\1# MARKER CODE DIHAPUS - Menyebabkan premature marking di fallback\n                    # ref_num = result.get(\'reference_number\')\n                    # if ref_num and ref_num in markers_by_number:\n                    #     marker_info = markers_by_number[ref_num]\n                    #     marker_y, next_marker_y = marker_info[\'y\'], marker_info.get(\'next_y\')\n                    #     for wi, w in enumerate(words_on_page):\n                    #         word_y = w[1]\n                    #         if word_y >= marker_y - 5:\n                    #             if next_marker_y is None or word_y < next_marker_y - 5:\n                    #                 used_word_indices.add(wi)\n                    \n                    \3'

# Lakukan replacement dengan DOTALL flag untuk multiline
new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

# Cek apakah ada perubahan
if new_content != content:
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("✅ Marker code di fallback section berhasil dihapus!")
    
    # Hitung berapa banyak marker code yang masih aktif
    active_markers = len(re.findall(r'^\s{16,20}ref_num = result\.get\(\'reference_number\'\)\s*$', new_content, re.MULTILINE))
    commented_markers = len(re.findall(r'^\s{16,20}# ref_num = result\.get\(\'reference_number\'\)\s*$', new_content, re.MULTILINE))
    
    print(f"📊 Status marker code:")
    print(f"   - Aktif (tidak dicomment): {active_markers}")
    print(f"   - Dinonaktifkan (commented): {commented_markers}")
else:
    print("⚠️ Tidak ada perubahan yang dilakukan")
