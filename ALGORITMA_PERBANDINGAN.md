# 🔄 ANALISIS ALGORITMA: Perbandingan Multi-Column vs Single-Column

## 📄 Contoh Referensi yang Diproses:
```
M. E. Khan, "Different approaches to white box testing technique for finding errors," 
International Journal of Software Engineering and its Applications, vol. 5, no. 3, 
pp. 1–14, 2011, doi: 10.5121/ijsea.2011.2404.
```

---

## 🔵 ALGORITMA MULTI-COLUMN (BENAR SEJAK AWAL)

### **FASE 1: PERSIAPAN DATA**
```
START
│
├─ Input: page (PDF page object), detailed_results, colors
│
├─ Ekstrak words dari halaman
│   words_on_page = page.get_text("words")
│   → Hasil: [("M.", x0, y0, x1, y1, block, line), 
│              ("E.", x0, y0, x1, y1, block, line),
│              ("Khan,", x0, y0, x1, y1, block, line), ...]
│
├─ Bangun struktur by_line (group words by block & line number)
│   by_line = {
│       (0, 15): {y: 450.2, words: ["M.", "E.", "Khan,", "\"Different", ...], ...},
│       (0, 16): {y: 462.8, words: ["International", "Journal", "of", ...], ...},
│       ...
│   }
│
└─ Sort lines by Y coordinate (top → bottom)
    lines = sorted(by_line.values(), key=lambda d: d['y'])
```

---

### **FASE 2: DETEKSI HEADING "REFERENCES" / "DAFTAR PUSTAKA"**

```
┌─────────────────────────────────────────────────┐
│  Loop: for li, line in enumerate(lines)         │  ← DARI DEPAN KE BELAKANG
│  (Mulai dari baris PERTAMA halaman)             │
└─────────────────────────────────────────────────┘
          │
          ├─ Line 0: "ABSTRACT" → Skip
          ├─ Line 1: "This paper..." → Skip
          ├─ Line 2: "..."  → Skip
          │  ...
          ├─ Line 87: "REFERENCES" ✅
          │    │
          │    ├─ Normalize: "references"
          │    ├─ Match dengan heading_tokens? YES
          │    ├─ Cek konteks 8 baris berikutnya:
          │    │   Line 88: "[1] M. E. Khan, \"Different approaches..."
          │    │   → _looks_like_reference_line() = TRUE ✅
          │    │
          │    └─ SET: start_annotating = TRUE
          │         current_page_heading_rects = [Rect of "REFERENCES"]
          │         BREAK loop
          │
          └─ HASIL: start_annotating = TRUE ✅
```

**✅ Kesimpulan Fase 2:** Heading ditemukan dengan benar!

---

### **FASE 3: HIGHLIGHT RINGKASAN (SUMMARY NOTE)**

```
IF start_annotating == TRUE AND not added_references_summary:
    │
    ├─ Highlight heading "REFERENCES" dengan warna biru
    │
    ├─ Buat summary note:
    │   "Total Referensi: 25
    │    Artikel Jurnal: 20 (80%)
    │    Terindeks SJR: 15 (60%)
    │    Validitas Tahun: 22 dari 25
    │    Kuartil: Q1:5 | Q2:7 | Q3:3 | Q4:0"
    │
    └─ SET: added_references_summary = TRUE
```

---

### **FASE 4: TOKENISASI UNTUK PENCARIAN JURNAL**

```
expanded_tokens = []

For each word in words_on_page:
    │
    ├─ Clean word: "International" → "international"
    ├─ Split into tokens: ["international"]
    └─ Store: {token: "international", word_index: 45, rect: Rect(...)}

Hasil expanded_tokens:
[
    {token: "m", word_index: 0, rect: Rect(...)},
    {token: "e", word_index: 1, rect: Rect(...)},
    {token: "khan", word_index: 2, rect: Rect(...)},
    {token: "different", word_index: 4, rect: Rect(...)},
    ...
    {token: "international", word_index: 45, rect: Rect(...)},
    {token: "journal", word_index: 46, rect: Rect(...)},
    {token: "of", word_index: 47, rect: Rect(...)},
    {token: "software", word_index: 48, rect: Rect(...)},
    {token: "engineering", word_index: 49, rect: Rect(...)},
    {token: "and", word_index: 50, rect: Rect(...)},
    {token: "its", word_index: 51, rect: Rect(...)},
    {token: "applications", word_index: 52, rect: Rect(...)},
    ...
]
```

