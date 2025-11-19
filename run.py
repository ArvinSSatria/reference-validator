from app import app, logger

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("SISTEM PEMROSESAN REFERENSI OTOMATIS - STARTING")
    logger.info(f"[OK] Gemini API: {'Configured' if app.config['GEMINI_API_KEY'] else 'NOT CONFIGURED'}")
    
    # Import dari modul baru
    from app.services.scimago_service import SCIMAGO_DATA
    logger.info(f"[OK] ScimagoJR Database: {len(SCIMAGO_DATA['by_title'])} jurnal loaded")
    logger.info("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)