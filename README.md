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
  ┌──────────────────────────────────────────────────────────────────────────┐
  │                       Google Cloud Run (dev)                             │
  │                       us-central1 · 0–3 instances · 512Mi               │
  │                       SA: letting-copilot-runner@...                    │
  │                                                                          │
  │  ┌───────────────────────────────────────────────────────────────────┐   │
  │  │  FastAPI  (port 8080)                                             │   │
  │  │                                                                   │   │
  │  │  Public:                      JWT-protected:                      │   │
  │  │  GET  /health                 POST /chat      ← ADK orchestrator  │   │
  │  │  POST /auth/token             POST /workflow  ← LangGraph         │   │
  │  │  GET  /.well-known/agent.json POST /a2a       ← A2A JSON-RPC      │   │
  │  │                               GET  /properties                    │   │
  │  └────────────────────┬──────────────────────────────────────────────┘   │
  │                       │                                                   │
  │  ┌────────────────────▼──────────────────────────────────────────────┐   │
  │  │  JWT Auth  (auth/jwt_handler.py)                                  │   │
  │  │  HS256 · JWT_SECRET from Secret Manager · 24h expiry             │   │
  │  └────────────────────┬──────────────────────────────────────────────┘   │
  │          ┌────────────┴──────────────┐                                   │
  │          │ /chat                     │ /workflow                          │
  │          ▼                           ▼                                   │
  │  ┌──────────────────┐     ┌─────────────────────────────────────────┐   │
  │  │  ADK Runner      │     │  LangGraph StateGraph (workflow/)        │   │
  │  │  before_model_cb │     │  LettingsState (TypedDict)               │   │
  │  │  after_model_cb  │     │                                         │   │
  │  └────────┬─────────┘     │  qualify ──► match? ──► book ──► END   │   │
  │           │               │  (conditional edges, single-turn/req)   │   │
  │  ┌────────▼─────────┐     └──────────────┬──────────────────────────┘   │
  │  │ OrchestratorAgent│                    │ node_runner.run_adk_agent()   │
  │  │ (root_agent)     │                    │ bridges ADK ↔ LangGraph       │
  │  │ AgentTool x4     │◄───────────────────┘                              │
  │  └──┬───┬───┬───┬───┘                                                   │
  │     │   │   │   │  ADK AgentTool dispatch                               │
  │  ┌──▼─┐ │ ┌─▼─┐ │  ┌──────┐  ┌──────────┐                             │
  │  │Qual│ │ │Mat│ │  │Book  │  │FollowUp  │   ← Sub-agents               │
  │  │ify │ │ │ch │ │  │      │  │          │                              │
  │  └──┬─┘ │ └─┬─┘ │  └──┬───┘  └────┬─────┘                             │
  │     └───┴───┴───┴─────┴────────────┘                                   │
  │                       │                                                  │
  │  ┌────────────────────▼──────────────────────────────────────────────┐  │
  │  │  Tools Layer                                                       │  │
  │  │  crm_tool · property_store · calendar_tool · notification_tool   │  │
  │  └───────────────────────────────────────────────────────────────────┘  │
  │                                                                          │
  │  ┌───────────────────────────────────────────────────────────────────┐  │
  │  │  Secret Manager                                                    │  │
  │  │  gemini-api-key  ──► GOOGLE_API_KEY / GOOGLE_GENAI_API_KEY        │  │
  │  │  jwt-secret      ──► JWT_SECRET                 (secretKeyRef)    │  │
  │  └───────────────────────────────────────────────────────────────────┘  │
  └──────────────────────────────────────┬───────────────────────────────────┘
                                         │ HTTPS  X-goog-api-key header
                                         ▼
                       ┌──────────────────────────────────────┐
                       │  generativelanguage.googleapis.com   │
                       │  model: gemini-flash-latest          │
                       │  project: gen-lang-client-0300667287 │
                       └──────────────────────────────────────┘
```

---

## A2A Protocol

LettingCopilot exposes the [Agent-to-Agent (A2A)](https://google.github.io/A2A/) protocol, enabling external orchestrators to call it as a microservice.

```
GET  /.well-known/agent.json       AgentCard — skills, auth, capabilities
POST /a2a                          JSON-RPC 2.0 task endpoint (JWT required)
  methods:
    tasks/send    → run agent, returns completed task + artifacts
    tasks/get     → retrieve task by ID
    tasks/cancel  → cancel in-progress task
```

**Skills declared in AgentCard:**

| Skill ID | Description |
|---|---|
| `qualify_applicant` | Collect name, budget, employment, move date |
| `match_property` | Search portfolio for suitable properties |
| `book_viewing` | Check slots and confirm viewing appointment |

---

## LangGraph Workflow

The `/workflow` endpoint runs a typed `StateGraph` across the lettings pipeline.

```
LettingsState (TypedDict)
  messages: Annotated[list[BaseMessage], add_messages]
  stage: "start" | "qualifying" | "matching" | "booking" | "followup" | "complete"
  qualified: bool
  needs_matching: bool
  viewing_booked: bool
  + applicant fields (name, budget, employment, move_date, contact)
  + property / booking IDs

