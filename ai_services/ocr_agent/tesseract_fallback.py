"""Tesseract 5 OCR fallback (used when PaddleOCR fails or returns low confidence)."""

import io
from ai_services.shared.schemas import OCRResult, OCRBlock
from ai_services.ocr_agent.preprocess import preprocess_image_for_ocr, pdf_page_to_image, get_page_count


def run_tesseract_ocr(document_id: str, content: bytes, mime_type: str, lang: str = "eng+hin") -> OCRResult:
    """Run Tesseract OCR as fallback."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise RuntimeError("pytesseract not installed")

    all_text_parts = []
    page_count = 1

    if mime_type == "application/pdf":
        page_count = get_page_count(content)
        for page_num in range(min(page_count, 10)):
            page_bytes = pdf_page_to_image(content, page_num)
            processed = preprocess_image_for_ocr(page_bytes)
            img = Image.open(io.BytesIO(processed))
            text = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
            all_text_parts.append(text)
    else:
        processed = preprocess_image_for_ocr(content)
        img = Image.open(io.BytesIO(processed))
        text = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
        all_text_parts.append(text)

    full_text = "\n".join(all_text_parts)
    devanagari_chars = sum(1 for c in full_text if '\u0900' <= c <= '\u097F')
    lang_detected = "hi" if len(full_text) > 0 and devanagari_chars / max(len(full_text), 1) > 0.2 else "en"

    return OCRResult(
        document_id=document_id,
        text=full_text,
        blocks=[],  # Tesseract block data skipped in fallback mode
        language_detected=lang_detected,
        page_count=page_count,
        ocr_confidence=0.7,  # Conservative estimate for Tesseract
        model_used="tesseract",
    )
