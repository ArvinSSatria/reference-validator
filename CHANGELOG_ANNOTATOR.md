# Changelog - PDF Annotator Refactoring

## Update 2 - 29 Oktober 2025 (18:50)

### Bug Fix: Highlight Semua Tipe Referensi

**Problem**: Book dan tipe referensi lainnya tidak ter-highlight di PDF
- Referensi #2 (Blumberg - Book) tidak ter-highlight
- Referensi #11 (Iphofen - Book) tidak ter-highlight
- Hanya journal yang ter-highlight

**Root Cause**: Filter yang terlalu ketat di annotator
```python
is_journal_or_indexed = (result.get('reference_type') == 'journal') or result.get('is_indexed')
if not is_journal_or_indexed:
    continue  # SKIP BOOK! ❌
```

**Solution**: Highlight SEMUA tipe referensi dengan warna berbeda

#### Skema Warna Baru:
1. 🟢 **Hijau (INDEXED_RGB)**: Journal terindeks di Scimago
2. 🔴 **Pink (PINK_RGB)**: Journal TIDAK terindeks
3. 🟡 **Kuning (YEAR_RGB)**: Book, Conference, Website, dan tipe lainnya

#### Perubahan di `pdf_annotator.py`:

1. **Hapus filter tipe referensi**:
   ```python
   # BEFORE: Hanya journal
   is_journal_or_indexed = (result.get('reference_type') == 'journal') or result.get('is_indexed')
   if not is_journal_or_indexed:
       continue
   
   # AFTER: Semua tipe referensi
   for result in sorted_results:
       # Process ALL reference types
   ```

2. **Update logika warna**:
   ```python
   if is_indexed:
       color = INDEXED_RGB  # Hijau untuk yang terindeks
   elif ref_type == 'journal':
       color = PINK_RGB  # Pink untuk journal tidak terindeks
   else:
       color = YEAR_RGB  # Kuning untuk book, conference, website, dll
   ```

3. **Update summary annotation**:
   - Tambahkan breakdown: Jurnal, Buku, Konferensi, Lainnya
   - Tambahkan legend warna

#### Expected Result:
- ✅ Blumberg (Book) → Highlight **KUNING**
- ✅ Hansen (Journal Q1) → Highlight **HIJAU**
- ✅ Iphofen (Book) → Highlight **KUNING**

---

## Tanggal: 29 Oktober 2025

### Perubahan Utama

#### 1. **File Baru: `app/services/pdf_annotator.py`**
   - Menggabungkan logika dari `pdf_annotator_single.py` dan `pdf_annotator_multi.py` menjadi satu file unified annotator
   - Mengadopsi pendekatan dari `core.py` dengan strategi pencarian bertingkat untuk menghindari highlight yang tumpang tindih
   - **Fitur Utama:**
     - `find_references_section_in_text()`: Mencari bagian referensi dengan smart heuristics (validasi tahun, DOI, author pattern)
     - `annotate_pdf_page()`: Unified annotator untuk semua jenis layout (single & multi-column)
     - `group_rects_by_proximity()`: Mengelompokkan rects yang terpotong multi-baris menjadi satu grup
     - `normalize_text_for_search()`: Normalisasi teks untuk pencarian yang lebih fleksibel

#### 2. **Strategi Pencarian Bertingkat**
   Menggunakan 5 strategi pencarian untuk menemukan teks referensi di PDF:
   
   ```
   STRATEGI 1: Teks lengkap (paling akurat)
   STRATEGI 2: 150 karakter pertama (normalized)
   STRATEGI 3: 80 karakter pertama (normalized)
   STRATEGI 4: 40 karakter pertama (normalized)
   STRATEGI 5: 30 karakter pertama (normalized)
   ```
   
   **Keuntungan:**
   - Menghindari highlight yang tumpang tindih
   - Prioritas pada highlight yang paling lengkap (berdasarkan total area)
   - Fallback mechanism jika teks tidak ditemukan dengan exact match

