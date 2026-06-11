# LettingCopilot

AI-powered lettings agent that handles the full rental journey — from first enquiry to confirmed viewing — without any manual handoffs. Built on Google ADK 2.2.0 + Gemini Flash, deployed on GCP Cloud Run via Terraform with GitHub Actions CI/CD.

**Live:** `https://letting-copilot-913660829167.us-central1.run.app`

---

## What It Does

A prospective tenant opens the chat and Ava (the AI agent) runs the entire pipeline automatically in one continuous conversation:

```
Sign In → Qualify → Match → Book → Confirm
```

No buttons, no forms, no manual handoffs between stages.

---

## User Journey

### 1. Sign In
The user visits the app and signs in with Google. Google Sign-In (GIS) returns an `id_token` credential which is exchanged at `/auth/google` for a short-lived JWT. All subsequent requests use that JWT.

### 2. Qualify
Ava collects five details conversationally, one at a time:

- Preferred move date
- Monthly budget (PCM)
- Employment status
- Guarantor availability (if not full-time employed)
- Full name and contact email

Ava validates inline — an unrecognisable date or a budget typed as words triggers a gentle re-ask, not an error. Short replies like "no", "yes", "ok" pass through normally.

### 3. Match
As soon as all five details are collected, Ava saves the applicant to the CRM and immediately calls `search_properties` without waiting for a prompt. Pinecone returns semantically ranked properties filtered by budget and bedroom count. Ava presents up to three options conversationally.

### 4. Book
Once the applicant picks a property, Ava immediately calls `get_available_slots`. If real Google Calendar slots are available she offers two or three choices. The applicant picks one, Ava calls `book_slot` and a calendar event is created on the agency calendar.

### 5. Confirm
Ava calls `send_reminder` with the applicant's email address. SendGrid sends an HTML confirmation email with the property address, date and time. If the send fails, Ava says so honestly — it never claims to have sent an email unless `sent=True` is returned.

---

## Architecture

```
Browser
  │  Google Sign-In (GIS + One Tap)
  ▼
FastAPI (port 8080)
  ├── /auth/google  ──── verify id_token ──── issue JWT
  ├── /auth/config  ──── tells UI which auth mode is active
  ├── /health       ──── active features list
  │
  │  JWT (Bearer)
  ▼
┌──────────────────────────────────────────────────────┐
│               ADK Orchestrator                       │
│               ava_orchestrator (Gemini Flash)        │
│                                                      │
│  All 7 tools live directly on root_agent             │
│  (no sub-agents — sub-agents end the turn early)     │
│                                                      │
│  ┌─────────────────┐   ┌──────────────────────────┐  │
│  │  save_applicant │   │    search_properties     │  │
│  │     (CRM)       │   │  Pinecone semantic search│  │
│  └─────────────────┘   └──────────────────────────┘  │
│  ┌─────────────────┐   ┌──────────────────────────┐  │
│  │get_available_   │   │       book_slot          │  │
│  │    slots        │   │   Google Calendar API    │  │
│  │ Google Calendar │   └──────────────────────────┘  │
│  └─────────────────┘                                 │
│  ┌─────────────────┐   ┌──────────────────────────┐  │
│  │  send_reminder  │   │      send_followup       │  │
│  │   SendGrid      │   │       SendGrid           │  │
│  └─────────────────┘   └──────────────────────────┘  │
│  ┌─────────────────┐                                 │
│  │   save_offer    │                                 │
│  │     (CRM)       │                                 │
│  └─────────────────┘                                 │
└──────────────────────────────────────────────────────┘
         │            │             │
     Pinecone    Google Calendar  SendGrid
   (vector search)  (real slots)  (emails)
```

### Guardrails

**Input guard** (runs before the LLM, at FastAPI layer):
- Blocks empty input, pure symbols, prompt injection, off-topic domains (crypto, recipes, weather)
- Validates budget numbers and date hints when the message looks like a direct answer
- Short natural replies ("no", "ok", "yes", "thanks") always pass through

**Output guard** (runs after the LLM):
- Replaces empty LLM responses with a friendly retry prompt
- Redacts API key patterns, tracebacks, and raw JSON blobs before they reach the user

### Key Design Decisions

**All tools on root_agent, no sub-agents.** ADK sub-agent delegation ends the turn after the sub-agent responds — the pipeline would stall after qualification and never continue to matching. Flattening all tools onto `root_agent` lets the full flow run in one continuous turn driven by the LLM's tool-calling.

