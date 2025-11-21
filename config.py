import os
from dotenv import load_dotenv

load_dotenv()

# Set Google API Key untuk kompatibilitas dengan google libraries
os.environ['GOOGLE_API_KEY'] = os.getenv("GEMINI_API_KEY", "")

class Config:
    # Konfigurasi Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'kunci-rahasia-default-yang-aman')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Konfigurasi Aplikasi
    ALLOWED_EXTENSIONS = {'docx', 'pdf'}
    SCIMAGO_FILE_PATH = 'data/scimagojr 2024.csv'
    
    UPLOAD_FOLDER = 'uploads'
    
    # Konfigurasi API
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # Pengaturan Logika Validasi
    MIN_REFERENCE_COUNT = 10
    MAX_REFERENCE_COUNT = 150
    JOURNAL_PROPORTION_THRESHOLD = 80.0
    REFERENCE_YEAR_THRESHOLD = 5
    
    # Pengaturan Auto-Cleanup
    AUTO_CLEANUP_ENABLED = True  # Set False untuk disable auto-cleanup
    AUTO_CLEANUP_MAX_AGE_HOURS = 0.0833  # 5 minutes (file lebih lama dari ini akan dihapus)
 