# LettingCopilot

An AI lettings agent that guides renters from first enquiry to confirmed viewing — entirely through conversation. No forms, no buttons, no handoffs.

**Live demo:** https://letting-copilot-913660829167.us-central1.run.app

---

## How It Works

A renter opens the chat and talks to **Ava**, the AI agent. Ava handles everything:

```
Qualify  →  Match  →  Book  →  Confirm
```

Each stage runs automatically — Ava never waits for a human to trigger the next step.

---

## The Conversation Flow

```
Renter: "Hi, I'm looking for a flat in South London"
                        ↓
        ┌───────────────────────────────┐
        │  QUALIFY                      │
        │  Ava collects 5 things:       │
        │  • Move date                  │
        │  • Monthly budget             │
        │  • Employment status          │
        │  • Guarantor (if needed)      │
        │  • Name + email               │
        └──────────────┬────────────────┘
                       ↓  (all 5 collected → automatic)
        ┌───────────────────────────────┐
        │  MATCH                        │
        │  Searches properties by:      │
        │  • Budget (hard filter)       │
        │  • Bedrooms (hard filter)     │
        │  • Natural language ranking   │
        │    via Pinecone vector search │
        │  Presents up to 3 options     │
        └──────────────┬────────────────┘
                       ↓  (renter picks one → automatic)
        ┌───────────────────────────────┐
        │  BOOK                         │
        │  Checks real Google Calendar  │
        │  availability, offers 2–3     │
        │  slots, renter picks one,     │
        │  creates calendar event       │
        └──────────────┬────────────────┘
                       ↓  (booking confirmed → automatic)
        ┌───────────────────────────────┐
        │  CONFIRM                      │
        │  Sends HTML email via         │
        │  SendGrid with property +     │
        │  viewing details              │
        └───────────────────────────────┘
```

---

## Architecture

```
                    ┌─────────────────┐
                    │   Browser UI    │
                    │  (index.html)   │
                    └────────┬────────┘
                             │ Google Sign-In
                             ▼
                    ┌─────────────────┐
                    │    FastAPI      │◄── /health
                    │   (app.py)      │◄── /auth/google
                    └────────┬────────┘◄── /chat
                             │ JWT verified
                             ▼
               ┌─────────────────────────────┐
               │     Input Guardrails        │
               │  blocks injection, gibberish│
               │  off-topic, empty messages  │
               └──────────────┬──────────────┘
                              │ clean input
                              ▼
               ┌─────────────────────────────┐
               │      Ava (root_agent)       │
               │   Google ADK 2.2 + Gemini   │
               │                             │
               │  All tools run directly     │
               │  on the agent — no          │
               │  sub-agents (see note)      │
               └──┬──────┬──────┬──────┬─────┘
                  │      │      │      │
           ┌──────┘  ┌───┘  ┌───┘  ┌──┘
           ▼         ▼      ▼      ▼
        CRM      Pinecone  Google  SendGrid
     (applicant  (property  Calendar (email
      records)    search)   (slots +  confirm)
                            booking)
                              │
               ┌──────────────┴──────────────┐
               │      Output Guardrails       │
               │  redacts secrets/tracebacks  │
               │  handles empty LLM responses │
               └─────────────────────────────┘
```

> **Why no sub-agents?** In ADK 2.2, delegating to a sub-agent ends the conversation turn. The pipeline would stop after qualification and wait for the user to send another message. All tools live directly on `root_agent` so the full qualify → match → book → confirm flow runs in one continuous turn.

---

## Key Components

| Component | What it does |
|-----------|-------------|
| **Ava (orchestrator)** | The AI agent. Runs the full pipeline in one turn using Gemini Flash |
| **Pinecone** | Semantic vector search for properties. Budget/bedroom filters are exact; natural language query ranks results by relevance |
| **Google Calendar** | Checks real freebusy availability and creates calendar events on booking |
| **SendGrid** | Sends HTML confirmation emails after booking. Falls back to log-only if not configured |
| **Google OAuth** | Sign-in via Google. Issues a short-lived JWT for all API calls |
| **Input guardrails** | Blocks prompt injection, gibberish, off-topic queries before they reach the LLM |
| **Output guardrails** | Redacts API keys or tracebacks that leak into LLM responses |
| **LangGraph** | Alternative pipeline endpoint (`/workflow`) using a typed state machine |
| **Terraform** | Manages all GCP infrastructure. State stored remotely in GCS — never local |
| **GitHub Actions** | CI/CD: test → build (Docker layer cache) → deploy on every push to `main` |

