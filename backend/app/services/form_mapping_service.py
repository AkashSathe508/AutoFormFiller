"""Form Mapping Service — 3-stage field mapping pipeline.

Stage 1 — Rule Engine (deterministic, zero model calls)
    Uses rules.yaml dictionary to match well-known label variants.
    Confidence: 1.0

Stage 2 — Embedding Similarity (fast, pre-embedded via pgvector)
    Encodes the form field label with e5-small and runs a cosine
    similarity query against the pre-seeded field_embeddings table.
    Confidence: cosine similarity score (0-1).
    Falls through if score < EMBEDDING_COSINE_THRESHOLD (default 0.82).

Stage 3 — LLM Fallback (local Ollama, per-field, cached after first run)
    Asks the LLM to choose from available profile field keys.
    Results are stored in FieldMappingCache so the LLM is only called
    ONCE per (form_template_id, form_field_id) pair — all subsequent
    users reuse the cached decision at zero LLM cost.
    Confidence: 0.70 (intentionally lower to trigger human review).
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class FormMappingService:
    """Stateless mapping service. Instantiate per Celery task invocation."""

    def __init__(
        self,
        db,                          # SQLAlchemy sync Session
        template_id: str,
        profile_field_keys: List[str],
        embedding_model_name: str = "intfloat/multilingual-e5-small",
        embedding_threshold: float = 0.82,
        ollama_host: str = "http://localhost:11434",
        ollama_model: str = "qwen2.5:7b-instruct-q4_K_M",
        ollama_timeout: int = 60,
    ):
        self.db = db
        self.template_id = template_id
        self.profile_field_keys = set(profile_field_keys)
        self.embedding_model_name = embedding_model_name
        self.embedding_threshold = embedding_threshold
        self.ollama_host = ollama_host
        self.ollama_model = ollama_model
        self.ollama_timeout = ollama_timeout

        # Lazy-initialised embedding model (shared across all calls in this task)
        self._embed_model = None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def resolve(
        self,
        form_field: dict,
        profile_hint: Optional[str] = None,
    ) -> Tuple[Optional[str], float, str]:
        """Resolve a form field dict to a (profile_key, confidence, method) tuple.

        Args:
            form_field:    The field dict from form_templates.field_schema
                           (must have "field_id" and "label").
            profile_hint:  Optional LLM-generated hint from form_parser
                           (profile_field_hint key in the field dict).

        Returns:
            (profile_field_key | None, confidence, method)
            method is one of: "cache" | "rule" | "hint" | "embedding" | "llm" | "none"
        """
        fid = form_field.get("field_id", "")
        label = form_field.get("label", fid)

        # ── 0. Check FieldMappingCache (previously resolved) ──────────────
        cached = self._check_cache(fid)
        if cached is not None:
            key, conf, method = cached
            logger.debug("Cache hit: %s → %s (%.2f)", label, key, conf)
            return key, conf, "cache"

        # ── 1. Rule engine ────────────────────────────────────────────────
        from app.services.rule_engine.loader import rule_match
        rule_key = rule_match(label)
        if rule_key and rule_key in self.profile_field_keys:
            logger.debug("Rule match: %s → %s", label, rule_key)
            self._write_cache(fid, rule_key, 1.0, "rule")
            return rule_key, 1.0, "rule"

        # ── 2. Profile hint (from LLM normalisation during form parse) ────
        if profile_hint and profile_hint in self.profile_field_keys:
            logger.debug("Hint match: %s → %s", label, profile_hint)
            self._write_cache(fid, profile_hint, 0.92, "hint")
            return profile_hint, 0.92, "hint"

        # ── 3. Embedding similarity (pgvector query) ──────────────────────
        emb_key, emb_score = self._embedding_match(label)
        if emb_key and emb_score >= self.embedding_threshold:
            logger.debug("Embedding match: %s → %s (%.3f)", label, emb_key, emb_score)
            self._write_cache(fid, emb_key, emb_score, "embedding")
            return emb_key, emb_score, "embedding"

        # ── 4. LLM fallback ───────────────────────────────────────────────
        llm_key = self._llm_match(label, form_field)
        if llm_key and llm_key in self.profile_field_keys:
            logger.debug("LLM match: %s → %s", label, llm_key)
            self._write_cache(fid, llm_key, 0.70, "llm")
            return llm_key, 0.70, "llm"

        # No match
        self._write_cache(fid, None, 0.0, "none")
        return None, 0.0, "none"

    # ------------------------------------------------------------------
    # Stage 2 — Embedding similarity via pgvector
    # ------------------------------------------------------------------

    def _embedding_match(self, label: str) -> Tuple[Optional[str], float]:
        """Cosine-similarity search against field_embeddings table in pgvector."""
        try:
            from sentence_transformers import SentenceTransformer
            from sqlalchemy import text

            if self._embed_model is None:
                logger.debug("Loading embedding model: %s", self.embedding_model_name)
                self._embed_model = SentenceTransformer(self.embedding_model_name)

            query_vec = self._embed_model.encode(
                f"query: {label}",
                normalize_embeddings=True,
            )
            vec_str = "[" + ",".join(f"{v:.6f}" for v in query_vec.tolist()) + "]"

            # Build an IN clause to restrict to profile fields this instance actually has
            # so we never map to a field the user has no data for.
            if not self.profile_field_keys:
                return None, 0.0

            keys_tuple = tuple(self.profile_field_keys)
            result = self.db.execute(
                text(
                    """
                    SELECT field_key,
                           1 - (embedding <=> :vec::vector) AS cosine_sim
                    FROM   field_embeddings
                    WHERE  field_key = ANY(:keys)
                    ORDER  BY embedding <=> :vec::vector
                    LIMIT  1
                    """
                ),
                {"vec": vec_str, "keys": list(keys_tuple)},
            ).fetchone()

            if result:
                return result[0], float(result[1])
            return None, 0.0

        except Exception as e:
            logger.warning("Embedding match failed: %s", e)
            return None, 0.0

    # ------------------------------------------------------------------
    # Stage 3 — LLM fallback via Ollama
    # ------------------------------------------------------------------

    def _llm_match(self, label: str, form_field: dict) -> Optional[str]:
        """Ask Ollama to pick the best profile field key for this form label."""
        import httpx

        keys_str = ", ".join(sorted(self.profile_field_keys)[:40])  # token budget
        field_type = form_field.get("field_type", "text")

        prompt = (
            f'Map this government form field to the most appropriate profile key.\n\n'
            f'Form field label: "{label}"\n'
            f'Form field type: {field_type}\n\n'
            f'Available profile keys: {keys_str}\n\n'
            f'Rules:\n'
            f'- Respond with ONLY the exact profile key name\n'
            f'- Respond "none" if no key is a reasonable match\n'
            f'- Do not guess; prefer "none" over a wrong match\n'
            f'Answer:'
        )

        try:
            response = httpx.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0},
                },
                timeout=self.ollama_timeout,
            )
            response.raise_for_status()
            matched = response.json().get("response", "none").strip().lower()
            if matched == "none" or matched not in self.profile_field_keys:
                return None
            return matched
        except Exception as e:
            logger.warning("LLM mapping failed for label '%s': %s", label, e)
            return None

    # ------------------------------------------------------------------
    # FieldMappingCache helpers
    # ------------------------------------------------------------------

    def _check_cache(self, form_field_id: str) -> Optional[Tuple[Optional[str], float, str]]:
        """Return cached mapping for this (template, field) pair, or None."""
        from app.models.form import FieldMappingCache
        from sqlalchemy import select

        cached = (
            self.db.execute(
                select(FieldMappingCache).where(
                    FieldMappingCache.form_template_id == self.template_id,
                    FieldMappingCache.form_field_id == form_field_id,
                )
            ).scalar_one_or_none()
        )
        if cached:
            return cached.profile_field_key, cached.confidence, cached.method
        return None

    def _write_cache(
        self,
        form_field_id: str,
        profile_field_key: Optional[str],
        confidence: float,
        method: str,
    ) -> None:
        """Upsert a mapping decision into FieldMappingCache."""
        from app.models.form import FieldMappingCache
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        try:
            stmt = pg_insert(FieldMappingCache).values(
                form_template_id=self.template_id,
                form_field_id=form_field_id,
                profile_field_key=profile_field_key,
                confidence=confidence,
                method=method,
            ).on_conflict_do_update(
                index_elements=["form_template_id", "form_field_id"],
                set_={
                    "profile_field_key": profile_field_key,
                    "confidence": confidence,
                    "method": method,
                },
            )
            self.db.execute(stmt)
        except Exception as e:
            logger.warning("Failed to write mapping cache entry: %s", e)
