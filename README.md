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

#### For Running Compiled App:
-   **Windows**: Windows 10/11 (64-bit)
-   **macOS**: macOS 10.13+ (Intel & Apple Silicon)
-   **Linux**: Ubuntu 18.04+, Fedora, Debian
-   **RAM**: 4GB minimum, 8GB recommended
-   **Storage**: 500MB free space
-   **Internet**: Active connection for Gemini API

#### For Development:
-   Python 3.8 or higher
-   Node.js 16+ & npm
-   pip (Python Package Manager)
-   Google Gemini API Key

---

## Installation

### Option 1: Download Compiled App (Recommended for Users)

#### Windows:
1. Download `Reference-Validator-Setup.exe` from [Releases](https://github.com/ArvinSSatria/reference-validator/releases)
2. Run installer
3. Configure `.env` file (see [Configuration](#configuration))
4. Launch from Desktop or Start Menu

#### macOS:
1. Download `Reference-Validator.dmg` from [Releases](https://github.com/ArvinSSatria/reference-validator/releases)
2. Open DMG and drag to Applications
3. Configure `.env` file (see [Configuration](#configuration))
4. Launch from Applications

#### Linux:
1. Download `Reference-Validator.AppImage` from [Releases](https://github.com/ArvinSSatria/reference-validator/releases)
2. Make executable: `chmod +x Reference-Validator.AppImage`
3. Configure `.env` file (see [Configuration](#configuration))
4. Run: `./Reference-Validator.AppImage`

---

### Option 2: Run from Source (For Developers)

#### Step 1: Clone Repository
```bash
git clone https://github.com/ArvinSSatria/reference-validator.git
cd reference-validator
```

#### Step 2: Setup Python Environment
```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

#### Step 3: Setup Electron Environment
```bash
cd electron
npm install
cd ..
```

#### Step 4: Configure Environment Variables
Create `.env` file in project root:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

#### Step 5: Run Application
```bash
cd electron
npm start
```

---

### Building Installer

To create distributable installer:

```bash
cd electron

# Build for Windows
npm run build

# Build for macOS
npm run build:mac

# Build for Linux
npm run build:linux
```

Output will be in `electron/dist/`

---

### How to Use

1. **Launch Application** 
   - Desktop: Click app icon
   - Development: Run `npm start` in `electron/` folder

2. **Choose Input Method**
   - **Upload File**: Drag & drop or click to select PDF/DOCX (max 16MB)
   - **Text Input**: Paste or type reference list manually

3. **Configure Options** (Optional)
   - Min. Jumlah Referensi (default: 10)
   - Gaya Penulisan (Auto, APA, IEEE, MLA, Chicago, Harvard)
   - Min. Persentase Jurnal (default: 80%)
   - Min. Tahun Publikasi (default: 5 years)

4. **Validate** 
   - Click "Validasi Referensi" button
   - Watch real-time progress bar
   - Wait for analysis to complete

5. **Review Results**
   - View summary (total, valid, invalid, validation rate)
   - Filter by: Invalid / Valid / Indexed (SJR)
   - Check detailed validation for each reference

6. **Export**
   - **Download PDF**: Get annotated PDF with highlights
   - **Export .bib**: Download BibTeX for individual or all references

7. **Validate Again**
   - Scroll to top or click "Back to Top" button (bottom-right)
   - Upload new file or enter new references

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

#### Environment Variables (`.env`)

```env
GEMINI_API_KEY=your_api_key_here
```

Get API key from: https://aistudio.google.com/app/apikey

#### Application Settings (`config.py`)

| Setting | Default | Description |
|---------|---------|-------------|
| `SECRET_KEY` | Auto-generated | Flask session security key |
| `MAX_CONTENT_LENGTH` | 16MB | Maximum file upload size |
| `ALLOWED_EXTENSIONS` | pdf, docx | Allowed file types |
| `UPLOAD_FOLDER` | uploads/ | Temporary upload directory |
| `MIN_REFERENCE_COUNT` | 10 | Minimum required references |
| `MAX_REFERENCE_COUNT` | 200 | Maximum allowed references |
| `JOURNAL_PROPORTION_THRESHOLD` | 80% | Minimum journal percentage |
| `REFERENCE_YEAR_THRESHOLD` | 5 years | Publication year range |
| `AUTO_CLEANUP_ENABLED` | True | Auto cleanup old files |
| `AUTO_CLEANUP_MAX_AGE_HOURS` | 24 | Cleanup age threshold |

#### Electron Settings (`electron/main.js`)

| Setting | Default | Description |
|---------|---------|-------------|
| `width` | 1400 | Window width |
| `height` | 900 | Window height |
| `minWidth` | 1000 | Minimum width |
| `minHeight` | 700 | Minimum height |
| `autoHideMenuBar` | true | Hide File/Edit menu |
| `FLASK_PORT` | 5000 | Backend server port |

---

### Troubleshooting

<details>
<summary><b>Application fails to start</b></summary>

**Causes:**
- Python not installed or wrong version
- Missing dependencies
- Port 5000 already in use

**Solutions:**
```bash
# Check Python version
python --version  # Should be 3.8+

# Reinstall dependencies
pip install -r requirements.txt

# Check if port is in use (Windows)
netstat -ano | findstr :5000

# Kill process using port 5000
taskkill /PID <PID> /F
```
</details>

<details>
<summary><b>Gemini API Key error</b></summary>

**Error messages:**
- "API key tidak valid"
- "Kuota API habis"
- "Timeout koneksi ke Gemini"

**Solutions:**
1. Get valid API key from https://aistudio.google.com/app/apikey
2. Create/edit `.env` file in project root:
   ```
   GEMINI_API_KEY=your_actual_api_key_here
   ```
3. Restart application
4. Check API quota at https://aistudio.google.com/
</details>

<details>
<summary><b>File upload fails</b></summary>

**Solutions:**
- Ensure file format is `.pdf` or `.docx`
- Check file size < 16MB
- Remove password protection from PDF
- Try re-saving file in compatible format
</details>

<details>
<summary><b>Journal not found in database</b></summary>

**Solutions:**
- Check journal name spelling
- Try alternative journal name format
- Verify journal is indexed in ScimagoJR or Scopus
- Update CSV databases in `data/` folder
</details>

<details>
<summary><b>PDF annotation fails / Download stuck</b></summary>

**Solutions:**
- Ensure PDF is not encrypted/password protected
- Check PDF is not corrupted (try opening in Adobe Reader)
- Clear `uploads/` folder
- Restart application
- Check disk space
</details>

<details>
<summary><b>Electron app won't launch</b></summary>

**Solutions:**
```bash
# Rebuild Electron modules
cd electron
npm install
npm rebuild

# Clear cache
npm cache clean --force

# Reinstall
rm -rf node_modules package-lock.json
npm install
```
</details>

<details>
<summary><b>Python dependencies error</b></summary>

**Solutions:**
```bash
# Upgrade pip
python -m pip install --upgrade pip

# Install with verbose output
pip install -r requirements.txt --verbose

# Install individually if batch fails
pip install flask flask-socketio python-docx PyMuPDF fuzzywuzzy python-Levenshtein google-generativeai python-dotenv
```
</details>

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

#### Untuk Aplikasi yang Sudah Dikompilasi:
-   **Windows**: Windows 10/11 (64-bit)
-   **macOS**: macOS 10.13+ (Intel & Apple Silicon)
-   **Linux**: Ubuntu 18.04+, Fedora, Debian
-   **RAM**: 4GB minimum, 8GB disarankan
-   **Storage**: 500MB ruang kosong
-   **Internet**: Koneksi aktif untuk Gemini API

#### Untuk Development:
-   Python 3.8 atau lebih tinggi
-   Node.js 16+ & npm
-   pip (Python Package Manager)
-   Google Gemini API Key

---

## Cara Instalasi

### Opsi 1: Download Aplikasi (Direkomendasikan untuk User)

#### Windows:
1. Download `Reference-Validator-Setup.exe` dari [Releases](https://github.com/ArvinSSatria/reference-validator/releases)
2. Jalankan installer
3. Konfigurasi file `.env` (lihat [Konfigurasi](#konfigurasi-1))
4. Buka dari Desktop atau Start Menu

#### macOS:
1. Download `Reference-Validator.dmg` dari [Releases](https://github.com/ArvinSSatria/reference-validator/releases)
2. Buka DMG dan drag ke Applications
3. Konfigurasi file `.env` (lihat [Konfigurasi](#konfigurasi-1))
4. Buka dari Applications

#### Linux:
1. Download `Reference-Validator.AppImage` dari [Releases](https://github.com/ArvinSSatria/reference-validator/releases)
2. Buat executable: `chmod +x Reference-Validator.AppImage`
3. Konfigurasi file `.env` (lihat [Konfigurasi](#konfigurasi-1))
4. Jalankan: `./Reference-Validator.AppImage`

---

### Opsi 2: Jalankan dari Source (Untuk Developer)

#### Langkah 1: Clone Repository
```bash
git clone https://github.com/ArvinSSatria/reference-validator.git
cd reference-validator
```

#### Langkah 2: Setup Python Environment
```bash
# Buat virtual environment
python -m venv venv

# Aktifkan (Windows)
venv\Scripts\activate

# Aktifkan (macOS/Linux)
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

#### Langkah 3: Setup Electron Environment
```bash
cd electron
npm install
cd ..
```

#### Langkah 4: Konfigurasi Environment Variables
Buat file `.env` di root proyek:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

#### Langkah 5: Jalankan Aplikasi
```bash
cd electron
npm start
```

---

### Build Installer

Untuk membuat installer distribusi:

```bash
cd electron

# Build untuk Windows
npm run build

# Build untuk macOS
npm run build:mac

# Build untuk Linux
npm run build:linux
```

Output akan ada di `electron/dist/`

---

### Cara Penggunaan

1. **Buka Aplikasi** 
   - Desktop: Klik icon aplikasi
   - Development: Jalankan `npm start` di folder `electron/`

2. **Pilih Metode Input**
   - **Upload File**: Drag & drop atau klik untuk pilih PDF/DOCX (maks 16MB)
   - **Input Teks**: Paste atau ketik daftar referensi manual

3. **Konfigurasi Opsi** (Opsional)
   - Min. Jumlah Referensi (default: 10)
   - Gaya Penulisan (Auto, APA, IEEE, MLA, Chicago, Harvard)
   - Min. Persentase Jurnal (default: 80%)
   - Min. Tahun Publikasi (default: 5 tahun)

4. **Validasi** 
   - Klik tombol "Validasi Referensi"
   - Lihat progress bar real-time
   - Tunggu analisis selesai

5. **Lihat Hasil**
   - Lihat ringkasan (total, valid, invalid, tingkat validitas)
   - Filter: Invalid / Valid / Indexed (SJR)
   - Periksa validasi detail setiap referensi

6. **Ekspor**
   - **Download PDF**: Dapatkan PDF beranotasi dengan highlight
   - **Export .bib**: Download BibTeX untuk individual atau semua referensi

7. **Validasi Lagi**
   - Scroll ke atas atau klik tombol "Back to Top" (kanan bawah)
   - Upload file baru atau masukkan referensi baru

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

#### Environment Variables (`.env`)

```env
GEMINI_API_KEY=api_key_anda_disini
```

Dapatkan API key dari: https://aistudio.google.com/app/apikey

#### Pengaturan Aplikasi (`config.py`)

| Pengaturan | Default | Deskripsi |
|-----------|---------|-----------|
| `SECRET_KEY` | Auto-generate | Kunci keamanan session Flask |
| `MAX_CONTENT_LENGTH` | 16MB | Ukuran maksimum upload file |
| `ALLOWED_EXTENSIONS` | pdf, docx | Tipe file yang diizinkan |
| `UPLOAD_FOLDER` | uploads/ | Direktori upload sementara |
| `MIN_REFERENCE_COUNT` | 10 | Jumlah referensi minimal |
| `MAX_REFERENCE_COUNT` | 200 | Jumlah referensi maksimal |
| `JOURNAL_PROPORTION_THRESHOLD` | 80% | Persentase jurnal minimal |
| `REFERENCE_YEAR_THRESHOLD` | 5 tahun | Rentang tahun publikasi |
| `AUTO_CLEANUP_ENABLED` | True | Auto cleanup file lama |
| `AUTO_CLEANUP_MAX_AGE_HOURS` | 24 | Ambang umur cleanup |

#### Pengaturan Electron (`electron/main.js`)

| Pengaturan | Default | Deskripsi |
|-----------|---------|-----------|
| `width` | 1400 | Lebar window |
| `height` | 900 | Tinggi window |
| `minWidth` | 1000 | Lebar minimum |
| `minHeight` | 700 | Tinggi minimum |
| `autoHideMenuBar` | true | Sembunyikan menu File/Edit |
| `FLASK_PORT` | 5000 | Port backend server |

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

## Tech Stack

### Backend:
- **Flask** 3.0.0 - Web framework
- **Flask-SocketIO** 5.4.1 - Real-time communication
- **PyMuPDF (fitz)** 1.24.14 - PDF processing
- **python-docx** 1.1.2 - DOCX processing
- **Google Generative AI (Gemini)** 0.8.3 - AI-powered validation
- **FuzzyWuzzy** 0.18.0 - Fuzzy string matching
- **python-Levenshtein** 0.26.1 - String similarity

### Frontend:
- **HTML5/CSS3** - Modern UI
- **JavaScript (ES6)** - Interactive features
- **Socket.IO Client** 4.5.4 - Real-time updates
- **Font Awesome** 6.0.0 - Icons

### Desktop:
- **Electron** 28.0.0 - Cross-platform desktop wrapper
- **electron-builder** 24.9.1 - App packaging

### Development:
- **Python** 3.8+
- **Node.js** 16+
- **npm** - Package management

---

## Development

### Project Structure
```
Frontend (Electron) → Backend (Flask) → Services → Database (CSV)
     ↓                    ↓                ↓             ↓
  UI Layer         API Routes      Business Logic   Data Layer
```

### Adding New Features

1. **Backend**: Add service in `app/services/`
2. **API**: Add route in `app/routes.py`
3. **Frontend**: Update `static/js/script.js`
4. **UI**: Modify `templates/index.html` & `static/css/style.css`

### Running Tests
```bash
# Python tests (if available)
pytest

# Lint Python code
pylint app/

# Format Python code
black app/
```

---

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

---

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

---

## Authors

**ArvinSSatria**
- GitHub: [@ArvinSSatria](https://github.com/ArvinSSatria)
- Repository: [reference-validator](https://github.com/ArvinSSatria/reference-validator)

---

## Acknowledgments

- **Universitas Ahmad Dahlan** - Fakultas Teknologi Industri, Program Studi S1 Informatika
- **ScimagoJR** - Journal ranking database
- **Scopus** - Academic database
- **Google Gemini AI** - Natural language processing
- **Electron** - Cross-platform desktop framework
- **Flask** - Python web framework

---

## Support

Jika ada pertanyaan atau masalah:
- **Bug Reports**: [Open an issue](https://github.com/ArvinSSatria/reference-validator/issues)
- **Feature Requests**: [Open an issue](https://github.com/ArvinSSatria/reference-validator/issues)
- **Contact**: Through GitHub profile

---

<div align="center">

**Star this repository if you find it helpful!**

Made by [ArvinSSatria](https://github.com/ArvinSSatria)

</div>


