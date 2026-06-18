"""
Ollama LLM client wrapper for AutoFormFiller.
Enforces: short responses, JSON mode, timeout + graceful fallback.
"""

import json
import httpx
from typing import Optional, Dict, Any
from app.core.config import settings


def call_ollama(
    system: str,
    prompt: str,
    max_tokens: int = 200,
    json_mode: bool = False,
    model: Optional[str] = None,
    temperature: float = 0.1,
) -> Optional[str]:
    """
    Send a request to Ollama and return the response text.
    Returns None on timeout or error (caller should handle gracefully).
    """
    model = model or settings.OLLAMA_PRIMARY_MODEL
    options = {
        "num_predict": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
        "stop": ["\n\n"],
    }
    if json_mode:
        options["format"] = "json"

    payload = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }

    try:
        with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{settings.OLLAMA_HOST}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()
    except httpx.TimeoutException:
        print(f"Ollama timeout after {settings.OLLAMA_TIMEOUT_SECONDS}s")
        return None
    except httpx.HTTPStatusError as e:
        # Try fallback model
        if model == settings.OLLAMA_PRIMARY_MODEL:
            print(f"Primary model failed: {e}. Trying fallback...")
            return call_ollama(system, prompt, max_tokens, json_mode, settings.OLLAMA_FALLBACK_MODEL, temperature)
        print(f"Ollama HTTP error: {e}")
        return None
    except Exception as e:
        print(f"Ollama call error: {e}")
        return None


def call_ollama_classification(system: str, prompt: str) -> str:
    """Specialized call for document classification (short, fast)."""
    result = call_ollama(system, prompt, max_tokens=20, json_mode=False)
    return result or "UNKNOWN,0.3"


def call_ollama_field_mapping(
    field_label: str,
    surrounding_context: str,
    profile_field_keys: list,
) -> Dict[str, Any]:
    """Map a form field label to a canonical profile field key."""
    system = """You map a single form field to the closest matching field from a user's
profile, or determine there is no good match. Only choose a profile field if you
are reasonably confident it represents the same real-world fact. Respond as JSON:
{"profile_field": "<field_key>" | null, "confidence": 0.0-1.0, "reason": "<short reason>"}"""

    prompt = f"""Form field label: "{field_label}"
Form section context: "{surrounding_context}"
Available profile fields: {json.dumps(profile_field_keys)}"""

    result = call_ollama(system, prompt, max_tokens=100, json_mode=True)
    if result:
        try:
            parsed = json.loads(result)
            return {
                "profile_field": parsed.get("profile_field"),
                "confidence": float(parsed.get("confidence", 0.5)),
                "reason": parsed.get("reason", ""),
            }
        except (json.JSONDecodeError, ValueError):
            pass
    return {"profile_field": None, "confidence": 0.0, "reason": "LLM parse error"}


def call_ollama_form_layout(
    layout_text: str,
) -> list:
    """Infer form fields from a flat/scanned PDF's OCR layout text."""
    system = """You extract a list of fillable fields from a government/institutional form's
raw text layout. For each field, give: label, likely_data_type (text/date/number/enum/file_upload), and whether it appears mandatory (look for '*' or 'mandatory').
Return strict JSON list, no prose. Example:
[{"label": "Name", "type": "text", "required": true}, {"label": "DOB", "type": "date", "required": true}]"""

    prompt = f"""Form text with line positions:
\"\"\"
{layout_text[:3000]}
\"\"\""""

    result = call_ollama(system, prompt, max_tokens=500, json_mode=True)
    if result:
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            pass
    return []


def call_ollama_rag(
    query: str,
    chunks: list,
) -> str:
    """RAG answer synthesis. Constrained to provided context only."""
    system = """Answer ONLY using the provided context chunks. If the context does not
contain the answer, say \"I don't have verified information on this — please
check the official source\" and do not guess. Cite which chunk you used."""

    chunks_text = "\n---\n".join([f"[{i+1}] {c}" for i, c in enumerate(chunks)])
    prompt = f"Question: {query}\nContext chunks:\n{chunks_text}"

    result = call_ollama(system, prompt, max_tokens=300)
    return result or "I don't have verified information on this — please check the official source."