Graph:
  qualify_node
      │
      ├── needs_matching=True  ──► match_node ──► book_node ──► followup_node ──► END
      │
      └── needs_matching=False ──► END  (single-turn — caller drives next step)

Each node calls run_adk_agent(agent, message, state) which:
  1. Creates/reuses InMemorySessionService keyed by session_id
  2. Runs ADK Runner.run_async() and extracts final response
  3. Returns text to the LangGraph node to append as AIMessage
```

---

## JWT Authentication

All `/chat`, `/workflow`, `/a2a`, and `/properties` endpoints require a Bearer token.

```bash
# 1. Get a token
curl -X POST https://letting-copilot-ruzwhtmsaq-uc.a.run.app/auth/token \
  -H "Content-Type: application/json" \
  -d '{"client_id": "myapp", "client_secret": "any-non-empty-value"}'

# 2. Use it
curl -X POST https://letting-copilot-ruzwhtmsaq-uc.a.run.app/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hi, I want to view a flat"}'
```

- Algorithm: HS256
- Secret: `JWT_SECRET` from Secret Manager (never a plain env var)
- Expiry: 24h (configurable via `JWT_EXPIRE_SECONDS`)
- Subject: `client_id` from the token request

---

## CI/CD Pipeline

```
  git push → main
       │
       ▼
  ┌──────────────────────────────────────────────────────────────┐
  │              GitHub Actions  (deploy-dev.yml)                │
  │                                                              │
  │  Job 1: Unit Tests                                           │
  │  ├── pytest tests/test_tools.py  (12 tests)                 │
  │  └── uses: GOOGLE_API_KEY secret                            │
  │                         │ pass                               │
  │  Job 2: Build & Push    ▼                                    │
  │  ├── Read VERSION file  →  semver = 0.1.0                   │
  │  ├── Compute tags:                                           │
  │  │     v0.1.0-<sha8>   ← production pin (deployed to CR)    │
  │  │     v0.1.0          ← semver float                       │
  │  │     sha-<sha8>      ← git sha                            │
  │  │     latest          ← floating (never deployed to CR)    │
  │  ├── docker build  (OCI labels: version, revision, source)  │
  │  └── docker push all 4 tags → Artifact Registry             │
  │                         │ pass                               │
  │  Job 3: Terraform Deploy▼                                    │
  │  ├── terraform init  (GCS remote backend)                    │
  │  ├── terraform apply -var image_tag=v0.1.0-<sha8>           │
  │  │     (pinned tag — never :latest on Cloud Run)             │
  │  └── smoke test: curl /health → assert status=ok            │
  └──────────────────────────────────────────────────────────────┘
```

---

## GCP Infrastructure (Terraform)

```
  gen-lang-client-0300667287  (lettingcopilot)
  │
  ├── terraform/bootstrap/          ← run once, local state
  │   ├── GCS Bucket                  gen-lang-client-0300667287-tfstate
  │   │   └── versioning, lifecycle: keep 10 versions
  │   ├── Artifact Registry           us-central1 / letting-copilot (DOCKER)
  │   └── APIs enabled:               run, artifactregistry, secretmanager,
  │                                   storage, iam, cloudbuild
  │
  └── terraform/dev/                ← every deploy, remote GCS state
      │   backend: gcs              bucket = *-tfstate, prefix = letting-copilot/dev
      │
      ├── Secret Manager
      │   ├── gemini-api-key        → GOOGLE_API_KEY / GOOGLE_GENAI_API_KEY
      │   └── jwt-secret            → JWT_SECRET
      │                               both injected via secretKeyRef, never plain env
      │
      ├── Service Account           letting-copilot-runner@...
      │   └── roles:                secretmanager.secretAccessor
      │                             logging.logWriter
      │
      ├── Cloud Run v2              letting-copilot  (us-central1)
      │   ├── image:                AR / letting-copilot:v<semver>-<sha>
      │   ├── timeout:              300s
      │   ├── scaling:              min=0  max=3
      │   ├── resources:            cpu=1  memory=512Mi
      │   ├── env (plain):          ENVIRONMENT, AVA_MODEL, GOOGLE_GENAI_USE_VERTEXAI
      │   └── env (secret ref):     GOOGLE_API_KEY, GOOGLE_GENAI_API_KEY, JWT_SECRET
      │
      └── IAM                       allUsers → roles/run.invoker  (public POC)
