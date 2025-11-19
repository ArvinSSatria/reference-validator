# Reference Validator - Sistem Pemrosesan Referensi Otomatis

[English Version](#english-version) | [Versi Indonesia](#versi-indonesia)

---

## Versi Indonesia

### Deskripsi Proyek

Reference Validator adalah sistem berbasis web untuk validasi dan pemrosesan referensi akademik secara otomatis. Sistem ini menggunakan teknologi Natural Language Processing (NLP) dan Artificial Intelligence (AI) untuk menganalisis daftar pustaka dari dokumen akademik.

### Fitur Utama

- Validasi referensi dari file PDF dan DOCX
- Validasi referensi dari teks input langsung
- Pengolahan metadata referensi menggunakan Google Generative AI (Gemini)
- Pencocokkan jurnal dengan database ScimagoJR dan Scopus
- Penciptaan PDF dengan anotasi hasil validasi
- Ekspor referensi dalam format BibTeX
- Auto-cleanup file sementara untuk manajemen disk
- Antarmuka web yang responsif dan user-friendly

### Teknologi yang Digunakan

- **Backend**: Flask (Python Web Framework)
- **Frontend**: HTML, CSS, JavaScript
- **AI/ML**: Google Generative AI (Gemini API)
- **Database Jurnal**: ScimagoJR dan Scopus
- **Pemrosesan Dokumen**: python-docx, PyMuPDF, lxml
- **Data Processing**: Pandas, NumPy

### Persyaratan Sistem

- Python 3.8 atau lebih tinggi
- pip (Python Package Manager)
- Koneksi internet aktif
- Google Gemini API Key

### Instalasi

1. Clone repository:
```bash
git clone https://github.com/ArvinSSatria/reference-validator.git
cd reference-validator
```

2. Buat virtual environment (opsional namun direkomendasikan):
```bash
python -m venv venv
venv\Scripts\activate
```

3. Instal dependencies:
```bash
pip install -r requirements.txt
```

4. Konfigurasi environment variables. Buat file `.env` di direktori root:
```
GEMINI_API_KEY=your_gemini_api_key_here
```

5. Jalankan aplikasi:
```bash
python run.py
```

6. Buka browser dan akses aplikasi di:
```
http://localhost:5000
```

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

### Konfigurasi

File `config.py` berisi konfigurasi utama aplikasi:

- `SECRET_KEY`: Kunci rahasia Flask untuk session security
- `MAX_CONTENT_LENGTH`: Ukuran file maksimal yang diizinkan (default: 16MB)
- `ALLOWED_EXTENSIONS`: Ekstensi file yang diizinkan (pdf, docx)
- `UPLOAD_FOLDER`: Direktori untuk menyimpan file upload
- `SCIMAGO_FILE_PATH`: Path ke database ScimagoJR
- `MIN_REFERENCE_COUNT`: Jumlah referensi minimal
- `MAX_REFERENCE_COUNT`: Jumlah referensi maksimal
- `JOURNAL_PROPORTION_THRESHOLD`: Persentase minimum jurnal dalam referensi
- `REFERENCE_YEAR_THRESHOLD`: Tahun maksimal untuk menentukan recency
- `AUTO_CLEANUP_ENABLED`: Aktifkan/nonaktifkan pembersihan otomatis
- `AUTO_CLEANUP_MAX_AGE_HOURS`: Usia maksimal file sebelum dihapus

### Penggunaan API

#### 1. Validasi Referensi

Endpoint: `POST /api/validate`

Request dengan file:
```bash
curl -X POST -F "file=@document.pdf" http://localhost:5000/api/validate
```

Request dengan teks:
```bash
curl -X POST -d "text=Nama Jurnal, 2024" http://localhost:5000/api/validate
```

Response:
```json
{
  "validation_status": "passed",
  "summary": {
    "total_references": 10,
    "valid_references": 9,
    "invalid_references": 1
  },
  "detailed_results": [...]
}
```

#### 2. Download Laporan PDF

Endpoint: `GET /api/download_report`

Response: File PDF dengan anotasi hasil validasi

#### 3. Download BibTeX

Endpoint: `GET /api/download_bibtex/<reference_number>`

Response: File BibTeX untuk referensi tertentu

### Troubleshooting

1. **Error: Gemini API Key tidak ditemukan**
   - Pastikan file `.env` sudah dibuat dengan `GEMINI_API_KEY` yang valid
   - Restart aplikasi setelah mengubah `.env`

2. **Error: File tidak dapat diproses**
   - Pastikan format file PDF atau DOCX dan tidak corrupt
   - Periksa ukuran file tidak melebihi 16MB

3. **Error: Database jurnal tidak load**
   - Pastikan file `data/scimagojr 2024.csv` dan `data/scopus 2025.csv` ada
   - Pastikan file CSV tidak corrupt

### Kontribusi

Kami menerima kontribusi. Silakan buat branch baru untuk fitur atau bug fix Anda:

```bash
git checkout -b feature/nama-fitur
git commit -am 'Add new feature'
git push origin feature/nama-fitur
```

### Lisensi

Proyek ini berada di bawah lisensi MIT. Lihat file LICENSE untuk detail lengkap.

### Kontak

Untuk pertanyaan atau dukungan, silakan hubungi:
- Email: arvin.satria@example.com
- GitHub: @ArvinSSatria

---

## English Version

### Project Description

Reference Validator is a web-based system for automatic validation and processing of academic references. The system uses Natural Language Processing (NLP) and Artificial Intelligence (AI) technologies to analyze bibliographies from academic documents.

### Main Features

- Reference validation from PDF and DOCX files
- Reference validation from direct text input
- Reference metadata processing using Google Generative AI (Gemini)
- Journal matching with ScimagoJR and Scopus databases
- PDF creation with validation result annotations
- Reference export in BibTeX format
- Auto-cleanup of temporary files for disk management
- Responsive and user-friendly web interface

### Technologies Used

- **Backend**: Flask (Python Web Framework)
- **Frontend**: HTML, CSS, JavaScript
- **AI/ML**: Google Generative AI (Gemini API)
- **Journal Database**: ScimagoJR and Scopus
- **Document Processing**: python-docx, PyMuPDF, lxml
- **Data Processing**: Pandas, NumPy

### System Requirements

- Python 3.8 or higher
- pip (Python Package Manager)
- Active internet connection
- Google Gemini API Key

### Installation

1. Clone the repository:
```bash
git clone https://github.com/ArvinSSatria/reference-validator.git
cd reference-validator
```

2. Create a virtual environment (optional but recommended):
```bash
python -m venv venv
venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables. Create a `.env` file in the root directory:
```
GEMINI_API_KEY=your_gemini_api_key_here
```

5. Run the application:
```bash
python run.py
```

6. Open your browser and access the application at:
```
http://localhost:5000
```

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

### Configuration

The `config.py` file contains the main application configuration:

- `SECRET_KEY`: Flask secret key for session security
- `MAX_CONTENT_LENGTH`: Maximum file size allowed (default: 16MB)
- `ALLOWED_EXTENSIONS`: Allowed file extensions (pdf, docx)
- `UPLOAD_FOLDER`: Directory for storing uploaded files
- `SCIMAGO_FILE_PATH`: Path to ScimagoJR database
- `MIN_REFERENCE_COUNT`: Minimum number of references
- `MAX_REFERENCE_COUNT`: Maximum number of references
- `JOURNAL_PROPORTION_THRESHOLD`: Minimum percentage of journals in references
- `REFERENCE_YEAR_THRESHOLD`: Maximum year to determine recency
- `AUTO_CLEANUP_ENABLED`: Enable/disable automatic cleanup
- `AUTO_CLEANUP_MAX_AGE_HOURS`: Maximum file age before deletion

### API Usage

#### 1. Validate References

Endpoint: `POST /api/validate`

Request with file:
```bash
curl -X POST -F "file=@document.pdf" http://localhost:5000/api/validate
```

Request with text:
```bash
curl -X POST -d "text=Journal Name, 2024" http://localhost:5000/api/validate
```

Response:
```json
{
  "validation_status": "passed",
  "summary": {
    "total_references": 10,
    "valid_references": 9,
    "invalid_references": 1
  },
  "detailed_results": [...]
}
```

#### 2. Download Report PDF

Endpoint: `GET /api/download_report`

Response: PDF file with validation result annotations

#### 3. Download BibTeX

Endpoint: `GET /api/download_bibtex/<reference_number>`

Response: BibTeX file for a specific reference

### Troubleshooting

1. **Error: Gemini API Key not found**
   - Ensure that the `.env` file has been created with a valid `GEMINI_API_KEY`
   - Restart the application after modifying `.env`

2. **Error: File cannot be processed**
   - Ensure the file format is PDF or DOCX and not corrupted
   - Check that the file size does not exceed 16MB

3. **Error: Journal database not loaded**
   - Ensure that `data/scimagojr 2024.csv` and `data/scopus 2025.csv` files exist
   - Ensure that CSV files are not corrupted

### Contributing

We welcome contributions. Please create a new branch for your features or bug fixes:

```bash
git checkout -b feature/feature-name
git commit -am 'Add new feature'
git push origin feature/feature-name
```

### License

This project is licensed under the MIT License. See the LICENSE file for full details.

### Contact

For questions or support, please contact:
- Email: arvin.satria@example.com
- GitHub: @ArvinSSatria
