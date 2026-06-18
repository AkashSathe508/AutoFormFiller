# AutoFormFiller

> **AI-powered Indian government form pre-fill platform.** Upload your Aadhaar, PAN, marksheets, and other identity documents once — the system extracts your data, builds a unified profile, and auto-fills any government or institutional form.

## Features

- 🔐 **Document Vault** — encrypted storage for Aadhaar, PAN, Passport, Driving License, Marksheets, Caste/Income certificates
- 🤖 **AI Extraction Pipeline** — PaddleOCR + classification + verification (Verhoeff, MRZ, PAN checksums)
- 📋 **Smart Form Filling** — 3-tier mapping: rule engine → semantic embeddings → local LLM
- 👁️ **Human Review Gate** — mandatory review before any submission, no exceptions
- 📊 **Application Tracker** — centralized status tracking across all applications
- 🏠 **100% Local AI** — Qwen2.5-7B via Ollama, no cloud LLM API costs
- 🔒 **Privacy by Design** — DPDP Act 2023 compliant, envelope encryption, Postgres RLS
- 👨‍👩‍👧‍👦 **Family Mode** — manage multiple profiles under one account

## Quick Start (Development)

### Prerequisites
- Docker Desktop with at least 16GB RAM allocated (for containerized deployment)
- Node.js v18+ and Python 3.12+ (for local host deployment)
- Git

---

### Option A: Run via Docker Compose (Recommended)

#### 1. Configure Environment Files
**Linux / macOS (Bash):**
```bash
cp .env.example .env
```
**Windows (PowerShell):**
```powershell
Copy-Item -Path .env.example -Destination .env
```

#### 2. Generate a Master KEK (Key Encryption Key)
**Linux / macOS:**
```bash
python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```
**Windows (PowerShell):**
```powershell
$bytes = New-Object Byte[] 32; (New-Object System.Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes); [Convert]::ToBase64String($bytes)
```
Copy the generated 44-character string and paste it into your `.env` file as `KEK_BASE64`.

#### 3. Build and Start Services
```bash
docker compose up --build
```

#### 4. Pull the LLM Model (First time only)
Once the Ollama container is healthy, run the download script:
**Linux / macOS:**
```bash
bash infrastructure/scripts/setup_models.sh
```
**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/scripts/setup_models.sh
```

---

### Option B: Run Directly on Local Host (without Docker)

If Docker is not installed, you can start the UI dev server directly:

#### 1. Setup & Run the Frontend
```bash
cd frontend
npm install
npm run dev
```
The client dashboard will be available at: http://localhost:5173

#### 2. Run the Backend API (Optional - Requires PostgreSQL + Redis + MinIO + Ollama)
```bash
cd backend
python -m venv venv
# Linux/macOS
source venv/bin/activate
# Windows
.\venv\Scripts\activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

---

### Service Ports Map
- **Frontend App**: http://localhost:5173
- **FastAPI backend (Swagger Docs)**: http://localhost:8000/docs
- **MinIO S3 Console**: http://localhost:9001
- **Grafana Panel**: http://localhost:3000 (admin / admin)

## Architecture

```
User → Caddy (TLS) → FastAPI → Celery Workers → AI Agents
                                    ↓
                            PostgreSQL + pgvector
                            Redis (queue + cache)
                            MinIO (encrypted docs)
                            Ollama (local LLM)
```

### AI Pipeline
1. **OCR Agent** — PaddleOCR (en+hi) → Tesseract fallback
2. **Classification Agent** — regex rules → Ollama LLM fallback
3. **Verification Agent** — Verhoeff (Aadhaar), MRZ (Passport), PAN format checks
4. **Profile Merge Engine** — conflict detection, user resolution
5. **Form Understanding Agent** — AcroForm PDF → Playwright DOM → LLM layout inference
6. **Form Filling Agent** — rule engine → embedding cosine match → LLM resolver
7. **RAG Agent** — pgvector scheme knowledge base
8. **Workflow Orchestrator** — deterministic FSM (not LLM-driven)

## Project Structure

```
autoformfiller/
├── frontend/          # React + TypeScript + Vite + TailwindCSS
├── backend/           # FastAPI + SQLAlchemy + Celery
├── ai_services/       # All AI agents (OCR, classification, filling, etc.)
├── database/          # SQL schema, seed data
├── infrastructure/    # Docker Compose, Caddy, Prometheus, Grafana
└── docs/              # API docs, runbooks
```

## Security

- **Envelope encryption**: per-document DEK wrapped by KEK (see `backend/app/core/encryption.py`)
- **Column-level encryption**: sensitive fields (Aadhaar, PAN, DOB) via pgcrypto
- **Postgres RLS**: cross-profile data access impossible at the DB layer
- **Append-only audit log**: triggered at the DB level, not just application level
- **No cloud LLM**: all AI inference is local — document content never leaves your server
- **DPDP Act 2023**: consent logging per action, right to erasure via DEK deletion

## Development

### Backend only
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend only
```bash
cd frontend
npm install
npm run dev
```

### Run tests
```bash
cd backend && pytest tests/ -v
cd frontend && npm run typecheck
```

## Troubleshooting

### Error: extension "vector" is not available

This error occurs when attempting to run the database schema DDL [`001_schema.sql`](file:///D:/Fillix/autoformfiller/database/init/001_schema.sql) against a standard PostgreSQL database that does not have the `pgvector` extension installed.

#### Solution A: Use Docker Compose (Recommended)
The project's [`docker-compose.yml`](file:///D:/Fillix/autoformfiller/infrastructure/docker-compose.yml) uses the official pre-compiled `pgvector/pgvector:pg16` image. 
1. Stop any local PostgreSQL servers running on your host machine to free up port `5432`:
   - On Windows: Open `services.msc`, locate `postgresql-x64-...`, right-click and select **Stop**.
2. Run `docker compose up --build`. The database container will launch with `pgvector` pre-configured.

#### Solution B: Installing pgvector on Local Windows PostgreSQL
If you must run PostgreSQL directly on your host Windows OS:
1. Ensure your PostgreSQL version is supported (v12 to v16+).
2. Download pre-compiled binaries for Windows or build them:
   - Run `cmd` as Administrator and set up the MSVC compiler path, or download a pre-built zip of `pgvector` matching your PG version.
3. Copy the compiled assets into your local PostgreSQL installation path:
   - Copy `vector.dll` into `C:\Program Files\PostgreSQL\<version>\lib\`
   - Copy `vector.control` and all `vector--*.sql` files into `C:\Program Files\PostgreSQL\<version>\share\extension\`
4. Restart the PostgreSQL service using Windows Services (`services.msc`).
5. Open your SQL editor and run `CREATE EXTENSION vector;` to verify.

## License

MIT
