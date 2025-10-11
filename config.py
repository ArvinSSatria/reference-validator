import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """
    Kelas konfigurasi terpusat untuk aplikasi.
    Mengambil nilai dari environment variables jika ada.
    """
    # Konfigurasi Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'kunci-rahasia-default-yang-aman')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Konfigurasi Aplikasi
    ALLOWED_EXTENSIONS = {'docx'}
    SCIMAGO_FILE_PATH = 'scimagojr 2024.csv'
    
    # Konfigurasi API
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # Pengaturan Logika Validasi
    MIN_REFERENCE_COUNT = 10
    MAX_REFERENCE_COUNT = 150
    JOURNAL_PROPORTION_THRESHOLD = 80.0
    REFERENCE_YEAR_THRESHOLD = 5 