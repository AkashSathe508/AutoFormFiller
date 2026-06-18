"""Image preprocessing for OCR — deskew, denoise, enhance."""

import cv2
import numpy as np
from PIL import Image
import io


def preprocess_image_for_ocr(image_bytes: bytes) -> bytes:
    """
    Apply preprocessing pipeline to improve OCR accuracy:
    1. Convert to grayscale
    2. Deskew (correct rotation)
    3. Denoise
    4. Adaptive threshold / binarization
    Returns processed image as JPEG bytes.
    """
    # Decode image
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        # Try PIL as fallback
        pil_img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        img = np.array(pil_img)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    # Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Deskew
    gray = deskew(gray)

    # Denoise
    denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

    # Adaptive threshold for better contrast
    binary = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )

    # Encode back to JPEG
    _, jpeg_bytes = cv2.imencode('.jpg', binary, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return jpeg_bytes.tobytes()


def deskew(image: np.ndarray) -> np.ndarray:
    """Correct skew in a grayscale image."""
    # Find angle via Hough line transform
    edges = cv2.Canny(image, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)

    if lines is None or len(lines) == 0:
        return image

    angles = []
    for line in lines[:20]:  # Use top 20 lines
        rho, theta = line[0]
        angle = np.degrees(theta) - 90
        if -45 < angle < 45:
            angles.append(angle)

    if not angles:
        return image

    median_angle = np.median(angles)
    if abs(median_angle) < 0.5:  # Less than 0.5 degrees, skip rotation
        return image

    # Rotate to correct skew
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(
        image, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )
    return rotated


def pdf_page_to_image(pdf_bytes: bytes, page_num: int = 0, dpi: int = 200) -> bytes:
    """Convert a PDF page to a high-res JPEG image for OCR."""
    import fitz  # PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if page_num >= len(doc):
        page_num = 0
    page = doc[page_num]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("jpeg")


def get_page_count(pdf_bytes: bytes) -> int:
    """Return the number of pages in a PDF."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return len(doc)
