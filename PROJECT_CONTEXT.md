# PROJECT_CONTEXT

## Project Overview

* **Project name:** AutoFormFiller
* **Purpose:** AI-powered Indian government form pre-fill platform. Upload identity documents once to extract data, build a unified profile, and auto-fill any government or institutional form.
* **Target users:** Indian citizens needing to fill out complex forms (Aadhaar, PAN, Passport, etc.).
* **Main problem being solved:** Redundant manual data entry across multiple government platforms.

## Tech Stack

### Frontend
* React
* TypeScript
* Vite
* TailwindCSS

### Backend
* Python (FastAPI)
* SQLAlchemy (asyncpg)
* Celery (Background tasks)

### Database
* PostgreSQL 16
* pgvector (for semantic search / embeddings)
* Redis (for Celery broker and caching)

### Authentication
* JWT access tokens + Refresh tokens
* Password hashing (Argon2)
* OTP verification flow

### Cloud Services
* MinIO (Local S3-compatible object storage for documents)

### AI/LLM Services
* **Local LLM:** Ollama (Qwen2.5-7B)
* **OCR:** PaddleOCR (en+hi) + Tesseract fallback
* **Embeddings:** Sentence-Transformers

### Other Dependencies
* Playwright (for automated web form parsing/submission)
* PyMuPDF / pypdf (PDF processing)
* Caddy (Reverse Proxy / TLS)
* Prometheus & Grafana (Monitoring)

## Architecture Overview

* **High-level architecture:** User → Caddy (Reverse Proxy) → FastAPI → Celery Workers → AI Agents. Local AI infrastructure handles all sensitive data processing without relying on external APIs.
* **Data flow:** Document upload → MinIO (encrypted) → OCR extraction (Celery) → Verification & Classification → Profile unification in Postgres → Form understanding & mapping → Final human review → Application submission.
* **Important design decisions:** 
  1. **100% Local AI:** No cloud LLM APIs are used to ensure maximum privacy and cost-efficiency.
  2. **Envelope Encryption:** Documents are encrypted with a Document Encryption Key (DEK) wrapped by a Master Key (KEK).
  3. **Human-in-the-loop:** The system enforces mandatory human review before any form submission.
  4. **PostgreSQL RLS:** Cross-profile data access is prevented at the database level.

## Folder Structure

```text
autoformfiller/
├── frontend/          # React + Vite UI client
├── backend/           # FastAPI application, SQLAlchemy models, Celery tasks
│   └── app/
│       ├── api/       # API routers (v1)
│       ├── core/      # Config, security, encryption
│       ├── db/        # Database sessions, Base class
│       ├── models/    # SQLAlchemy ORM definitions
│       ├── services/  # Business logic
│       └── tasks/     # Celery workers
├── ai_services/       # AI agents (OCR, Classification, Verification, LLM)
├── database/          # SQL schema (001_schema.sql)
├── infrastructure/    # Docker Compose, monitoring (Prometheus/Grafana), Caddy
└── docs/              # Documentation
```

## Features Completed

* **Core Infrastructure:** Docker Compose setup with Postgres, Redis, MinIO, and Ollama.
* **Database Schema:** Full DDL for users, profiles, documents, forms, and workflows.
* **Authentication:** Signup, Login, JWT issuing, Refresh Tokens.
* **Frontend Basics:** Dashboard, Vault, Auth pages, Profile management UI, Forms list, and FormInstanceReview UI.
* **Backend API:** Routers for auth, profiles, documents, forms, and applications.
* **AI Agent Skeleton:** OCR, classification, and verification agent directories are set up.
* **Profile Field Decryption:** `GET /profiles/{id}/fields` decrypts values using each field's source document DEK (matches merge-time encryption).
* **Post-Commit Document Processing:** Celery `extract_document` is enqueued via FastAPI `BackgroundTasks` after the upload transaction commits (avoids race with worker).
* **Field Extraction Agent:** `ai_services/extraction_agent/` provides Aadhaar/PAN-specific extraction with verification-aware confidence scoring.
* **Profile Merge Service:** `backend/app/services/profile_service.py` handles upserts and conflict queueing from extracted fields.

## Features In Progress

* **Form Filling Agent:** Semantic embedding matching for form field mapping to unified profile fields.

## Features Completed (Phase 1 Document Pipeline)

* **Document Processing Pipeline:** Upload → encrypt/MinIO → Celery OCR → classify → verify → extract → profile merge with `processing_status` tracking (`processing` / `extracted` / `verified` / `failed`).
* **End-to-End Tests:** `backend/tests/test_document_pipeline_e2e.py` (in-process agent chain) and `scratch/test_pipeline.py` (live API against Docker stack).

## Phase 1 Pipeline Tasks (in order)

| Task | Status |
| ---- | ------ |
| 1. Encryption round-trip (profile fields) | **Done** |
| 2. Upload → Celery post-commit enqueue | **Done** |
| 3. Aadhaar/PAN-specific extraction | **Done** |
| 4. Profile merge service | **Done** |
| 5. Processing status tracking | **Done** |
| 6. End-to-end test (synthetic Aadhaar) | **Done** |

