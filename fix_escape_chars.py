"""
Script untuk memperbaiki escape characters di marker code comments
"""

file_path = r'c:\xampp\htdocs\pemrosesan-referensi-otomatis-terbaru\app\services.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix escaped quotes dalam comment
content = content.replace(r"# ref_num = result.get(\'reference_number\')", "# ref_num = result.get('reference_number')")
content = content.replace(r"marker_info[\'y\'], marker_info.get(\'next_y\')", "marker_info['y'], marker_info.get('next_y')")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Escape characters dalam comment berhasil diperbaiki!")