---

### **FASE 5: PENCARIAN & HIGHLIGHTING NAMA JURNAL**

```
Target: "International Journal of Software Engineering and its Applications"
Search tokens: ["international", "journal", "of", "software", "engineering", "and", "its", "applications"]

┌─────────────────────────────────────────────────┐
│  Loop: Sliding window di expanded_tokens        │
└─────────────────────────────────────────────────┘
          │
          ├─ Window di index 0: ["m", "e", "khan", ...] → NO MATCH
          ├─ Window di index 1: ["e", "khan", ...] → NO MATCH
          │  ...
          ├─ Window di index 45: ["international", "journal", "of", "software", 
          │                        "engineering", "and", "its", "applications"] ✅
          │    │
          │    ├─ MATCH! potential_match_tokens == search_tokens
          │    ├─ matched_window_len = 8
          │    ├─ match_indices = [45, 46, 47, 48, 49, 50, 51, 52]
          │    │
          │    ├─ Validasi:
          │    │   ├─ Cek apakah sudah digunakan? NO ✅
          │    │   ├─ Cek next word: "vol." → Not in ['in', 'proceedings', ...] ✅
          │    │   ├─ Cek dalam quotes? NO ✅ (ini SETELAH closing quote)
          │    │   └─ Cek nearby quotes? YES, tapi appears_after_closing_quote = TRUE ✅
          │    │
          │    ├─ Mark words as used: used_word_indices.update([45-52])
          │    │
          │    └─ HIGHLIGHT:
          │         ├─ Color: INDEXED_RGB (hijau) atau PINK_RGB (pink)
          │         │   (tergantung is_indexed dari database Scimago)
          │         │
          │         ├─ Highlight rectangles untuk kata:
          │         │   ["International", "Journal", "of", "Software", 
          │         │    "Engineering", "and", "its", "Applications"]
          │         │
          │         └─ Add annotation note:
          │              "Jurnal: International Journal of Software Engineering and its Applications
          │               Tipe: journal
          │               Kuartil: Q3"
          │
          └─ matched = TRUE, BREAK loop
```

**✅ Hasil:** Nama jurnal **berhasil di-highlight** dengan warna hijau/pink dan tooltip info!

---

### **FASE 6: HIGHLIGHT TAHUN OUTDATED**

```
Target: Cari tahun < (current_year - year_range)
Contoh: current_year=2025, year_range=5 → min_year=2020
Pattern: \b(19\d{2}|20\d{2})\b

Loop through all words:
    │
    ├─ Word: "2011" (dari referensi contoh)
    │    │
    │    ├─ Match pattern? YES ✅
    │    ├─ year_int = 2011
    │    ├─ year_int >= min_year? NO (2011 < 2020) ❌
    │    ├─ Is in quotes? NO ✅
    │    ├─ Is in reference region? YES ✅ (Y > heading_Y)
    │    ├─ Is part of reference entry? YES ✅
    │    │
    │    └─ HIGHLIGHT:
    │         ├─ Color: YEAR_RGB (merah)
    │         ├─ Highlight "2011"
    │         └─ Add note: "Tahun: 2011\nMinimal: 2020\nStatus: Outdated"
    │
    └─ Continue untuk tahun lainnya...
```

**✅ Hasil:** Tahun **"2011" di-highlight merah** dengan peringatan outdated!

---