## Planned Features

* **Government Portal Integration:** Playwright scripts to automatically submit forms to specific external portals.
* **RAG Agent Integration:** Contextual help and form instructions using the local LLM and `rag_chunks` table.
* **Family Mode UI:** Enhancements to manage multiple profiles under a single account seamlessly.

## Database Design

### Tables/Collections
* **Auth & Users:** `users`, `otp_tokens`, `refresh_tokens`, `consent_log`, `audit_log`
* **Profiles:** `profiles`, `profile_fields`, `field_embeddings`, `profile_field_conflicts`
* **Documents:** `documents`, `document_extractions`, `document_verifications`
* **Forms:** `form_templates`, `field_mapping_cache`, `form_instances`, `form_field_values`
* **Workflows:** `workflow_runs`, `application_status_log`
* **Knowledge Base:** `rag_chunks`

### Relationships
* A `User` has many `Profiles` (Family mode).
* A `Profile` has many `Documents`, `Profile Fields`, and `Form Instances`.
* A `Document` links to `Document Extractions` and `Document Verifications`.
* A `Form Template` is instantiated as many `Form Instances`.
* A `Form Instance` contains multiple `Form Field Values`.

## API Documentation

### Public APIs
* `POST /api/v1/auth/register` - User registration
* `POST /api/v1/auth/login` - Authenticate and get JWT
* `POST /api/v1/auth/refresh` - Refresh JWT
* `GET /health` - Service health check

### Protected APIs
* `GET /api/v1/profiles/*` - CRUD for unified profiles
* `GET/POST /api/v1/documents/*` - Upload and manage vault documents
* `GET/POST /api/v1/forms/*` - Manage form templates and instances
* `GET /api/v1/applications/*` - View submission statuses

## Authentication Flow

* **Signup:** User provides email/phone and password.
* **Verification:** OTP sent for verification (MFA support).
* **Login:** Exchanging credentials for an access token (JWT) and a refresh token.
* **Authorization:** Standard Bearer token header. Role-based checks (`user` vs `admin`) and Postgres Row-Level Security for multi-tenant isolation.
* **Session Management:** Refresh tokens stored in the `refresh_tokens` table. Expired or revoked tokens are tracked.

## Third-Party Integrations

* **None explicitly required for core logic.**
* **Purpose:** The system relies entirely on self-hosted services (Ollama, MinIO, Postgres) to maintain DPDP Act 2023 compliance. Future integrations may include SMS/Email gateways for OTP.

## Environment Variables

| Variable | Purpose |
| -------- | ------- |
| `APP_ENV` | Application environment (e.g., development, production) |
| `DATABASE_URL` | Asyncpg connection string for PostgreSQL |
| `DATABASE_SYNC_URL` | Sync connection string for PostgreSQL (for Celery) |
| `REDIS_URL` | Connection string for Redis |
| `MINIO_ENDPOINT` | URL for the local MinIO instance |
| `OLLAMA_HOST` | URL for the local Ollama LLM server |
| `KEK_BASE64` | Master Key Encryption Key for envelope encryption |

## Coding Standards

* **Naming conventions:** `snake_case` for Python variables/functions, `PascalCase` for Python classes & React components, `camelCase` for TypeScript variables.
* **Component structure:** React features separated by pages and modular UI components.
* **API conventions:** RESTful FastAPI routers with Pydantic models for request/response validation. Background processing via Celery for heavy I/O.

## Known Issues

* `ERROR: relation "refresh_tokens" does not exist` occurs if the database volume is initialized before the schema file was updated. Recreating the database volume or manually executing the DDL resolves it.
* `ERROR: extension "vector" is not available` occurs if a user runs native Postgres on Windows instead of the provided `docker-compose` environment.
* Existing Postgres volumes created before June 2026 need `database/init/004_processing_status.sql` applied (or volume recreated) to add `documents.processing_status`.

## Technical Debt

* Complex error handling and retry logic in Celery tasks for OCR timeouts and LLM inference delays.
* The frontend lacks comprehensive test coverage.
* The Playwright web scraping logic needs robust anti-bot bypass strategies for government websites.

## Current Progress Summary

Overall completion estimate: 72% (Phase 1 document pipeline **complete**; form filling next)

## Recommended Next Steps

* **Priority 1:** Implement the form mapping engine using semantic embeddings to automatically resolve form field targets to profile fields.
* **Priority 2:** Refine the frontend `FormInstanceReview` UI to handle conflict resolutions and human-in-the-loop approvals seamlessly.
* **Priority 3:** Wire workflow orchestrator state machine for form-fill and submission flows.

## Important Notes For Future AI Agents

When working on this repository:

1. Read PROJECT_CONTEXT.md first.
2. Do not scan the entire repository unless necessary.
3. Follow existing architecture and coding patterns.
4. Reuse existing components whenever possible.
5. Explain proposed changes before implementing them.
6. Modify only the files required for the task.
