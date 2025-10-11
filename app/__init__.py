import logging
from flask import Flask
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reference_validator.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, instance_relative_config=False,
            template_folder='../templates',
            static_folder='../static')
app.config.from_object(Config)

if not app.config['GEMINI_API_KEY']:
    raise ValueError("GEMINI_API_KEY tidak ditemukan. Pastikan ada di file .env dan config.py")

from app import routes