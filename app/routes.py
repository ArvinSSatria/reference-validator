from datetime import datetime
from flask import render_template, request, jsonify
from app import app, logger # Import 'app' dari paket kita
from app import services   # Import services.py

@app.route('/')
def index():
    """Menampilkan halaman utama aplikasi."""
    return render_template('index.html')

@app.route('/api/validate', methods=['POST'])
def validate_references_api():
    """Endpoint utama untuk validasi referensi."""
    try:
        result = services.process_validation_request(request)
        
        if "error" in result:
            logger.warning(f"Validation failed: {result['error']}")
            return jsonify(result), 400
            
        logger.info(f"Validation successful for {result['summary']['total_references']} references.")
        return jsonify(result)

    except Exception as e:
        logger.critical(f"Unhandled exception in /api/validate: {e}", exc_info=True)
        return jsonify({"error": "Terjadi kesalahan internal tak terduga."}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Endpoint untuk mengecek status sistem."""
    return jsonify({
        "status": "healthy",
        "gemini_configured": bool(app.config['GEMINI_API_KEY']),
        "scimago_loaded": len(services.SCIMAGO_TITLES) > 0,
        "timestamp": datetime.now().isoformat()
    })

# Error Handlers
@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": f"File terlalu besar. Maksimal {app.config['MAX_CONTENT_LENGTH'] // 1024 // 1024}MB."}), 413

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal Server Error: {e}", exc_info=True)
    return jsonify({"error": "Terjadi kesalahan internal pada server."}), 500