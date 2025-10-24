"""
Script untuk restore HANYA multi-column dari backup
Keep single-column fixes intact
"""

# Baca backup dan current
with open('app/services.py.backup', 'r', encoding='utf-8') as f:
    backup_lines = f.readlines()

with open('app/services.py', 'r', encoding='utf-8') as f:
    current_lines = f.readlines()

print("Restoring multi-column sections from backup...")
print("=" * 70)

# AREA 1: Multi-column fallback (around line 966)
# Cari baris yang di-comment di area multi-column
restored_count = 0

# Multi-column adalah fungsi PERTAMA (_annotate_multi_column_page)
# Single-column adalah fungsi KEDUA (_annotate_single_column_page)

# Strategi: Restore line 900-980 (multi-column fallback area)
for i in range(900, 980):
    if i < len(backup_lines) and i < len(current_lines):
        # Jika current di-comment tapi backup tidak, restore
        if current_lines[i].strip().startswith('# ref_num') and not backup_lines[i].strip().startswith('#'):
            print(f"Line {i+1}: Restoring from backup")
            current_lines[i] = backup_lines[i]
            restored_count += 1
        elif current_lines[i].strip().startswith('# if ref_num') and not backup_lines[i].strip().startswith('#'):
            print(f"Line {i+1}: Restoring from backup")
            current_lines[i] = backup_lines[i]
            restored_count += 1
        elif current_lines[i].strip().startswith('# marker_info') and not backup_lines[i].strip().startswith('#'):
            print(f"Line {i+1}: Restoring from backup")
            current_lines[i] = backup_lines[i]
            restored_count += 1
        elif current_lines[i].strip().startswith('# marker_y') and not backup_lines[i].strip().startswith('#'):
            print(f"Line {i+1}: Restoring from backup")
            current_lines[i] = backup_lines[i]
            restored_count += 1
        elif current_lines[i].strip().startswith('# for wi, w in enumerate') and not backup_lines[i].strip().startswith('#'):
            print(f"Line {i+1}: Restoring from backup")
            current_lines[i] = backup_lines[i]
            restored_count += 1
        elif current_lines[i].strip().startswith('# word_y') and not backup_lines[i].strip().startswith('#'):
            print(f"Line {i+1}: Restoring from backup")
            current_lines[i] = backup_lines[i]
            restored_count += 1
        elif current_lines[i].strip().startswith('# if word_y') and not backup_lines[i].strip().startswith('#'):
            print(f"Line {i+1}: Restoring from backup")
            current_lines[i] = backup_lines[i]
            restored_count += 1
        elif current_lines[i].strip().startswith('# if next_marker_y') and not backup_lines[i].strip().startswith('#'):
            print(f"Line {i+1}: Restoring from backup")
            current_lines[i] = backup_lines[i]
            restored_count += 1
        elif current_lines[i].strip().startswith('# used_word_indices.add') and not backup_lines[i].strip().startswith('#'):
            print(f"Line {i+1}: Restoring from backup")
            current_lines[i] = backup_lines[i]
            restored_count += 1

print("=" * 70)
print(f"Multi-column: {restored_count} lines restored")
print(f"Single-column: KEPT (not touched)")

# Write
with open('app/services.py', 'w', encoding='utf-8') as f:
    f.writelines(current_lines)

print("\n✅ Done! Multi-column restored, single-column fixes preserved.")
