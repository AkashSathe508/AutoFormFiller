"""PDF Form Parser — Form Understanding Agent (PDF path).

Two parsing strategies:
  1. AcroForm path  — pypdf reads interactive field definitions directly.
                      Zero LLM calls; deterministic and fast.
  2. Flat PDF path  — PyMuPDF rasterises pages, existing OCR agent extracts
                      text, then Ollama infers field boundaries from layout.

Output contract (matches web parser output):
  {
    "form_id":   str,           # sha256 hash of the PDF bytes
    "form_name": str,           # from PDF metadata or filename
    "fields":    List[FieldSchema],
    "upload_slots": List[UploadSlot],
  }

FieldSchema = {
    "field_id":    str,   # AcroForm name or inferred id
    "label":       str,
    "field_type":  str,   # text | number | date | select | checkbox | radio | file | signature
    "required":    bool,
    "options":     list | None,   # for select/radio
    "max_length":  int  | None,
    "read_only":   bool,
    "position":    dict | None,   # {"page": int, "x": float, "y": float}
}

UploadSlot = {
    "slot_id":          str,
    "label":            str,
    "accepted_formats": list,
    "max_size_kb":      int | None,
}
"""

import hashlib
import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_pdf(
    pdf_bytes: bytes,
    filename: str = "form.pdf",
    ollama_host: str = "http://localhost:11434",
    ollama_model: str = "qwen2.5:7b-instruct-q4_K_M",
    ollama_timeout: int = 120,
) -> Dict[str, Any]:
    """Parse a PDF form and return a structured field schema.

    Tries AcroForm first; falls back to OCR+LLM for flat/scanned PDFs.
    """
    form_id = hashlib.sha256(pdf_bytes).hexdigest()

    # --- Strategy 1: AcroForm ---
    acroform_fields, has_acroform = _parse_acroform(pdf_bytes)
    if has_acroform and acroform_fields:
        logger.info("PDF %s: AcroForm detected — %d fields", form_id[:8], len(acroform_fields))
        form_name = _extract_pdf_title(pdf_bytes, filename)
        fields = [f for f in acroform_fields if f["field_type"] != "file"]
        upload_slots = [
            {
                "slot_id": f["field_id"],
                "label": f["label"],
                "accepted_formats": ["image/jpeg", "image/png", "application/pdf"],
                "max_size_kb": None,
            }
            for f in acroform_fields if f["field_type"] == "file"
        ]
        return {
            "form_id": form_id,
            "form_name": form_name,
            "fields": fields,
            "upload_slots": upload_slots,
            "parse_method": "acroform",
        }

    # --- Strategy 2: OCR + LLM fallback ---
    logger.info("PDF %s: No AcroForm — falling back to OCR+LLM", form_id[:8])
    ocr_text = _ocr_pdf_pages(pdf_bytes)
    if not ocr_text.strip():
        logger.warning("PDF %s: OCR returned empty text", form_id[:8])
        return {
            "form_id": form_id,
            "form_name": _extract_pdf_title(pdf_bytes, filename),
            "fields": [],
            "upload_slots": [],
            "parse_method": "ocr_empty",
        }

    llm_fields = _infer_fields_with_llm(
        ocr_text, ollama_host, ollama_model, ollama_timeout
    )
    fields = [f for f in llm_fields if f.get("field_type") != "file"]
    upload_slots = [
        {
            "slot_id": f["field_id"],
            "label": f["label"],
            "accepted_formats": ["image/jpeg", "image/png", "application/pdf"],
            "max_size_kb": None,
        }
        for f in llm_fields if f.get("field_type") == "file"
    ]
    return {
        "form_id": form_id,
        "form_name": _extract_pdf_title(pdf_bytes, filename),
        "fields": fields,
        "upload_slots": upload_slots,
        "parse_method": "ocr_llm",
    }


# ---------------------------------------------------------------------------
# Strategy 1 — AcroForm parsing via pypdf
# ---------------------------------------------------------------------------

def _parse_acroform(pdf_bytes: bytes) -> Tuple[List[Dict], bool]:
    """Extract AcroForm field definitions from a PDF.

    Returns (field_list, has_acroform_flag).
    """
    try:
        from pypdf import PdfReader
        from io import BytesIO

        reader = PdfReader(BytesIO(pdf_bytes))

        # Check for AcroForm
        if not reader.trailer.get("/Root") or not reader.trailer["/Root"].get("/AcroForm"):
            return [], False

        raw = reader.get_fields()
        if not raw:
            return [], False

        fields: List[Dict] = []
        for name, props in raw.items():
            ft = str(props.get("/FT", "/Tx")).lstrip("/")
            widget_type = _acroform_type_to_schema_type(ft, props)

            # Collect options for choice fields
            options = None
            if ft == "Ch":
                opt_raw = props.get("/Opt", [])
                options = []
                for opt in opt_raw:
                    if isinstance(opt, (list, tuple)):
                        options.append(str(opt[1] if len(opt) > 1 else opt[0]))
                    else:
                        options.append(str(opt))

            # Determine label: /TU (tooltip) preferred, fallback to /T (name)
            label = str(props.get("/TU", props.get("/T", name)))

            # Flags
            flags = int(props.get("/Ff", 0))
            read_only = bool(flags & 1)
            required = bool(flags & 2)

            # Position from widget annotation (first widget if multiple)
            position = None
            widgets = props.get("/Kids") or ([props] if "/Rect" in props else [])
            if widgets:
                try:
                    rect = widgets[0].get("/Rect")
                    if rect:
                        position = {
                            "x": float(rect[0]),
                            "y": float(rect[1]),
                            "width": float(rect[2]) - float(rect[0]),
                            "height": float(rect[3]) - float(rect[1]),
                        }
                except Exception:
                    pass

            fields.append({
                "field_id": name,
                "label": label,
                "field_type": widget_type,
                "required": required,
                "read_only": read_only,
                "options": options,
                "max_length": int(props.get("/MaxLen", 0)) or None,
                "position": position,
            })

        return fields, True

    except Exception as e:
        logger.warning("AcroForm parsing failed: %s", e)
        return [], False