### **OUTPUT AKHIR MULTI-COLUMN:**
```
✅ Heading "REFERENCES" → Highlighted biru + summary note
✅ Nama jurnal "International Journal of..." → Highlighted hijau/pink + tooltip
✅ Tahun "2011" → Highlighted merah + warning
```

---

---

## 🔴 ALGORITMA SINGLE-COLUMN (SEBELUM PERBAIKAN - SALAH)

### **FASE 1: PERSIAPAN DATA**
```
START
│
├─ Input: page, detailed_results, colors
│
├─ Ekstrak warna (MASALAH #1):
│   PATTENS_BLUE, INDEXED_RGB, PINK_RGB, YEAR_RGB = colors.values() ⚠️
│   → Bisa salah jika urutan keys berubah!
│
├─ Ekstrak words: words_on_page = page.get_text("words")
│
├─ Bangun by_line structure (sama seperti multi-column)
│
└─ Sort lines (MASALAH #2):
    lines = sorted(by_line.values(), key=lambda d: d['y'])
    lines = sorted(by_line.values(), key=lambda d: d['y'])  ← DUPLIKAT! ⚠️
```

---

### **FASE 2: DETEKSI HEADING (MASALAH UTAMA #3)**

```
┌─────────────────────────────────────────────────┐
│  Loop: for li in range(len(lines)-1, -1, -1)    │  ← DARI BELAKANG KE DEPAN! ❌
│  (Mulai dari baris TERAKHIR halaman)            │
└─────────────────────────────────────────────────┘
          │
          ├─ Line 200: "Page 10" → Skip
          ├─ Line 199: "Acknowledgments" → Skip
          ├─ Line 198: "We thank..." → Skip
          │  ...
          ├─ Line 150: "doi: 10.1234/..." → Skip
          ├─ Line 149: "...applications, vol. 5..." → Skip
          │  ...
          ├─ Line 88: "[1] M. E. Khan, \"Different..." 
          │    │
          │    ├─ Contains "references"? NO
          │    └─ Skip
          │
          ├─ Line 87: "REFERENCES" 
          │    │
          │    ├─ Normalize: "references"
          │    ├─ Match dengan heading_tokens? YES
          │    ├─ Cek konteks 8 baris berikutnya:
          │    │   
          │    │   MASALAH: "berikutnya" dalam loop mundur = baris di ATAS!
          │    │   Line 88 (seharusnya di bawah) tidak terdeteksi dengan benar
          │    │   karena logika range(li+1, ...) tetap mengacu forward
          │    │
          │    └─ _looks_like_reference_line() bisa FALSE ❌
          │         (tergantung bagaimana baris 88-95 dibaca)
          │
          └─ HASIL: Kemungkinan besar start_annotating = FALSE ❌

ATAU (Skenario Alternatif - Lebih Buruk):
          │
          ├─ Line 165: "...see our references for more details" 
          │    │
          │    ├─ Contains "references" dalam kalimat biasa!
          │    ├─ Normalize: "see our references for more details"
          │    ├─ Match? PARTIAL atau FALSE positive
          │    └─ Salah mendeteksi heading! ❌
          │
          └─ HASIL: start_annotating = TRUE tapi di tempat SALAH ❌
```

**❌ Kesimpulan Fase 2:** 
- **Skenario A:** Heading tidak ditemukan → `start_annotating = FALSE`
- **Skenario B:** Heading salah terdeteksi → `start_annotating = TRUE` tapi di lokasi salah

---

### **FASE 3: HIGHLIGHT RINGKASAN**

```
IF start_annotating == TRUE:  ← Tapi start_annotating = FALSE! ❌
    └─ SKIP! Tidak dijalankan ❌
    
ATAU (Jika false positive):
    └─ Highlight di tempat SALAH ❌
```

**❌ Hasil:** Summary note TIDAK ditambahkan atau di tempat salah!

---

### **FASE 4: TOKENISASI**
```
(Sama seperti multi-column - tidak ada masalah)
```

---

### **FASE 5: PENCARIAN & HIGHLIGHTING NAMA JURNAL**