#### 3. **Update `app/services/pdf_service.py`**
   - Menghapus deteksi layout (tidak lagi membedakan single vs multi-column)
   - Menggunakan unified annotator `annotate_pdf_page()`
   - Mencari keyword "REFERENCES" / "DAFTAR PUSTAKA" sekali di awal untuk efisiensi
   
   **Sebelum:**
   ```python
   layout_type = detect_layout(page)
   if layout_type == 'multi_column':
       handler_function = annotate_multi_column_page
   else:
       handler_function = annotate_single_column_page
   ```
   
   **Sesudah:**
   ```python
   # Cari keyword references section sekali di awal
   found_line_num, found_keyword = find_references_section_in_text(full_text)
   
   # Panggil unified annotator untuk semua halaman
   annotate_pdf_page(page, ...)
   ```

#### 4. **Update `app/services/ai_service.py`**
   - Menambahkan field `full_reference` ke dalam prompt AI
   - Field ini berisi teks referensi asli lengkap untuk keperluan highlighting di PDF
   
   **Prompt Update:**
   ```json
   {
       "reference_number": 1,
       "full_reference": "<TEKS REFERENSI LENGKAP SEPERTI YANG DIBERIKAN>",
       "parsed_authors": ["Penulis 1"],
       ...
   }
   ```

#### 5. **Update `app/services/validation_service.py`**
   - Menambahkan field `full_reference` ke dalam `detailed_results`
   - Field ini di-pass dari AI response untuk digunakan oleh annotator
   
   **Detail Results Structure:**
   ```python
   {
       "reference_number": 1,
       "reference_text": "...",  # Original text dari references_list
       "full_reference": "...",   # BARU: Dari AI response untuk highlighting
       "status": "valid",
       ...
   }
   ```

### Keuntungan Refactoring

1. **Kode Lebih Sederhana**: Tidak ada lagi duplikasi logic antara single dan multi-column
2. **Highlight Lebih Akurat**: Strategi pencarian bertingkat mengurangi false positive
3. **Menghindari Overlap**: Algoritma prioritas area mencegah highlight tumpang tindih
4. **Multi-baris Support**: Group rects by proximity untuk nama jurnal yang terpotong ke beberapa baris
5. **Smart References Detection**: Heuristics yang lebih cerdas untuk menemukan bagian referensi (validasi tahun, DOI, author pattern)

### File yang Tidak Lagi Digunakan

File-file berikut masih ada tetapi **TIDAK LAGI DIPANGGIL** oleh `pdf_service.py`:

- `app/services/pdf_annotator_single.py` (replaced by `pdf_annotator.py`)
- `app/services/pdf_annotator_multi.py` (replaced by `pdf_annotator.py`)
- `app/utils/layout_detector.py` (tidak lagi perlu deteksi layout)

> **Note**: File-file ini bisa dihapus jika sudah dipastikan tidak ada kode lain yang menggunakannya.

### Testing Checklist

- [ ] Test dengan PDF single-column
- [ ] Test dengan PDF multi-column
- [ ] Test dengan PDF yang punya nama jurnal panjang (terpotong multi-baris)
- [ ] Test dengan PDF yang tidak punya keyword "REFERENCES" eksplisit
- [ ] Test dengan PDF yang punya banyak referensi (>50)
- [ ] Verify highlight tidak tumpang tindih
- [ ] Verify summary annotation muncul di keyword "REFERENCES"
- [ ] Verify tahun outdated di-highlight dengan warna merah

### Breaking Changes

**TIDAK ADA** - Refactoring ini backward compatible. API dan response format tetap sama.

### Migration Guide

Tidak ada migration yang diperlukan. Cukup pull changes dan restart aplikasi.

### Future Improvements

1. **Cache Full Text**: Simpan full_text di memory untuk menghindari re-extract di setiap halaman
2. **Parallel Processing**: Process multiple pages secara parallel untuk PDF besar
3. **Better Error Handling**: Tambahkan fallback jika AI tidak return `full_reference`
4. **Performance Metrics**: Log waktu eksekusi untuk setiap strategi pencarian
