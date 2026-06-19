"""Tests for upload → Celery enqueue ordering."""

import ast
from pathlib import Path


def test_vault_service_does_not_enqueue_celery_directly():
    """Extraction must be enqueued post-commit by the API layer, not VaultService."""
    vault_path = Path(__file__).resolve().parents[1] / "app" / "services" / "vault_service.py"
    source = vault_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "delay":
                raise AssertionError(
                    "vault_service.py must not call .delay(); use documents API BackgroundTasks"
                )


def test_documents_api_defines_post_commit_enqueue_helper():
    docs_path = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "documents.py"
    source = docs_path.read_text(encoding="utf-8")
    assert "enqueue_document_extraction" in source
    assert "background_tasks.add_task" in source
