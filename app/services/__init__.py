from app.services.scimago_service import (
    load_scimago_data,
    search_journal_in_scimago,
    clean_scimago_title,
    SCIMAGO_DATA
)

# Import dari ai_service
from app.services.ai_service import (
    get_generative_model,
    split_references_with_ai,
    analyze_references_with_ai
)

# Import dari validation_service
from app.services.validation_service import (
    process_validation_request
)

# Import dari pdf_service
from app.services.pdf_service import (
    extract_references_from_pdf,
    create_annotated_pdf
)

# Import dari docx_service
from app.services.docx_service import (
    extract_references_from_docx,
    convert_docx_to_pdf
)

__all__ = [
    # Scimago
    'load_scimago_data',
    'search_journal_in_scimago',
    'clean_scimago_title',
    'SCIMAGO_DATA',
    
    # AI
    'get_generative_model',
    'split_references_with_ai',
    'analyze_references_with_ai',
    
    # Validation (Main Entry Point)
    'process_validation_request',
    
    # PDF
    'extract_references_from_pdf',
    'create_annotated_pdf',
    
    # DOCX
    'extract_references_from_docx',
    'convert_docx_to_pdf'
]
