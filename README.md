# LettingCopilot

AI-powered lettings qualification and booking agent built with **Google ADK 2.2.0** + **Gemini API (free tier)**.

Handles the full journey from first enquiry to viewing booked — qualification, property matching, calendar booking, reminders, and offer collection.

**Live URL:** https://letting-copilot-ruzwhtmsaq-uc.a.run.app

---

## Architecture

```
  User / Browser
  ──────────────
  https://letting-copilot-ruzwhtmsaq-uc.a.run.app
         │
         │ HTTPS
         ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                    Google Cloud Run (dev)                           │
  │                    us-central1 · 0–3 instances · 512Mi             │
  │                    SA: letting-copilot-runner@...                  │
  │                                                                     │
  │  ┌──────────────────────────────────────────────────────────────┐  │
  │  │  FastAPI  (port 8080)                                        │  │
  │  │  POST /chat  ·  GET /health  ·  GET /properties  ·  GET /   │  │
  │  └─────────────────────────┬────────────────────────────────────┘  │
  │                            │                                        │
  │          ADK Runner  ·  InMemorySessionService                     │
  │                            │                                        │
  │  ┌─────────────────────────▼────────────────────────────────────┐  │
  │  │              OrchestratorAgent  (root_agent)                 │  │
  │  │              model: gemini-flash-latest                      │  │
  │  └────┬──────────────┬──────────────┬──────────────┬───────────┘  │
  │       │              │              │              │               │
  │  ┌────▼────┐   ┌─────▼────┐  ┌─────▼────┐  ┌─────▼──────┐       │
  │  │Qualific-│   │ Matching │  │ Booking  │  │ Follow-up  │       │
  │  │ation   │   │  Agent   │  │  Agent   │  │   Agent    │       │
  │  │ Agent  │   │          │  │          │  │            │       │
  │  └────┬────┘   └─────┬────┘  └─────┬────┘  └─────┬──────┘       │
  │       │              │              │              │               │
  │  ┌────▼──────────────▼──────────────▼──────────────▼───────────┐  │
  │  │                       Tools Layer                            │  │
  │  │  crm_tool · property_store · calendar_tool · notification   │  │
  │  └──────────────────────────────────────────────────────────────┘  │
  │                            │                                        │
  │                     Secret Manager                                  │
  │                     gemini-api-key  ◄── injected via secretKeyRef  │
  └────────────────────────────┼────────────────────────────────────────┘
                               │ HTTPS  X-goog-api-key header
                               ▼
             ┌──────────────────────────────────────┐
             │  generativelanguage.googleapis.com   │
             │  model: gemini-flash-latest          │
             │  project: gen-lang-client-0300667287 │
             └──────────────────────────────────────┘
```

---

## CI/CD Pipeline

```
  git push → main
       │
       ▼
  ┌─────────────────────────────────────────────────────────────┐
  │              GitHub Actions  (deploy-dev.yml)               │
  │                                                             │
  │  Job 1: Unit Tests                                          │
  │  ├── pytest tests/test_tools.py                             │
  │  └── uses: GOOGLE_API_KEY secret                           │
  │                         │ pass                              │
  │  Job 2: Build & Push    ▼                                   │
  │  ├── google-github-actions/auth (GCP_SA_KEY)                │
  │  ├── docker build                                           │
  │  └── docker push → Artifact Registry                       │
  │        us-central1-docker.pkg.dev/                         │
  │        gen-lang-client-0300667287/letting-copilot/          │
  │                         │ pass                              │
  │  Job 3: Terraform Deploy▼                                   │
  │  ├── terraform init  (GCS backend)                          │
  │  ├── terraform apply -var image_tag=${SHA::8}               │
  │  └── smoke test: curl /health → assert status=ok            │
  └─────────────────────────────────────────────────────────────┘
```

---

## GCP Infrastructure (Terraform)

```
  gen-lang-client-0300667287  (lettingcopilot)
  │
  ├── terraform/bootstrap/          ← run once, local state
  │   ├── GCS Bucket                  gen-lang-client-0300667287-tfstate
  │   │   └── versioning enabled, lifecycle: keep 10 versions
  │   ├── Artifact Registry           us-central1 / letting-copilot (DOCKER)
  │   └── APIs enabled:               run, artifactregistry, cloudbuild,
  │                                   secretmanager, storage, iam
  │
  └── terraform/dev/                ← every deploy, remote GCS state
      │   backend: gcs              bucket = *-tfstate
      │                             prefix = letting-copilot/dev
      │
      ├── Secret Manager
      │   └── gemini-api-key        injected into Cloud Run via secretKeyRef
      │                             never stored as plain env var
      │
      ├── Service Account           letting-copilot-runner@...
      │   └── roles:                secretmanager.secretAccessor
      │                             logging.logWriter
      │
      ├── Cloud Run v2              letting-copilot  (us-central1)
      │   ├── image:                AR / letting-copilot:${git_sha}
      │   ├── scaling:              min=0  max=3
      │   ├── resources:            cpu=1  memory=512Mi
      │   ├── env (plain):          ENVIRONMENT, AVA_MODEL, GOOGLE_GENAI_USE_VERTEXAI
      │   └── env (secret ref):     GOOGLE_API_KEY, GOOGLE_GENAI_API_KEY
      │                             └── source: Secret Manager gemini-api-key
      │
      └── IAM                       allUsers → roles/run.invoker  (public POC)
```

---

## Agent Flow

