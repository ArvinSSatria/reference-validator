"""
Script untuk menghapus marker-based marking yang bermasalah
Akan comment out baris 966-975 dan 1472-1481 (estimasi)
"""
import re

file_path = "c:/xampp/htdocs/pemrosesan-referensi-otomatis-terbaru/app/services.py"

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Backup
with open(file_path + '.backup', 'w', encoding='utf-8') as f:
    f.writelines(lines)

# Find and comment out the problematic code blocks
# Pattern: ref_num = result.get('reference_number') followed by marker_y logic

modified = False
i = 0
while i < len(lines):
    line = lines[i]
    
    # Detect the problematic pattern  
    if 'ref_num = result.get' in line and 'reference_number' in line:
        # Check if next line has the marker logic
        if i + 1 < len(lines) and 'if ref_num and ref_num in markers_by_number:' in lines[i+1]:
            print(f"Found problematic code at line {i+1}")
            
            # Comment out from ref_num to the closing of used_word_indices.add(wi)
            # Typically 10 lines
            j = i
            while j < min(i + 12, len(lines)):
                # Stop before "for wi in unique_wi"
                if 'for wi in unique_wi: used_word_indices.add(wi)' in lines[j]:
                    break
                    
                # Comment out
                if not lines[j].strip().startswith('#'):
                    lines[j] = '                    # ' + lines[j].lstrip()
                    modified = True
                    print(f"  Line {j+1}: {lines[j][:60]}...")
                    
                j += 1
            
            # Skip processed lines
            i = j
    
    i += 1

if modified:
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"\n✅ File updated successfully!")
    print(f"📄 Backup saved to: {file_path}.backup")
else:
    print("❌ No changes needed")