```
IF start_annotating == FALSE:  ← Problem dari Fase 2! ❌
    │
    └─ Loop highlight TIDAK dilewati, TAPI:
        │
        └─ Fungsi _is_in_reference_region() akan return FALSE
            karena current_page_heading_rects = [] (kosong)
            
Result: 
    └─ Nama jurnal TIDAK di-highlight! ❌
        (Atau jika ada false positive di Fase 2, highlight di area salah)
```

**❌ Hasil:** Nama jurnal **"International Journal of..."** **TIDAK DI-HIGHLIGHT**!

---

### **FASE 6: HIGHLIGHT TAHUN OUTDATED**

```
Loop through words untuk "2011":
    │
    ├─ Match pattern? YES ✅
    ├─ year_int = 2011 < min_year? YES ✅
    ├─ Is in reference region?
    │    │
    │    └─ _is_in_reference_region() checks:
    │         IF current_page_heading_rects AND y_start_threshold > 0:
    │              return rect.y0 >= y_start_threshold
    │         ELSE IF not start_annotating:  ← start_annotating = FALSE! ❌
    │              return FALSE  ❌
    │
    └─ SKIP! Tidak di-highlight ❌
```

**❌ Hasil:** Tahun **"2011" TIDAK DI-HIGHLIGHT**!

---

### **OUTPUT AKHIR SINGLE-COLUMN (SEBELUM PERBAIKAN):**
```
❌ Heading "REFERENCES" → Tidak ditemukan
❌ Nama jurnal "International Journal of..." → TIDAK di-highlight
❌ Tahun "2011" → TIDAK di-highlight
```

---

---

## 🟢 ALGORITMA SINGLE-COLUMN (SETELAH PERBAIKAN - BENAR)

### **PERBAIKAN YANG DILAKUKAN:**

#### **Perbaikan #1: Ekstraksi Warna (Line 1093)**
```python
# SEBELUM (Berbahaya):
PATTENS_BLUE, INDEXED_RGB, PINK_RGB, YEAR_RGB = colors.values() ❌

# SESUDAH (Aman):
PATTENS_BLUE = colors['PATTENS_BLUE'] ✅
INDEXED_RGB = colors['INDEXED_RGB'] ✅
PINK_RGB = colors['PINK_RGB'] ✅
YEAR_RGB = colors['YEAR_RGB'] ✅
```

#### **Perbaikan #2: Hapus Duplikasi Sorting (Line 1113)**
```python
# SEBELUM:
lines = sorted(by_line.values(), key=lambda d: d['y'])
lines = sorted(by_line.values(), key=lambda d: d['y'])  ❌ Duplikat!

# SESUDAH:
lines = sorted(by_line.values(), key=lambda d: d['y']) ✅
```

#### **Perbaikan #3: Deteksi Heading dari Depan (Line 1151)**
```python
# SEBELUM:
for li in range(len(lines) - 1, -1, -1):  ❌ Mundur!
    line = lines[li]

# SESUDAH:
for li, line in enumerate(lines):  ✅ Maju dari depan!
```

---

### **HASIL SETELAH PERBAIKAN:**

```
FASE 2: DETEKSI HEADING
┌─────────────────────────────────────────────────┐
│  Loop: for li, line in enumerate(lines)         │  ← DARI DEPAN (BENAR!) ✅
└─────────────────────────────────────────────────┘
          │
          └─ SAMA PERSIS seperti Multi-Column ✅
              └─ start_annotating = TRUE ✅

FASE 3-6: SEMUA SAMA seperti Multi-Column ✅
```

### **OUTPUT AKHIR SINGLE-COLUMN (SETELAH PERBAIKAN):**
```
✅ Heading "REFERENCES" → Highlighted biru + summary note
✅ Nama jurnal "International Journal of..." → Highlighted hijau/pink + tooltip
✅ Tahun "2011" → Highlighted merah + warning
```

---

---