**Pinecone with in-memory fallback.** Properties are upserted as vectors (multilingual-e5-large via Pinecone integrated inference) on first cold start. Semantic search ranks by natural language query; metadata filters enforce hard budget and bedroom constraints. When `PINECONE_API_KEY` is unset, the code falls back to an exact in-memory filter — local dev and CI work without a Pinecone account.

**Secret Manager for all secrets.** Gemini key, JWT secret, SendGrid key, Pinecone key, and the Google Calendar service account JSON all live in Secret Manager, injected into Cloud Run via `secretKeyRef`. They never appear in source, CI logs, or plain env vars.

**Terraform remote state on GCS.** State stored at `gs://gen-lang-client-0300667287-tfstate/letting-copilot/dev`. State lock prevents concurrent applies from corrupting infrastructure — two simultaneous CI runs will fail gracefully rather than corrupt state.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Agent | Google ADK 2.2.0 + Gemini Flash (free tier) |
| API | FastAPI + Uvicorn |
| Pipeline | LangGraph StateGraph (qualify → match → book) |
| Vector Search | Pinecone (integrated inference, multilingual-e5-large) |
| Calendar | Google Calendar API (service account, freebusy + event create) |
| Email | SendGrid REST API (HTML + text, graceful fallback) |
| Auth | Google OAuth 2.0 → short-lived JWT (PyJWT HS256) |
| A2A | Google A2A protocol (agent-to-agent JSON-RPC) |
| Guardrails | Input (injection, gibberish, off-topic) + output (secret leak, traceback) |
| Container | Docker — `python:3.12-slim` |
| Hosting | GCP Cloud Run (serverless, 0–3 instances, 512Mi) |
| IaC | Terraform 1.6 (GCS remote state) |
| CI/CD | GitHub Actions — test → build (BuildKit cache) → deploy |
| Registry | GCP Artifact Registry |
| Secrets | GCP Secret Manager (`secretKeyRef`) |

---

## Project Structure

```
LettingCopilot/
├── letting_copilot/
│   ├── agents/
│   │   └── orchestrator.py       # root_agent — all tools, full pipeline instruction
│   ├── auth/
│   │   └── jwt_handler.py        # Google OAuth verify + JWT issue/verify
│   ├── guardrails/
│   │   ├── input_guard.py        # blocks injection/gibberish/off-topic
│   │   └── output_guard.py       # redacts secrets/tracebacks, empty fallback
│   ├── tools/
│   │   ├── property_store.py     # Pinecone search + in-memory fallback
│   │   ├── calendar_tool.py      # Google Calendar freebusy + event create
│   │   ├── notification_tool.py  # SendGrid email (reminder + followup)
│   │   └── crm_tool.py           # in-memory applicant + offer store
│   ├── workflow/
│   │   └── graph.py              # LangGraph StateGraph pipeline
│   ├── a2a/                      # A2A agent card + JSON-RPC router
│   ├── config.py                 # env-driven config (model, keys)
│   └── app.py                    # FastAPI app, ADK runner, all endpoints
├── data/
│   └── properties.json           # seed listings — feeds Pinecone on startup
├── ui/
│   └── index.html                # single-page chat UI (Google Sign-In + chat)
├── terraform/
│   └── dev/
│       ├── main.tf               # Cloud Run, Secret Manager, IAM
│       └── variables.tf
├── tests/
│   ├── test_tools.py             # 18 unit tests — no GCP calls
│   └── test_guardrails.py        # 28 guardrail tests
├── .github/workflows/
│   └── deploy-dev.yml            # test → build (BuildKit cache) → terraform deploy
├── Dockerfile                    # python:3.12-slim, layered for cache
├── requirements.txt
└── VERSION                       # semver — image tagged v<semver>-<sha8>
```

---

## CI/CD Pipeline

Every push to `main`:

```
git push → main
    │
    ▼
Job 1: Unit Tests
    pytest test_tools.py + test_guardrails.py (46 tests, no GCP calls)
    │
    ▼ pass
Job 2: Build & Push
    Compute tag: v<semver>-<sha8>  (e.g. v0.1.0-a1b2c3d4)
    docker buildx build --cache-from type=gha --cache-to type=gha,mode=max
    Push all tags: v0.1.0-<sha8> · v0.1.0 · sha-<sha8> · latest
    │
    ▼ pass
Job 3: Terraform Deploy
    terraform init  (GCS remote backend)
    terraform apply -var image_tag=v0.1.0-<sha8>
    smoke test: curl /health → assert status=ok
```

