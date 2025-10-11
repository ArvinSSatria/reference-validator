# run.py (Versi Diperbaiki)

from app import app, logger

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("SISTEM PEMROSESAN REFERENSI OTOMATIS - STARTING")
    logger.info(f"[OK] Gemini API: {'Configured' if app.config['GEMINI_API_KEY'] else 'NOT CONFIGURED'}")
    # Kita perlu import services di sini untuk bisa cek
    from app import services
    # PERUBAHAN DI SINI:
    logger.info(f"[OK] ScimagoJR Database: {len(services.SCIMAGO_DATA)} jurnal loaded")
    logger.info("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)