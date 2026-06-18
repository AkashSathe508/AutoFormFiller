"""
PaddleOCR-based OCR agent.
Primary OCR engine — supports English + Hindi bilingual documents.
"""

import io
import threading
from typing import Optional, List
from ai_services.shared.schemas import OCRResult, OCRBlock
from ai_services.ocr_agent.preprocess import preprocess_image_for_ocr, pdf_page_to_image, get_page_count

_paddle_ocr = None
_paddle_lock = threading.Lock()


def get_paddle_ocr():
    """Lazy singleton for PaddleOCR model."""
    global _paddle_ocr
    if _paddle_ocr is None:
        with _paddle_lock:
            if _paddle_ocr is None:
                from paddleocr import PaddleOCR
                print("Loading PaddleOCR model (en+hi)...")
                _paddle_ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang="en",
                    show_log=False,
                    use_gpu=False,
                    enable_mkldnn=False,
                )
                print("PaddleOCR loaded.")
    return _paddle_ocr


def run_paddle_ocr(document_id: str, content: bytes, mime_type: str) -> OCRResult:
    """
    Run PaddleOCR on a document (image or PDF).
    Returns structured OCR result.
    """
    all_text_parts = []
    all_blocks = []
    total_confidence = []
    page_count = 1

    if mime_type == "application/pdf":
        page_count = get_page_count(content)
        pages_to_process = min(page_count, 10)  # Cap at 10 pages
        for page_num in range(pages_to_process):
            page_bytes = pdf_page_to_image(content, page_num)
            processed = preprocess_image_for_ocr(page_bytes)
            text, blocks, confidence = _run_paddle_on_image(processed)
            all_text_parts.append(text)
            all_blocks.extend(blocks)
            total_confidence.extend(confidence)
    else:
        # Image file
        processed = preprocess_image_for_ocr(content)
        text, blocks, confidence = _run_paddle_on_image(processed)
        all_text_parts.append(text)
        all_blocks.extend(blocks)
        total_confidence.extend(confidence)

    full_text = "\n".join(all_text_parts)
    avg_confidence = float(sum(total_confidence) / len(total_confidence)) if total_confidence else 0.0

    # Detect language (heuristic: if >20% chars are in Devanagari range, it's Hindi)
    devanagari_chars = sum(1 for c in full_text if '\u0900' <= c <= '\u097F')
    total_chars = max(len(full_text.strip()), 1)
    lang = "hi" if devanagari_chars / total_chars > 0.2 else "en"

    return OCRResult(
        document_id=document_id,
        text=full_text,
        blocks=all_blocks,
        language_detected=lang,
        page_count=page_count,
        ocr_confidence=avg_confidence,
        model_used="paddleocr",
    )


def _run_paddle_on_image(image_bytes: bytes):
    """Run PaddleOCR on a single image. Returns (text, blocks, confidences)."""
    ocr = get_paddle_ocr()

    import numpy as np
    import cv2
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    result = ocr.ocr(img, cls=True)

    text_parts = []
    blocks = []
    confidences = []

    if result and result[0]:
        for line in result[0]:
            if line is None:
                continue
            bbox, (text, confidence) = line[0], line[1]
            text_parts.append(text)
            confidences.append(confidence)

            # Flatten bbox coordinates
            flat_bbox = [coord for point in bbox for coord in point]
            blocks.append(OCRBlock(
                text=text,
                bbox=flat_bbox,
                confidence=confidence,
            ))

    return "\n".join(text_parts), blocks, confidences