**Build caching:** Docker BuildKit stores layers in GitHub Actions cache. If `requirements.txt` is unchanged the pip install layer is a cache hit — build time drops from ~3 min to ~30s.

**Secrets flow:** GitHub Secrets → `TF_VAR_*` env vars → Terraform → Secret Manager → Cloud Run `secretKeyRef`

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | Public | Status, version, active features |
| `GET` | `/auth/config` | Public | OAuth mode + client ID for UI |
| `POST` | `/auth/google` | Public | Exchange Google id_token for JWT |
| `POST` | `/auth/token` | Public | Dev JWT (disabled when OAuth enabled) |
| `POST` | `/chat` | JWT | ADK orchestrator — main agent endpoint |
| `POST` | `/workflow` | JWT | LangGraph pipeline endpoint |
| `GET` | `/properties` | JWT | List all seed properties |
| `GET` | `/.well-known/agent.json` | Public | A2A agent card |
| `POST` | `/a2a` | JWT | A2A JSON-RPC (tasks/send, tasks/get, tasks/cancel) |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Yes | Gemini API key (AI Studio) |
| `JWT_SECRET` | Yes | HS256 signing secret (min 32 chars) |
| `PINECONE_API_KEY` | No | Enables Pinecone vector search (falls back to in-memory) |
| `PINECONE_INDEX` | No | Index name (default: `lettingcopilot-properties`) |
| `GOOGLE_CALENDAR_ID` | No | Calendar ID for real slot availability |
| `GOOGLE_CALENDAR_SA_JSON` | No | Service account JSON for Calendar API |
| `GOOGLE_OAUTH_CLIENT_ID` | No | Enables Google Sign-In (falls back to dev JWT) |
| `SENDGRID_API_KEY` | No | Enables real email confirmations (falls back to log-only) |
| `SENDGRID_FROM_EMAIL` | No | Verified sender address in SendGrid |

---

## GitHub Actions Secrets

| Secret | Description |
|--------|-------------|
| `GCP_SA_KEY` | Service account JSON for CI (Artifact Registry + Cloud Run + Terraform) |
| `GOOGLE_API_KEY` | Gemini key — used in unit tests |
| `GEMINI_API_KEY` | Gemini key — stored in Secret Manager via Terraform |
| `JWT_SECRET` | JWT signing secret — stored in Secret Manager |
| `GOOGLE_CALENDAR_SA_JSON` | Calendar service account JSON |
| `GOOGLE_CALENDAR_ID` | Calendar ID (e.g. `user@gmail.com`) |
| `GOOGLE_OAUTH_CLIENT_ID` | OAuth client ID |
| `SENDGRID_API_KEY` | SendGrid key |
| `SENDGRID_FROM_EMAIL` | Verified sender address |
| `PINECONE_API_KEY` | Pinecone key |
| `PINECONE_INDEX` | Pinecone index name |

---

## Local Development

```bash
git clone https://github.com/anoopkum/LettingCopilot.git
cd LettingCopilot

pip install -r requirements.txt -r requirements-dev.txt

# Minimum config — only Gemini key needed to run locally
export GOOGLE_API_KEY=your_key_here

python main.py
# → http://localhost:8080
```

Pinecone, SendGrid, and Google Calendar are all optional locally. Without their keys the agent uses in-memory property search, mock calendar slots, and log-only email notifications.

```bash
# Run tests (no GCP calls needed)
pytest tests/ -v
```

---

## GCP Resources

| Resource | Name |
|----------|------|
| Project | `gen-lang-client-0300667287` |
| Region | `us-central1` |
| Cloud Run service | `letting-copilot` |
| Artifact Registry repo | `letting-copilot` |
| Service Account | `lettingcopilot-runner` |
| TF State Bucket | `gen-lang-client-0300667287-tfstate` |
| Calendar SA | `lettingcopilot-calendar@gen-lang-client-0300667287.iam.gserviceaccount.com` |

---

## Links

- **Live app:** https://letting-copilot-913660829167.us-central1.run.app
- **GitHub:** https://github.com/anoopkum/LettingCopilot
- **CI pipeline:** https://github.com/anoopkum/LettingCopilot/actions
- **Troubleshooting:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
