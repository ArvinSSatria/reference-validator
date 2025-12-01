import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env from multiple plausible locations to support packaged builds
# 1) Current working directory
# 2) Same directory as this config file
# 3) Executable/temp directory when frozen (PyInstaller)
_env_paths = []
_env_paths.append(Path.cwd() / ".env")
_env_paths.append(Path(__file__).parent / ".env")
if getattr(sys, 'frozen', False):
    try:
        _env_paths.append(Path(sys._MEIPASS) / ".env")
    except Exception:
        pass
for _p in _env_paths:
    if _p.exists():
        load_dotenv(dotenv_path=_p)
        break

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
    
    try:
        # Pakai environment jika tersedia, jika tidak bangun dari bagian obfuscated
        if os.getenv("GEMINI_API_KEY"):
            GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        else:
            from app.utils.secret_key_parts import build_gemini_key
            GEMINI_API_KEY = build_gemini_key()
    except Exception:
        GEMINI_API_KEY = ""

    # Pengaturan Logika Validasi
    MIN_REFERENCE_COUNT = 10
    MAX_REFERENCE_COUNT = 150
    JOURNAL_PROPORTION_THRESHOLD = 80.0
    REFERENCE_YEAR_THRESHOLD = 5
    
    # Pengaturan Auto-Cleanup
    AUTO_CLEANUP_ENABLED = True  # Set False untuk disable auto-cleanup
    AUTO_CLEANUP_MAX_AGE_HOURS = 0.0833  # 5 minutes (file lebih lama dari ini akan dihapus)
 