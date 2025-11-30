import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Set Google API Key untuk kompatibilitas dengan google libraries
os.environ['GOOGLE_API_KEY'] = os.getenv("GEMINI_API_KEY", "")

# Determine base directory (works for both script and PyInstaller bundle)
if getattr(sys, 'frozen', False):
    # Running as compiled executable (PyInstaller)
    BASE_DIR = Path(sys._MEIPASS)
else:
    # Running as script
    BASE_DIR = Path(__file__).parent.absolute()

class Config:
    # Konfigurasi Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'kunci-rahasia-default-yang-aman')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Konfigurasi Aplikasi
    ALLOWED_EXTENSIONS = {'docx', 'pdf'}
    SCIMAGO_FILE_PATH = str(BASE_DIR / 'data' / 'scimagojr 2024.csv')
    
    UPLOAD_FOLDER = 'uploads'
    
    # Konfigurasi API (read from .env file)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not found in environment variables. Please create .env file with GEMINI_API_KEY.")

    # Pengaturan Logika Validasi
    MIN_REFERENCE_COUNT = 10
    MAX_REFERENCE_COUNT = 150
    JOURNAL_PROPORTION_THRESHOLD = 80.0
    REFERENCE_YEAR_THRESHOLD = 5
    
    # Pengaturan Auto-Cleanup
    AUTO_CLEANUP_ENABLED = True  # Set False untuk disable auto-cleanup
    AUTO_CLEANUP_MAX_AGE_HOURS = 0.0833  # 5 minutes (file lebih lama dari ini akan dihapus)
 