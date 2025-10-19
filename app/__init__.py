# app/__init__.py

import logging
from flask import Flask
from config import Config

# Setup logging (tidak berubah)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reference_validator.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Inisialisasi Aplikasi Flask dengan path template dan static yang benar
app = Flask(__name__, instance_relative_config=False,
            template_folder='../templates',
            static_folder='../static')

# Muat konfigurasi dari objek Config
app.config.from_object(Config)

# --- TAMBAHKAN BARIS INI DI SINI ---
# Atur secret key untuk aplikasi agar session bisa bekerja
app.secret_key = Config.SECRET_KEY

# Cek konfigurasi penting saat startup (tidak berubah)
if not app.config['GEMINI_API_KEY']:
    raise ValueError("GEMINI_API_KEY tidak ditemukan. Pastikan ada di file .env dan config.py")

# Import routes setelah aplikasi diinisialisasi (tidak berubah)
from app import routes