def _acroform_type_to_schema_type(ft: str, props: Dict) -> str:
    """Map AcroForm /FT value to schema field_type string."""
    if ft == "Tx":
        return "text"
    if ft == "Ch":
        # Multi-select vs combo vs list
        flags = int(props.get("/Ff", 0))
        is_combo = bool(flags & (1 << 17))  # Bit 18
        return "select" if is_combo else "radio"
    if ft == "Btn":
        flags = int(props.get("/Ff", 0))
        is_radio = bool(flags & (1 << 15))  # Bit 16
        return "radio" if is_radio else "checkbox"
    if ft == "Sig":
        return "signature"
    return "text"


# ---------------------------------------------------------------------------
# Strategy 2 — OCR with PyMuPDF + Tesseract/PaddleOCR
# ---------------------------------------------------------------------------

def _ocr_pdf_pages(pdf_bytes: bytes, max_pages: int = 8) -> str:
    """Rasterise PDF pages and run OCR. Returns concatenated text."""
    try:
        import fitz  # PyMuPDF
        import io

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        texts: List[str] = []

        for page_num in range(min(len(doc), max_pages)):
            page = doc[page_num]

            # First try: extract embedded text (fast, no OCR needed)
            embedded_text = page.get_text("text").strip()
            if len(embedded_text) > 50:
                texts.append(f"[PAGE {page_num + 1}]\n{embedded_text}")
                continue

            # No embedded text — rasterise at 150 DPI and OCR
            mat = fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            img_bytes = pix.tobytes("png")

            page_text = _run_ocr_on_image(img_bytes)
            if page_text:
                texts.append(f"[PAGE {page_num + 1}]\n{page_text}")

        doc.close()
        return "\n\n".join(texts)

    except Exception as e:
        logger.warning("PDF OCR failed: %s", e)
        return ""


def _run_ocr_on_image(image_bytes: bytes) -> str:
    """Run PaddleOCR (or Tesseract fallback) on an image bytes blob."""
    # Try PaddleOCR first
    try:
        from paddleocr import PaddleOCR
        import numpy as np
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)

        ocr = PaddleOCR(lang="en", show_log=False, use_angle_cls=True)
        result = ocr.ocr(img_array, cls=True)
        if result and result[0]:
            return "\n".join(
                line[1][0] for line in result[0] if line and line[1]
            )
    except Exception as e:
        logger.debug("PaddleOCR unavailable: %s — trying Tesseract", e)

    # Tesseract fallback
    try:
        import pytesseract
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(img, lang="eng+hin")
    except Exception as e:
        logger.warning("Tesseract fallback also failed: %s", e)

    return ""


# ---------------------------------------------------------------------------
# Strategy 2b — LLM field inference from OCR text
# ---------------------------------------------------------------------------

def _infer_fields_with_llm(
    ocr_text: str,
    ollama_host: str,
    ollama_model: str,
    timeout: int,
) -> List[Dict]:
    """Ask the local LLM to infer form fields from OCR-extracted text."""
    import httpx

    # Trim to first 3000 chars to stay within context budget
    truncated = ocr_text[:3000]

    prompt = (
        "You are an expert at analysing Indian government forms.\n\n"
        "Below is text extracted (via OCR) from a scanned government/institutional form. "
        "Identify all fillable fields the user would need to complete.\n\n"
        "For each field return a JSON object with:\n"
        '  "field_id":   unique snake_case identifier\n'
        '  "label":      human-readable field label (translate Hindi if needed)\n'
        '  "field_type": one of [text, number, date, select, checkbox, radio, file, signature, textarea]\n'
        '  "required":   true/false (look for * or "mandatory")\n'
        '  "options":    list of options for select/radio, null otherwise\n'
        '  "max_length": integer or null\n\n'
        "Form text:\n"
        '"""\n'
        f"{truncated}\n"
        '"""\n\n'
        "Respond with ONLY a valid JSON array, no prose or markdown fences:"
    )

    try:
        response = httpx.post(
            f"{ollama_host}/api/generate",
            json={
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        raw = response.json().get("response", "[]").strip()
        # Strip markdown fences if LLM wraps them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning("LLM field inference failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _extract_pdf_title(pdf_bytes: bytes, filename: str) -> str:
    """Extract PDF document title from metadata, fallback to filename."""
    try:
        from pypdf import PdfReader
        from io import BytesIO

        reader = PdfReader(BytesIO(pdf_bytes))
        info = reader.metadata
        if info and info.title:
            return str(info.title).strip()
    except Exception:
        pass
    # Strip extension from filename
    return os.path.splitext(os.path.basename(filename))[0].replace("_", " ").replace("-", " ").title()