```
  Enquiry arrives (chat UI / API)
         │
         ▼
  OrchestratorAgent
         │
         ├──► QualificationAgent
         │         asks: move date · budget · employment · name/contact
         │         calls: save_applicant()
         │
         ├── budget fits property?
         │       NO ──► MatchingAgent
         │                   calls: search_properties()
         │                   presents up to 3 alternatives
         │
         ▼
  BookingAgent
         │  calls: get_available_slots()
         │  calls: book_slot()
         │  confirms datetime + address
         │
         ▼
  FollowupAgent
         │  calls: send_reminder()    ← pre-viewing
         │  calls: send_followup()    ← post-viewing feedback
         │  calls: save_offer()       ← if offer made
         │
         ▼
  Human negotiator takes over
```

---

## Project Structure

```
LettingCopilot/
├── letting_copilot/
│   ├── agents/
│   │   ├── orchestrator.py       # root_agent — entry point, routes flow
│   │   ├── qualification.py      # income, employment, move date, contact
│   │   ├── matching.py           # property search & alternatives
│   │   ├── booking.py            # calendar slots & confirmation
│   │   └── followup.py           # reminders, feedback, offers
│   ├── tools/
│   │   ├── property_store.py     # in-memory portfolio (POC)
│   │   ├── calendar_tool.py      # slots & booking (in-memory)
│   │   ├── crm_tool.py           # applicant records & offers
│   │   └── notification_tool.py  # reminders & follow-ups (logged)
│   ├── app.py                    # FastAPI + ADK runner
│   └── config.py                 # env-based config, loads .env
├── ui/
│   └── index.html                # chat UI (served at /)
├── data/
│   └── properties.json           # seed property portfolio (5 London props)
├── terraform/
│   ├── bootstrap/                # GCS bucket + Artifact Registry (run once)
│   │   ├── main.tf
│   │   └── variables.tf
│   └── dev/                      # Cloud Run + IAM + Secret Manager
│       ├── main.tf               # remote GCS backend
│       └── variables.tf
├── tests/
│   ├── test_tools.py             # unit tests — no GCP needed
│   └── test_api.py               # FastAPI endpoint tests
├── scripts/
│   └── deploy.sh                 # local deploy: bootstrap→build→push→apply
├── .github/workflows/
│   └── deploy-dev.yml            # CI: test → build/push → terraform deploy
├── Dockerfile
├── docker-compose.yml            # local dev with docker
└── .env                          # local secrets (gitignored)
```

---

## Quick Start (Local)

```bash
git clone https://github.com/anoopkum/LettingCopilot.git
cd LettingCopilot

cp .env.example .env
# Add your GOOGLE_API_KEY from https://aistudio.google.com/apikey

pip install -r requirements.txt
python main.py
open http://localhost:8080
```

Or with Docker:

```bash
docker-compose up --build
open http://localhost:8080
```

---

## Cloud Deployment

### First time (bootstrap — run once)

```bash
gcloud auth login loganoop@gmail.com
gcloud auth application-default login
gcloud config set project gen-lang-client-0300667287

cd terraform/bootstrap
terraform init
terraform apply   # creates GCS state bucket + Artifact Registry
```

### Every deploy

```bash
bash scripts/deploy.sh          # build → push → terraform apply
```

Or just push to `main` — GitHub Actions handles it automatically.

---

## GitHub Actions Secrets Required

| Secret | Description |
|---|---|
| `GCP_SA_KEY` | Service account JSON key (`letting-copilot-ci@...`) |
| `GOOGLE_API_KEY` | Gemini API key (used in unit tests) |
| `GEMINI_API_KEY` | Gemini API key (stored in Secret Manager via Terraform) |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_API_KEY` | Yes | — | Gemini API key |
| `GOOGLE_GENAI_USE_VERTEXAI` | No | `false` | Use Vertex AI instead of AI Studio |
| `AVA_MODEL` | No | `gemini-flash-latest` | Gemini model to use |
| `ENVIRONMENT` | No | `dev` | Runtime environment label |
| `PORT` | No | `8080` | Server port |

---

## Security Notes

| Concern | How handled |
|---|---|
| API key in Cloud Run | Injected via `secretKeyRef` — never a plain env var |
| API key in CI logs | GitHub masks `GEMINI_API_KEY` — shows `***` in logs |
| API key in Terraform state | ⚠️ Stored in GCS state (POC acceptable — fix for prod: pre-create secret outside TF) |
| API key in repo | `.gitignore` covers `.env` and `terraform.tfvars` |
| Cloud Run access | Public (`allUsers`) for POC — add IAP or API key for prod |

---

## Infrastructure Free Tier Usage

| Service | Free Limit | Expected Usage |
|---|---|---|
| Cloud Run | 2M req/month · 180k vCPU-sec | Well under |
| Artifact Registry | 0.5 GB storage | ~200 MB per image |
| Secret Manager | 6 secret versions/month free | 1 version |
| GCS (state bucket) | 5 GB free | < 1 MB |
| Gemini API | 1,500 req/day (gemini-flash-latest) | POC usage |

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for all errors encountered and their fixes.

---

## Links

- **Live app:** https://letting-copilot-ruzwhtmsaq-uc.a.run.app
- **GitHub:** https://github.com/anoopkum/LettingCopilot
- **GCP project:** `gen-lang-client-0300667287` (lettingcopilot)
- **CI pipeline:** https://github.com/anoopkum/LettingCopilot/actions