```

---

## Agent Flow

```
  Enquiry arrives (/chat or /a2a)
         │
         ▼
  OrchestratorAgent  (ADK before_model_callback → logs token count)
         │           (ADK after_model_callback  → logs response preview)
         │
         │  calls AgentTool(qualification_agent)
         ├──► QualificationAgent
         │         asks: move date · budget · employment · name/contact
         │         calls: save_applicant()
         │
         │  calls AgentTool(matching_agent)  [if budget doesn't fit]
         ├──► MatchingAgent
         │         calls: search_properties(max_rent, bedrooms, area)
         │         presents up to 3 alternatives
         │
         │  calls AgentTool(booking_agent)
         ├──► BookingAgent
         │         calls: get_available_slots()
         │         calls: book_slot()
         │         confirms datetime + address
         │
         │  calls AgentTool(followup_agent)
         └──► FollowupAgent
                   calls: send_reminder()    ← pre-viewing
                   calls: send_followup()    ← post-viewing feedback
                   calls: save_offer()       ← if offer made
```

---

## Project Structure

```
LettingCopilot/
├── letting_copilot/
│   ├── agents/
│   │   ├── orchestrator.py       # root_agent — AgentTool x4, ADK callbacks
│   │   ├── qualification.py      # income, employment, move date, contact
│   │   ├── matching.py           # property search & alternatives
│   │   ├── booking.py            # calendar slots & confirmation
│   │   └── followup.py           # reminders, feedback, offers
│   ├── a2a/
│   │   ├── card.py               # A2A AgentCard (3 skills)
│   │   └── router.py             # JSON-RPC tasks/send, tasks/get, tasks/cancel
│   ├── auth/
│   │   └── jwt_handler.py        # HS256 create_token / verify_token
│   ├── workflow/
│   │   ├── graph.py              # LangGraph StateGraph — LettingsState TypedDict
│   │   └── node_runner.py        # ADK ↔ LangGraph bridge (run_adk_agent)
│   ├── tools/
│   │   ├── property_store.py     # in-memory portfolio (POC)
│   │   ├── calendar_tool.py      # slots & booking (in-memory)
│   │   ├── crm_tool.py           # applicant records & offers
│   │   └── notification_tool.py  # reminders & follow-ups (logged)
│   ├── app.py                    # FastAPI + ADK runner + LangGraph + A2A router
│   └── config.py                 # env-based config, loads .env
├── ui/
│   └── index.html                # chat UI — auto-obtains JWT, retries on 401
├── data/
│   └── properties.json           # seed portfolio (5 London properties)
├── terraform/
│   ├── bootstrap/                # GCS bucket + Artifact Registry (run once)
│   └── dev/                      # Cloud Run + IAM + Secret Manager (remote state)
├── tests/
│   ├── test_tools.py             # 12 unit tests — no GCP needed
│   └── test_api.py               # FastAPI endpoint tests
├── .github/workflows/
│   └── deploy-dev.yml            # CI: test → build (semver+sha tags) → terraform deploy
├── VERSION                       # semver — bump to cut a new release (e.g. 0.2.0)
├── Dockerfile
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
gcloud auth login
gcloud auth application-default login
gcloud config set project gen-lang-client-0300667287

cd terraform/bootstrap
terraform init && terraform apply
```

### Every deploy — just push to main

```bash
git push origin main   # triggers GitHub Actions automatically
```

---

## GitHub Actions Secrets Required

| Secret | Description |
|---|---|
| `GCP_SA_KEY` | Service account JSON key (`letting-copilot-ci@...`) |
| `GOOGLE_API_KEY` | Gemini API key (used in unit tests) |
| `GEMINI_API_KEY` | Gemini API key (stored in Secret Manager via Terraform) |
| `JWT_SECRET` | HS256 JWT signing secret (stored in Secret Manager via Terraform) |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_API_KEY` | Yes | — | Gemini API key |
| `GOOGLE_GENAI_USE_VERTEXAI` | No | `false` | Use Vertex AI instead of AI Studio |
| `AVA_MODEL` | No | `gemini-flash-latest` | Gemini model |
| `JWT_SECRET` | No | `lettingcopilot-dev-secret-change-in-prod` | HS256 signing key |
| `JWT_EXPIRE_SECONDS` | No | `86400` | Token lifetime (seconds) |
| `ENVIRONMENT` | No | `dev` | Runtime label |
| `PORT` | No | `8080` | Server port |

---

## Security Notes

| Concern | How handled |
|---|---|
| Gemini API key in Cloud Run | `secretKeyRef` → Secret Manager — never a plain env var |
| JWT signing secret | `secretKeyRef` → Secret Manager — never a plain env var |
| API keys in CI logs | GitHub masks `GEMINI_API_KEY` and `JWT_SECRET` — shows `***` |
| API key in Terraform state | ⚠️ Stored in GCS state (POC acceptable — fix for prod: pre-create secret outside TF) |
| Secrets in repo | `.gitignore` covers `.env` and `terraform.tfvars` |
| Cloud Run access | Public (`allUsers`) for POC — add IAP or OAuth for prod |
| Endpoint auth | All `/chat`, `/workflow`, `/a2a`, `/properties` require valid JWT |

---

## Infrastructure Free Tier Usage

| Service | Free Limit | Expected Usage |
|---|---|---|
| Cloud Run | 2M req/month · 180k vCPU-sec | Well under |
| Artifact Registry | 0.5 GB storage | ~200 MB per image |
| Secret Manager | 6 secret versions/month free | 2 versions |
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
