# Reference Validator

**[English](#english-version) | [Bahasa Indonesia](#versi-bahasa-indonesia)**

---

## English Version

### Description

Reference Validator is a web-based application for automatic validation and processing of academic references. It extracts and validates references from PDF and DOCX files against ScimagoJR and Scopus databases, and generates annotated PDF outputs with detailed validation results.

### Key Features

-   Extract and validate reference lists from PDF and DOCX files
-   Direct text input for reference validation
-   Match journal names against ScimagoJR and Scopus datasets
-   Verification rules (quartile, publication year, journal percentage, etc.)
-   Generate PDF files with highlighted validation results
-   Export references in BibTeX format
-   Automatic cleanup of temporary files
-   Responsive web-based GUI interface

### System Requirements

-   Python 3.8 or higher
-   pip (Python Package Manager)
-   Active internet connection
-   Google Gemini API Key
-   Modern web browser (Chrome, Firefox, Edge, Safari)

---

### Installation

#### Step 1: Clone the Repository

```bash
git clone https://github.com/ArvinSSatria/reference-validator.git
cd reference-validator
```

#### Step 2: Create Virtual Environment (Recommended)

```bash
python -m venv venv
venv\Scripts\activate
```

#### Step 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### Step 4: Configure Environment Variables

Create a `.env` file in the project root directory:

```
GEMINI_API_KEY=your_gemini_api_key_here
```

#### Step 5: Run the Application

```bash
python run.py
```

The application will be available at:
```
http://localhost:5000
```

---

### How to Use

1. **Open the Application**: Launch your web browser and navigate to `http://localhost:5000`
2. **Choose Input Method**:
   - **Upload File**: Select a PDF or DOCX file containing references
   - **Enter Text**: Paste or type reference text directly
3. **Start Validation**: Click "Start Validation" and wait for processing
4. **View Results**: Review detailed validation results on the page
5. **Download Report**: Save the annotated PDF with highlights and validation notes
6. **Export References** (Optional): Download individual references in BibTeX format

---

### Directory Structure

```
reference-validator/
├── app/
│   ├── __init__.py
│   ├── routes.py
│   ├── models/
│   │   └── reference.py
│   ├── services/
│   │   ├── ai_service.py
│   │   ├── bibtex_service.py
│   │   ├── docx_service.py
│   │   ├── pdf_annotator.py
│   │   ├── pdf_service.py
│   │   ├── scimago_service.py
│   │   ├── scopus_service.py
│   │   └── validation_service.py
│   └── utils/
│       ├── file_utils.py
│       └── text_utils.py
├── templates/
│   └── index.html
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── script.js
├── data/
│   ├── scimagojr 2024.csv
│   └── scopus 2025.csv
├── uploads/
├── config.py
├── run.py
├── requirements.txt
└── README.md
```

---

### Configuration

Edit `config.py` to customize application behavior:

-   `SECRET_KEY`: Flask session security key
-   `MAX_CONTENT_LENGTH`: Maximum file upload size (default: 16MB)
-   `ALLOWED_EXTENSIONS`: Allowed file types (pdf, docx)
-   `UPLOAD_FOLDER`: Directory for temporary uploaded files
-   `MIN_REFERENCE_COUNT`: Minimum required references
-   `MAX_REFERENCE_COUNT`: Maximum allowed references
-   `JOURNAL_PROPORTION_THRESHOLD`: Minimum journal percentage
-   `REFERENCE_YEAR_THRESHOLD`: Acceptable publication year range
-   `AUTO_CLEANUP_ENABLED`: Enable automatic cleanup of old files
-   `AUTO_CLEANUP_MAX_AGE_HOURS`: Age threshold for file cleanup

---

### Troubleshooting

**Problem**: Application fails to start  
**Solution**: Ensure Python 3.8+ is installed and all dependencies are installed via `pip install -r requirements.txt`

**Problem**: Gemini API Key error  
**Solution**: Create `.env` file with valid `GEMINI_API_KEY` and restart the application

**Problem**: File upload fails  
**Solution**: Ensure file is PDF or DOCX format and does not exceed 16MB

**Problem**: Journal not found in database  
**Solution**: Check journal name spelling. Database contains ScimagoJR and Scopus journals

**Problem**: PDF annotation fails  
**Solution**: Ensure uploaded PDF is not encrypted or corrupted

---

## Versi Bahasa Indonesia

### Deskripsi

Reference Validator adalah aplikasi berbasis web untuk validasi dan pemrosesan referensi akademik secara otomatis. Aplikasi ini mengekstrak dan memvalidasi referensi dari file PDF dan DOCX terhadap database ScimagoJR dan Scopus, serta menghasilkan output PDF beranotasi dengan hasil validasi terperinci.

### Fitur Utama

-   Ekstraksi dan validasi daftar referensi dari file PDF dan DOCX
-   Validasi referensi melalui input teks langsung
-   Pencocokan nama jurnal dengan dataset ScimagoJR dan Scopus
-   Aturan verifikasi (kuartil, tahun publikasi, persentase jurnal, dll.)
-   Generate file PDF dengan highlight hasil validasi
-   Ekspor referensi dalam format BibTeX
-   Pembersihan otomatis file sementara
-   Antarmuka GUI berbasis web yang responsif

### Kebutuhan Sistem

-   Python 3.8 atau lebih tinggi
-   pip (Python Package Manager)
-   Koneksi internet aktif
-   Google Gemini API Key
-   Web browser modern (Chrome, Firefox, Edge, Safari)

---

### Cara Instalasi

#### Langkah 1: Clone Repository

```bash
git clone https://github.com/ArvinSSatria/reference-validator.git
cd reference-validator
```

#### Langkah 2: Buat Virtual Environment (Direkomendasikan)

```bash
python -m venv venv
venv\Scripts\activate
```

#### Langkah 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### Langkah 4: Konfigurasi Environment Variables

Buat file `.env` di direktori root proyek:

```
GEMINI_API_KEY=your_gemini_api_key_here
```

#### Langkah 5: Jalankan Aplikasi

```bash
python run.py
```

Aplikasi akan tersedia di:
```
http://localhost:5000
```

---

### Cara Penggunaan

1. **Buka Aplikasi**: Buka web browser dan navigasi ke `http://localhost:5000`
2. **Pilih Metode Input**:
   - **Upload File**: Pilih file PDF atau DOCX yang berisi referensi
   - **Input Teks**: Paste atau ketik teks referensi langsung
3. **Mulai Validasi**: Klik "Start Validation" dan tunggu proses selesai
4. **Lihat Hasil**: Tinjau hasil validasi terperinci di halaman
5. **Download Laporan**: Simpan PDF beranotasi dengan highlight dan catatan validasi
6. **Ekspor Referensi** (Opsional): Unduh referensi individual dalam format BibTeX

---

### Struktur Direktori

```
reference-validator/
├── app/
│   ├── __init__.py
│   ├── routes.py
│   ├── models/
│   │   └── reference.py
│   ├── services/
│   │   ├── ai_service.py
│   │   ├── bibtex_service.py
│   │   ├── docx_service.py
│   │   ├── pdf_annotator.py
│   │   ├── pdf_service.py
│   │   ├── scimago_service.py
│   │   ├── scopus_service.py
│   │   └── validation_service.py
│   └── utils/
│       ├── file_utils.py
│       └── text_utils.py
├── templates/
│   └── index.html
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── script.js
├── data/
│   ├── scimagojr 2024.csv
│   └── scopus 2025.csv
├── uploads/
├── config.py
├── run.py
├── requirements.txt
└── README.md
```

---

### Konfigurasi

Edit `config.py` untuk menyesuaikan perilaku aplikasi:

-   `SECRET_KEY`: Kunci keamanan session Flask
-   `MAX_CONTENT_LENGTH`: Ukuran file upload maksimum (default: 16MB)
-   `ALLOWED_EXTENSIONS`: Tipe file yang diizinkan (pdf, docx)
-   `UPLOAD_FOLDER`: Direktori untuk file upload sementara
-   `MIN_REFERENCE_COUNT`: Jumlah referensi minimal yang diperlukan
-   `MAX_REFERENCE_COUNT`: Jumlah referensi maksimal yang diizinkan
-   `JOURNAL_PROPORTION_THRESHOLD`: Persentase jurnal minimal
-   `REFERENCE_YEAR_THRESHOLD`: Rentang tahun publikasi yang diterima
-   `AUTO_CLEANUP_ENABLED`: Aktifkan pembersihan otomatis file lama
-   `AUTO_CLEANUP_MAX_AGE_HOURS`: Ambang umur untuk pembersihan file

---

### Troubleshooting (Pemecahan Masalah)

**Masalah**: Aplikasi gagal dimulai  
**Solusi**: Pastikan Python 3.8+ terinstal dan semua dependencies terinstal via `pip install -r requirements.txt`

**Masalah**: Error Gemini API Key  
**Solusi**: Buat file `.env` dengan `GEMINI_API_KEY` yang valid dan restart aplikasi

**Masalah**: Upload file gagal  
**Solusi**: Pastikan file berformat PDF atau DOCX dan tidak melebihi 16MB

**Masalah**: Jurnal tidak ditemukan dalam database  
**Solusi**: Periksa kembali ejaan nama jurnal. Database berisi jurnal ScimagoJR dan Scopus

**Masalah**: Anotasi PDF gagal  
**Solusi**: Pastikan PDF yang diupload tidak terenkripsi atau corrupt

---

## Developer Notes

Untuk pengembang yang ingin menjalankan dari source atau membangun aplikasi, lihat dokumentasi pengembangan di bawah.

### Running from Source

1. Clone repository:
```bash
git clone https://github.com/ArvinSSatria/reference-validator.git
cd reference-validator
```

2. Buat virtual environment:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Install dependencies:
```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

4. Persiapkan file data:
   - Tambahkan API key ke file `.env`
   - Pastikan file `data/scimagojr 2024.csv` dan `data/scopus 2025.csv` ada

5. Jalankan aplikasi:
```powershell
python run.py
```

---

### Lisensi

Proyek ini dilisensikan di bawah MIT License - lihat file [LICENSE](LICENSE) untuk detail lengkap.