---

## Tech Stack

```
AI          Google ADK 2.2 + Gemini Flash (free tier)
API         FastAPI + Uvicorn
Search      Pinecone (integrated inference, no local embeddings)
Calendar    Google Calendar API (service account)
Email       SendGrid REST API
Auth        Google OAuth 2.0 → JWT (PyJWT HS256)
Pipeline    LangGraph StateGraph
Hosting     GCP Cloud Run (scales to 0, max 3 instances)
IaC         Terraform 1.6 (GCS remote state)
CI/CD       GitHub Actions
Secrets     GCP Secret Manager (secretKeyRef — never plain env vars)
```

---

## Project Layout

```
LettingCopilot/
├── letting_copilot/
│   ├── agents/orchestrator.py    ← Ava — all tools, full pipeline
│   ├── tools/
│   │   ├── property_store.py     ← Pinecone search + in-memory fallback
│   │   ├── calendar_tool.py      ← real slots + booking
│   │   ├── notification_tool.py  ← SendGrid emails
│   │   └── crm_tool.py           ← applicant + offer records
│   ├── guardrails/
│   │   ├── input_guard.py        ← blocks bad input before LLM
│   │   └── output_guard.py       ← cleans LLM response before user sees it
│   ├── auth/jwt_handler.py       ← Google OAuth verify + JWT issue
│   ├── workflow/graph.py         ← LangGraph pipeline (alt endpoint)
│   └── app.py                    ← FastAPI + ADK runner + all routes
├── data/properties.json          ← seed listings (feeds Pinecone on startup)
├── ui/index.html                 ← single-page chat UI
├── terraform/dev/                ← Cloud Run + Secret Manager + IAM
├── tests/                        ← 46 unit tests, no GCP calls needed
├── .github/workflows/deploy-dev.yml
├── Dockerfile
└── VERSION                       ← semver, image tagged v<semver>-<sha8>
```

---

## Running Locally

```bash
git clone https://github.com/anoopkum/LettingCopilot.git
cd LettingCopilot
pip install -r requirements.txt

export GOOGLE_API_KEY=your_gemini_key
python main.py
# → http://localhost:8080
```

Pinecone, SendGrid, and Google Calendar are all optional. Without their keys, Ava uses in-memory property search, mock calendar slots, and logs emails instead of sending them. Everything still works end-to-end.

```bash
pytest tests/ -v   # 46 tests, no GCP account needed
```

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GOOGLE_API_KEY` | Yes | Gemini API key |
| `JWT_SECRET` | Yes | JWT signing secret |
| `PINECONE_API_KEY` | No | Vector property search (falls back to in-memory) |
| `PINECONE_INDEX` | No | Index name (default: `lettingcopilot-properties`) |
| `GOOGLE_OAUTH_CLIENT_ID` | No | Google Sign-In (falls back to dev JWT) |
| `GOOGLE_CALENDAR_ID` | No | Real calendar slots (falls back to mock) |
| `GOOGLE_CALENDAR_SA_JSON` | No | Service account for Calendar API |
| `SENDGRID_API_KEY` | No | Real emails (falls back to log-only) |
| `SENDGRID_FROM_EMAIL` | No | Verified sender address in SendGrid |

---

## CI/CD

```
push to main
    │
    ├─ 1. Test       pytest (46 tests)
    ├─ 2. Build      docker buildx + GitHub Actions layer cache
    │                tagged: v0.1.0-<sha8>  (pinned, never :latest on Cloud Run)
    └─ 3. Deploy     terraform apply → Cloud Run → smoke test /health
```

Secrets never touch the shell. They flow: **GitHub Secrets → `TF_VAR_*` env → Terraform → Secret Manager → Cloud Run `secretKeyRef`**.

---

## Links

- **Live app:** https://letting-copilot-913660829167.us-central1.run.app
- **CI runs:** https://github.com/anoopkum/LettingCopilot/actions
- **Troubleshooting:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
