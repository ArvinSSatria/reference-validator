import os
from app import app, socketio, logger

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("SISTEM PEMROSESAN REFERENSI OTOMATIS - STARTING")
    logger.info(f"[OK] Gemini API: {'Configured' if app.config['GEMINI_API_KEY'] else 'NOT CONFIGURED'}")
    
    # Import dari modul baru
    from app.services.scimago_service import SCIMAGO_DATA
    logger.info(f"[OK] ScimagoJR Database: {len(SCIMAGO_DATA['by_title'])} jurnal loaded")
    logger.info("=" * 60)
    
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    # Use socketio.run instead of app.run
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)