# Reference Validator - Desktop Application

> **Alat Bantu Pemrosesan Referensi Otomatis**  
> Sistem berbasis Natural Language Processing untuk validasi referensi ilmiah secara otomatis

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![Electron](https://img.shields.io/badge/Electron-28.0.0-47848F?logo=electron)](https://www.electronjs.org/)

**[English](#english-version) | [Bahasa Indonesia](#versi-bahasa-indonesia)**

---

## English Version

### Description

Reference Validator is a **desktop application** for automatic validation and processing of academic references. Built with **Electron + Flask**, it extracts and validates references from PDF and DOCX files against ScimagoJR and Scopus databases, and generates annotated PDF outputs with detailed validation results.

### Key Features

-   **Desktop Application** - Standalone Electron app (Windows, macOS, Linux)
-   **File Support** - Extract references from PDF and DOCX files
-   **Text Input** - Direct text input for reference validation
-   **Database Matching** - Match against ScimagoJR and Scopus datasets
-   **Smart Validation** - Quartile, publication year, journal percentage checks
-   **Annotated PDF** - Generate highlighted PDF with validation results
-   **BibTeX Export** - Export references in BibTeX format (.bib)
-   **Real-time Progress** - WebSocket-based progress tracking
-   **Modern UI** - Clean, responsive interface with dark gradient theme
-   **Back to Top** - Smooth scroll navigation button
-   **Auto Cleanup** - Automatic cleanup of temporary files

### System Requirements

-   **OS**: Windows 10/11 (64-bit)
-   **RAM**: 4GB minimum (8GB recommended)
-   **Storage**: 500MB free space
-   **Internet**: Required for AI validation

---

## Installation

### Download Compiled App (Windows)

1. Download `Reference Validator Setup 1.0.0.exe` from [Releases](https://github.com/ArvinSSatria/reference-validator/releases)
2. Run installer and follow setup wizard
3. **⚠️ IMPORTANT**: When prompted, select **"Install for me only"** or **"Just for me"**
   - ❌ **DO NOT** choose "Install for all users" (will cause permission errors)
   - ✅ This ensures proper file access for uploads, cache, and temp files
4. Choose installation location (default: `%LOCALAPPDATA%\Programs`)
5. Desktop shortcut will be created automatically
6. Launch from Desktop or Start Menu

> **Note**: API key is bundled for demo/testing. First launch may take 20-30 seconds.

> **⚠️ Troubleshooting**: If you get "unexpected errors" during validation, it's likely due to installing "for all users". Please uninstall and reinstall with "Install for me only" option.

---

### Run from Source (For Developers)

#### Step 1: Clone Repository
```bash
git clone https://github.com/ArvinSSatria/reference-validator.git
cd reference-validator
```

#### Step 2: Setup Python Environment
```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

#### Step 3: Setup Electron
```bash
cd electron
npm install
```

#### Step 4: Run Application
```bash
npm start
```

---

### How to Use

1. **Launch Application** - Double-click Desktop shortcut or find in Start Menu
   
   > 🛡️ **First launch only**: Windows Firewall may ask permission for Flask server (localhost:5000). Click **"Allow access"** to continue.

2. **Choose Input Method**
   - Upload PDF/DOCX file (drag & drop or click, max 16MB)
   - Paste reference text manually

3. **Configure Options** (Optional)
   - Min. references (default: 10)
   - Citation style (Auto, APA, IEEE, etc.)
   - Min. journal percentage (default: 80%)
   - Min. publication year (default: 5 years)

4. **Validate** - Click "Validasi Referensi" and watch progress

5. **Review Results**
   - Summary: total, valid, invalid, validation rate
   - Filter: Semua / Invalid / Valid / SJR Indexed
   - Detailed validation for each reference

6. **Export**
   - Download annotated PDF with color highlights
   - Export BibTeX (.bib) for citation managers

7. **New Validation** - Click "Back to Top" button or scroll up

---

### Directory Structure

```
reference-validator/
├── app/                        # Flask backend
│   ├── __init__.py
│   ├── routes.py              # API routes
│   ├── models/
│   │   └── reference.py       # Reference data model
│   ├── services/
│   │   ├── ai_service.py      # Gemini AI integration
│   │   ├── bibtex_service.py  # BibTeX generation
│   │   ├── docx_service.py    # DOCX extraction
│   │   ├── pdf_annotator.py   # PDF annotation
│   │   ├── pdf_service.py     # PDF extraction
│   │   ├── scimago_service.py # ScimagoJR matching
│   │   ├── scopus_service.py  # Scopus matching
│   │   └── validation_service.py # Main validation logic
│   └── utils/
│       ├── file_utils.py      # File operations
│       └── text_utils.py      # Text processing
├── electron/                   # Electron desktop app
│   ├── main.js                # Main process
│   ├── preload.js             # Preload script
│   ├── package.json           # Electron dependencies
│   ├── electron-builder.json  # Build configuration
│   └── assets/                # App icons
│       ├── icon.png           # Window icon
│       └── icon.ico           # Windows installer icon
├── templates/
│   └── index.html             # Frontend HTML
├── static/
│   ├── css/
│   │   └── style.css          # Styling
│   └── js/
│       └── script.js          # Frontend logic + SocketIO
├── data/
│   ├── scimagojr 2024.csv     # ScimagoJR database
│   └── scopus 2025.csv        # Scopus database
├── uploads/                    # Temporary file uploads
├── config.py                   # App configuration
├── run.py                      # Flask entry point
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

---

### Configuration

API key is bundled for demo/testing. For production use:

1. Create `.env` file in installation directory
2. Add your Gemini API key:
   ```
   GEMINI_API_KEY=your_api_key_here
   ```
3. Get API key from: https://aistudio.google.com/app/apikey

---

### Troubleshooting

<details>
<summary><b>⚠️ Unexpected errors during validation (Permission denied)</b></summary>

**Cause:** Application installed with "Install for all users" option.

**Solutions:**
1. Uninstall the current application
2. Reinstall with **"Install for me only"** option
3. Alternative: Right-click application → "Run as Administrator" (not recommended)

**Why?** "For all users" installs to `C:\Program Files` which has restricted write permissions. The app needs to create upload folders, cache files, and temp files during validation.
</details>

<details>
<summary><b>First launch takes 20-30 seconds</b></summary>

This is normal. The application needs to:
- Extract Python runtime and libraries
- Load journal databases (60,000+ entries)
- Initialize AI service
- Get Windows Firewall approval

Subsequent launches will be faster (5-10 seconds).
</details>

<details>
<summary><b>Application fails to start</b></summary>

**Solutions:**
- Allow application through Windows Firewall when prompted
- Check if port 5000 is available: `netstat -ano | findstr :5000`
- Restart application
- Reinstall if issue persists
</details>

<details>
<summary><b>File upload fails</b></summary>

**Solutions:**
- Ensure file is PDF or DOCX format
- Check file size < 16MB
- Remove password protection from PDF
- Try re-saving file
</details>

<details>
<summary><b>Journal not found</b></summary>

**Solutions:**
- Check journal name spelling
- Verify journal is in Scimago or Scopus database
- Database covers 31,000+ indexed journals
</details>

---

## Versi Bahasa Indonesia

### Deskripsi

Reference Validator adalah aplikasi desktop untuk validasi referensi akademik secara otomatis menggunakan AI. Aplikasi ini memproses PDF/DOCX dan menghasilkan hasil validasi lengkap dengan PDF beranotasi.

### Cara Instalasi

1. Download `Reference Validator Setup 1.0.0.exe` dari [Releases](https://github.com/ArvinSSatria/reference-validator/releases)
2. Jalankan installer dan ikuti wizard instalasi
3. **⚠️ PENTING**: Saat diminta, pilih **"Install for me only"** atau **"Hanya untuk saya"**
   - ❌ **JANGAN** pilih "Install for all users" / "Untuk semua pengguna" (akan menyebabkan error permission)
   - ✅ Ini memastikan akses file yang tepat untuk upload, cache, dan file temporary
4. Pilih lokasi instalasi (default: `%LOCALAPPDATA%\Programs`)
5. Shortcut desktop dibuat otomatis
6. Buka dari Desktop atau Start Menu

> **Catatan**: API key sudah terpasang untuk demo. Peluncuran pertama butuh 20-30 detik.

> **⚠️ Troubleshooting**: Jika mendapat error "tak terduga" saat validasi, kemungkinan karena install "for all users". Silakan uninstall dan install ulang dengan pilihan "Install for me only".

---

### Cara Penggunaan

1. **Buka Aplikasi** - Klik shortcut di Desktop atau Start Menu
   
   > 🛡️ **Hanya peluncuran pertama**: Windows Firewall mungkin meminta izin untuk Flask server (localhost:5000). Klik **"Izinkan akses"** atau **"Allow access"** untuk melanjutkan.

2. **Pilih Input**
   - Upload file PDF/DOCX (drag & drop, maks 16MB)
   - Paste teks referensi manual

3. **Konfigurasi** (Opsional)
   - Jumlah referensi minimal (default: 10)
   - Gaya sitasi (Auto, APA, IEEE, dll)
   - Persentase jurnal minimal (default: 80%)
   - Tahun publikasi minimal (default: 5 tahun)

4. **Validasi** - Klik "Validasi Referensi" dan tunggu proses

5. **Lihat Hasil**
   - Ringkasan: total, valid, invalid, tingkat validitas
   - Filter: Semua / Invalid / Valid / SJR Indexed
   - Detail validasi tiap referensi

6. **Ekspor**
   - Download PDF beranotasi dengan highlight warna
   - Export BibTeX (.bib) untuk citation manager

7. **Validasi Baru** - Klik tombol "Back to Top" atau scroll ke atas

---

### Troubleshooting (Pemecahan Masalah)

**Peluncuran pertama lama (20-30 detik)**  
Ini normal karena aplikasi perlu ekstrak runtime Python, load database 60,000+ jurnal, dan inisialisasi AI. Peluncuran berikutnya lebih cepat (5-10 detik).

**Aplikasi gagal dimulai**  
Izinkan aplikasi melalui Windows Firewall saat diminta. Cek port 5000 tersedia dengan `netstat -ano | findstr :5000`

**Upload file gagal**  
Pastikan format PDF/DOCX, ukuran < 16MB, tidak terenkripsi password

**Jurnal tidak ditemukan**  
Cek ejaan nama jurnal. Database mencakup 31,000+ jurnal terindeks Scimago/Scopus

---

## Tech Stack

- **Flask** 3.0.0 - Backend web framework
- **Electron** 28.0.0 - Desktop wrapper
- **Google Gemini AI** 0.8.3 - AI validation
- **PyMuPDF** 1.24.14 - PDF processing
- **python-docx** 1.1.2 - DOCX processing
- **FuzzyWuzzy** - Fuzzy string matching

---

## License

MIT License - see [LICENSE](LICENSE) file

---

## Author

**ArvinSSatria** - [GitHub](https://github.com/ArvinSSatria)

---

## Acknowledgments

- Universitas Ahmad Dahlan - Fakultas Teknologi Industri
- ScimagoJR & Scopus - Journal databases
- Google Gemini AI - NLP processing
