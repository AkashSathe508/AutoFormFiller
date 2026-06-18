"""
Document Classification Agent.
Stage 1: Regex/keyword rules (fast, deterministic).
Stage 2: Local LLM via Ollama (only for low-confidence cases).
"""

import re
import yaml
import os
from typing import Dict, Tuple, List, Optional
from ai_services.shared.schemas import ClassificationResult, DocType

# Load rules at import time
_RULES_PATH = os.path.join(os.path.dirname(__file__), "rules.yaml")
_rules = None


def _load_rules() -> Dict:
    global _rules
    if _rules is None:
        with open(_RULES_PATH, 'r', encoding='utf-8') as f:
            _rules = yaml.safe_load(f)
    return _rules


def classify_document(
    document_id: str,
    ocr_text: str,
    ocr_confidence: float = 1.0,
    llm_threshold: float = 0.85,
) -> ClassificationResult:
    """
    Classify a document from its OCR text.
    Returns doc_type with confidence.
    """
    # Stage 1: Rule-based classification
    doc_type, confidence, method = _rule_based_classify(ocr_text)

    if confidence >= llm_threshold:
        return ClassificationResult(
            document_id=document_id,
            doc_type=DocType(doc_type),
            confidence=confidence,
            method=method,
        )

    # Stage 2: LLM fallback for low-confidence cases
    try:
        llm_type, llm_confidence = _llm_classify(ocr_text[:2000])  # Limit context
        if llm_confidence > confidence:
            return ClassificationResult(
                document_id=document_id,
                doc_type=DocType(llm_type),
                confidence=llm_confidence,
                method="llm",
            )
    except Exception as e:
        print(f"LLM classification failed, using rule result: {e}")

    return ClassificationResult(
        document_id=document_id,
        doc_type=DocType(doc_type),
        confidence=confidence,
        method=method,
    )


def _rule_based_classify(text: str) -> Tuple[str, float, str]:
    """Apply keyword/regex rules. Returns (doc_type, confidence, method)."""
    rules = _load_rules()
    text_upper = text.upper()
    text_clean = re.sub(r'\s+', ' ', text).strip()

    best_type = "UNKNOWN"
    best_score = 0.0

    for doc_type, rule_def in rules.get('document_types', {}).items():
        score = 0.0
        keywords = rule_def.get('keywords', [])
        patterns = rule_def.get('patterns', [])
        weight = rule_def.get('keyword_weight', 1.0)

        # Keyword matching
        matched_keywords = 0
        for kw in keywords:
            if kw.upper() in text_upper:
                matched_keywords += 1
        if keywords:
            score += (matched_keywords / len(keywords)) * weight

        # Regex pattern matching
        for pattern in patterns:
            try:
                if re.search(pattern, text_clean, re.IGNORECASE):
                    score += rule_def.get('pattern_weight', 2.0)
            except re.error:
                pass

        # Normalize score
        max_possible = weight + len(patterns) * rule_def.get('pattern_weight', 2.0)
        if max_possible > 0:
            normalized = min(score / max_possible, 1.0)
        else:
            normalized = 0.0

        if normalized > best_score:
            best_score = normalized
            best_type = doc_type

    return best_type, best_score, "rule"


def _llm_classify(text_excerpt: str) -> Tuple[str, float]:
    """Use local LLM to classify a document from its OCR text."""
    from ai_services.llm_runtime.ollama_client import call_ollama_classification

    prompt = f"""Document text excerpt:
\"\"\"
{text_excerpt}
\"\"\"
Classify this document."""

    system = """You classify Indian identity/supporting documents. Respond with ONLY one of:
AADHAAR, PAN, PASSPORT, DRIVING_LICENSE, MARKSHEET_10, MARKSHEET_12,
DEGREE_CERTIFICATE, CASTE_CERTIFICATE, INCOME_CERTIFICATE, UTILITY_BILL,
MEDICAL_DOCUMENT, GOVERNMENT_ID_OTHER, UNKNOWN
followed by a confidence score 0-1, comma separated. No other text.
Example: AADHAAR,0.97"""

    response = call_ollama_classification(system, prompt)

    # Parse "DOC_TYPE,confidence"
    parts = response.strip().split(',')
    if len(parts) == 2:
        doc_type = parts[0].strip().upper()
        try:
            confidence = float(parts[1].strip())
        except ValueError:
            confidence = 0.5
        if doc_type in [e.value for e in DocType]:
            return doc_type, confidence

    return "UNKNOWN", 0.3