## 📊 TABEL PERBANDINGAN AKHIR

| Fase | Multi-Column | Single (Sebelum) | Single (Sesudah) |
|------|--------------|------------------|------------------|
| **1. Persiapan Data** | ✅ Key-based colors<br>✅ 1x sorting | ⚠️ values() unpacking<br>⚠️ 2x sorting | ✅ Key-based colors<br>✅ 1x sorting |
| **2. Deteksi Heading** | ✅ Loop dari depan<br>✅ Heading found | ❌ Loop dari belakang<br>❌ Heading not found | ✅ Loop dari depan<br>✅ Heading found |
| **3. Summary Note** | ✅ Added correctly | ❌ Not added | ✅ Added correctly |
| **4. Tokenisasi** | ✅ Works | ✅ Works | ✅ Works |
| **5. Highlight Jurnal** | ✅ Highlighted | ❌ NOT highlighted | ✅ Highlighted |
| **6. Highlight Tahun** | ✅ Highlighted | ❌ NOT highlighted | ✅ Highlighted |

---

## 🎯 KESIMPULAN UNTUK REFERENSI CONTOH

**Referensi:**
```
M. E. Khan, "Different approaches to white box testing technique for finding errors," 
International Journal of Software Engineering and its Applications, vol. 5, no. 3, 
pp. 1–14, 2011, doi: 10.5121/ijsea.2011.2404.
```

### **Multi-Column (Selalu Benar):**
1. ✅ Menemukan heading "REFERENCES" dengan scanning dari atas
2. ✅ Tokenize: `["international", "journal", "of", "software", "engineering", "and", "its", "applications"]`
3. ✅ Match nama jurnal dengan sliding window
4. ✅ Highlight nama jurnal (hijau jika terindeks, pink jika tidak)
5. ✅ Detect tahun "2011" sebagai outdated
6. ✅ Highlight tahun dengan merah + tooltip warning

### **Single-Column Sebelum Perbaikan:**
1. ❌ Gagal menemukan heading (scan dari bawah)
2. ❌ `start_annotating = FALSE`
3. ❌ Nama jurnal TIDAK di-highlight (region check failed)
4. ❌ Tahun TIDAK di-highlight (not in reference region)
5. ❌ **Hasil PDF: Tidak ada highlight sama sekali!**

### **Single-Column Setelah Perbaikan:**
1. ✅ Menemukan heading "REFERENCES" (scan dari atas seperti multi-column)
2. ✅ `start_annotating = TRUE`
3. ✅ Tokenize dan match nama jurnal dengan benar
4. ✅ Highlight nama jurnal dengan warna yang tepat
5. ✅ Detect dan highlight tahun "2011" sebagai outdated
6. ✅ **Hasil PDF: Identik dengan multi-column!**

---

## 💡 INSIGHT TAMBAHAN

**Mengapa arah loop sangat penting?**

Dokumen akademik umumnya terstruktur:
```
1. ABSTRACT
2. INTRODUCTION
3. METHODOLOGY
4. RESULTS
5. DISCUSSION
6. CONCLUSION
7. REFERENCES      ← Target heading di AKHIR dokumen
   [1] Ref 1...
   [2] Ref 2...
   ...
8. ACKNOWLEDGMENTS (opsional)
9. APPENDIX (opsional)
```

**Loop dari DEPAN (✅ Benar):**
- Scan: Abstract → ... → REFERENCES (STOP & START ANNOTATING)
- Logis untuk dokumen yang terstruktur top-down
- Konteks "8 baris berikutnya" mengacu ke konten referensi yang benar

**Loop dari BELAKANG (❌ Salah):**
- Scan: Appendix → Acknowledgments → ... → REFERENCES
- Bisa melewatkan atau salah mendeteksi
- Konteks "berikutnya" menjadi ambigu dalam loop mundur
- Rentan false positive jika ada kata "references" dalam teks biasa di bagian akhir

---

**Generated by:** AI Analysis System
**Date:** October 24, 2025
