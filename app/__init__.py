import logging
import os
from flask import Flask
from config import Config

# Konfigurasi logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Tentukan path ke root project (parent directory dari app/)
basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Inisialisasi Flask app dengan path template dan static yang benar
app = Flask(__name__, 
            template_folder=os.path.join(basedir, 'templates'),
            static_folder=os.path.join(basedir, 'static'))
app.config.from_object(Config)

# Import routes setelah app dibuat (untuk menghindari circular import)
from app import routes
