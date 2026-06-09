# LettingCopilot

AI-powered lettings qualification and booking agent built with **Google ADK** + **Gemini API**.

Handles the full journey from first enquiry to viewing booked — qualification, property matching, calendar booking, reminders, and offer collection.

---

## Architecture

```
                        ┌─────────────────────────────────────────────────────┐
                        │                  LettingCopilot                     │
                        │                                                     │
  Applicant             │   FastAPI (port 8080)                               │
  ─────────             │   ┌─────────────────────────────────────────────┐   │
  Browser UI  ──HTTP──► │   │  POST /chat                                 │   │
  (ui/index.html)       │   │  GET  /health                               │   │
                        │   │  GET  /properties                           │   │
                        │   └──────────────┬──────────────────────────────┘   │
                        │                  │                                  │
                        │          ADK Runner (google-adk 2.2.0)              │
                        │          InMemorySessionService                     │
                        │                  │                                  │
                        │   ┌──────────────▼──────────────────────────────┐   │
                        │   │         OrchestratorAgent (root)            │   │
                        │   │   "ava_orchestrator"                        │   │
                        │   │   Routes enquiry through full journey       │   │
                        │   └──┬──────────┬──────────┬────────────┬───────┘   │
                        │      │          │          │            │           │
                        │  ┌───▼───┐  ┌───▼───┐  ┌───▼───┐  ┌───▼──────┐   │
                        │  │Qualif-│  │Match- │  │Booking│  │Follow-up │   │
                        │  │ication│  │ ing   │  │Agent  │  │Agent     │   │
                        │  │Agent  │  │Agent  │  │       │  │          │   │
                        │  └───┬───┘  └───┬───┘  └───┬───┘  └───┬──────┘   │
                        │      │          │          │            │           │
                        │  ┌───▼──────────▼──────────▼────────────▼───────┐   │
                        │  │                  Tools Layer                  │   │
                        │  │  crm_tool  │ property_store │ calendar_tool  │   │
                        │  │            │                │ notification   │   │
                        │  └───────────────────────────────────────────────┘   │
                        │                  │                                  │
                        └──────────────────┼──────────────────────────────────┘
                                           │ HTTPS
                                           ▼
                        ┌──────────────────────────────────────┐
                        │   generativelanguage.googleapis.com  │
                        │   Model: gemini-flash-latest         │
                        │   Auth:  X-goog-api-key header       │
                        └──────────────────────────────────────┘
```

---

## Agent Flow

```
  Enquiry arrives
       │
       ▼
  OrchestratorAgent ──► QualificationAgent
       │                      │ asks: move date, budget,
       │                      │ employment, name/contact
       │                      │ calls: save_applicant()
       │◄─────────────────────┘
       │
       ├── budget fits property? ──NO──► MatchingAgent
       │                                     │ calls: search_properties()
       │                                     │ presents alternatives
       │◄────────────────────────────────────┘
       │
       ▼
  BookingAgent
       │ calls: get_available_slots()
       │ calls: book_slot()
       │ confirms date/time to applicant
       │
       ▼
  FollowupAgent
       │ calls: send_reminder()     ← pre-viewing
       │ calls: send_followup()     ← post-viewing
       │ calls: save_offer()        ← if applicant makes offer
       │
       ▼
  Negotiator takes over (human handoff)
```

---

## Project Structure

```
LettingCopilot/
├── letting_copilot/
│   ├── agents/
│   │   ├── orchestrator.py     # root_agent — entry point
│   │   ├── qualification.py    # income, employment, move date
│   │   ├── matching.py         # property search & alternatives
│   │   ├── booking.py          # calendar slots & confirmation
│   │   └── followup.py         # reminders, feedback, offers
│   ├── tools/
│   │   ├── property_store.py   # in-memory property portfolio
│   │   ├── calendar_tool.py    # slots & booking (in-memory)
│   │   ├── crm_tool.py         # applicant records & offers
│   │   └── notification_tool.py # reminders & follow-ups
│   ├── app.py                  # FastAPI + ADK runner
│   └── config.py               # env-based config
├── ui/
│   └── index.html              # simple chat UI
├── data/
│   └── properties.json         # seed property portfolio
├── terraform/
│   └── dev/                    # Cloud Run + Artifact Registry IaC
│       ├── main.tf
│       └── variables.tf
├── tests/
│   ├── test_tools.py           # unit tests (no GCP needed)
│   └── test_api.py             # FastAPI endpoint tests
├── .github/workflows/
│   └── deploy-dev.yml          # CI: test → docker build → deploy
├── Dockerfile
├── docker-compose.yml
└── .env                        # local secrets (gitignored)
```

---

## Quick Start (Local)

```bash
# 1. Clone
git clone https://github.com/anoopkum/LettingCopilot.git
cd LettingCopilot

# 2. Set up env
cp .env.example .env
# Edit .env — add your GOOGLE_API_KEY from https://aistudio.google.com/apikey

# 3. Install deps
pip install -r requirements.txt

# 4. Run
python main.py

# 5. Open browser
open http://localhost:8080
```

Or with Docker:

```bash
docker-compose up --build
open http://localhost:8080
```

---

## Cloud Deployment (GCP Free Tier)

Target project: `gen-lang-client-0300667287` (`lettingcopilot`)

```bash
# Auth
gcloud auth login loganoop@gmail.com
gcloud auth application-default login
gcloud config set project gen-lang-client-0300667287

# Deploy (build → push → Cloud Run)
bash scripts/deploy.sh
```

### Infrastructure (Terraform)

| Resource | Config | Free tier limit |
|---|---|---|
| Cloud Run | 0–3 instances, 512Mi, 1 vCPU | 2M req/month |
| Artifact Registry | Docker repo `letting-copilot` | 0.5 GB |
| Cloud Build | On push to main | 120 min/day |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Yes | Gemini API key from AI Studio |
| `GOOGLE_GENAI_USE_VERTEXAI` | No | Set `false` for free-tier API |
| `AVA_MODEL` | No | Default: `gemini-flash-latest` |
| `ENVIRONMENT` | No | `dev` / `prod` |
| `PORT` | No | Default: `8080` |

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/test_tools.py -v
```

---

## GitHub

**Repo:** https://github.com/anoopkum/LettingCopilot
