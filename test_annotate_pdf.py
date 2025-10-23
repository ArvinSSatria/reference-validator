from app.services import create_annotated_pdf_from_file

INPUT = r"c:\\xampp\\htdocs\\pemrosesan-referensi-otomatis-terbaru\\18408-ArticleText-68640-1-10-20230503.pdf"
OUTPUT = r"c:\\xampp\\htdocs\\pemrosesan-referensi-otomatis-terbaru\\annotated_test.pdf"

if __name__ == "__main__":
    validation_results = {
        "detailed_results": [],  # skip journal highlighting
        "year_range": 5,         # treat older than current_year-5 as outdated
        "summary": {}
    }
    pdf_bytes, err = create_annotated_pdf_from_file(INPUT, validation_results)
    if err:
        print("ERROR:", err)
    else:
        with open(OUTPUT, 'wb') as f:
            f.write(pdf_bytes)
        print("Wrote:", OUTPUT)
