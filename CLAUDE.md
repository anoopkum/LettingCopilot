# LettingCopilot — CLAUDE.md

## Project Overview

AI lettings agent called **Ava** — guides renters from first enquiry to confirmed viewing entirely through conversation. No forms, no buttons, no human handoffs.

**Pipeline:** `Qualify → Match → Book → Confirm`

**Live app:** https://letting-copilot-913660829167.us-central1.run.app  
**Repo:** https://github.com/anoopkum/LettingCopilot  
**Local root:** `/Users/anoo4413/Let-copilot/LettingCopilot/`

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI | Google ADK 2.2 + Gemini (`gemini-flash-latest`) |
| API | FastAPI + Uvicorn |
| Search | Pinecone (integrated inference, no local embeddings) |
| Calendar | Google Calendar API (service account) |
| Email | SendGrid REST API |
| Auth | Google OAuth 2.0 → JWT (PyJWT HS256) |
| Pipeline (alt) | LangGraph StateGraph |
| Hosting | GCP Cloud Run (scales to 0, max 3 instances) |
| IaC | Terraform 1.6 (GCS remote state) |
| CI/CD | GitHub Actions |
| Secrets | GCP Secret Manager (secretKeyRef — never plain env vars) |

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
│   ├── workflow/graph.py         ← LangGraph pipeline (alt endpoint /workflow)
│   └── app.py                    ← FastAPI + ADK runner + all routes
├── data/properties.json          ← seed listings (feeds Pinecone on startup)
├── ui/index.html                 ← single-page chat UI
├── terraform/dev/                ← Cloud Run + Secret Manager + IAM
├── tests/                        ← 46 unit tests, no GCP calls needed
├── .github/workflows/deploy-dev.yml
├── Dockerfile
├── docker-compose.yml
└── VERSION                       ← semver, image tagged v<semver>-<sha8>
```

---

## Agent Skills (Tools)

All tools attach directly to `root_agent` in `letting_copilot/agents/orchestrator.py`.

### 1. `property_store.py` — Property Search
- Searches Pinecone index `lettingcopilot-properties` using vector similarity
- Hard filters: budget (max rent) and bedrooms
- Natural language ranking for location/feature preferences
- Falls back to in-memory search if `PINECONE_API_KEY` is not set
- When `HOMEDATA_API_KEY` is set: merges live HomeData results (by postcode) and enriches all results with EPC, floor area, construction age
- **Namespace:** `__default__` (empty string `""` raises SDK error)

### 1a. `homedata_tool.py` — HomeData UK Property Data
- `get_property_details(uprn)` → fetches EPC rating, floor area, construction age, tenure, sold price history
- `search_by_postcode(postcode, max_rent, bedrooms)` → live property search, results normalised to LettingCopilot schema
- `enrich_property(prop)` → adds HomeData fields in-place if `uprn` present on the dict
- API base: `https://api.homedata.co.uk` — Auth: `Authorization: Api-Key <key>`
- All functions degrade gracefully (return `None`/`[]`) if `HOMEDATA_API_KEY` not set or API fails
- Uses `httpx` (already in requirements) — no extra dependency

### 2. `calendar_tool.py` — Viewing Slots & Booking
- Checks real Google Calendar freebusy availability via service account
- Offers 2–3 available slots to renter
- Creates calendar event on booking confirmation
- Falls back to mock slots if `GOOGLE_CALENDAR_ID` or SA JSON not set
- **Timezone:** `Europe/London` via `ZoneInfo("Europe/London")` — NOT `timezone.utc`

### 3. `notification_tool.py` — Email Confirmation
- Sends HTML confirmation email via SendGrid after booking
- Email includes property details + viewing time
- Falls back to log-only if `SENDGRID_API_KEY` not set

### 4. `crm_tool.py` — Applicant CRM
- Saves applicant records (name, email, budget, move date, employment) to Pinecone index `applicants`
- Returns `storage` field: `"pinecone"` or `"memory_only"`
- **Agent must check `storage` field** — never confirm "saved" to user on `memory_only`
- Env vars must be lazy-loaded inside functions, not at module import time

---

## Conversation Flow

Ava collects 5 things during qualification:
1. Move date
2. Monthly budget
3. Employment status
4. Guarantor availability (if needed)
5. Name + email

All 5 collected → auto-searches properties → renter picks one → checks calendar → renter picks slot → creates event → sends email.

---

## Architecture Decisions

### No sub-agents
In ADK 2.2, delegating to a sub-agent ends the conversation turn. The full pipeline would stall after qualification waiting for the user's next message. All tools live directly on `root_agent` so the qualify → match → book → confirm flow runs in one continuous turn.

### Guardrails
- **Input:** blocks prompt injection, gibberish, off-topic queries before reaching the LLM
- **Output:** redacts API keys or tracebacks that leak into LLM responses, handles empty LLM responses

### Secrets flow
GitHub Secrets → `TF_VAR_*` env → Terraform → GCP Secret Manager → Cloud Run `secretKeyRef`. Secrets never touch the shell or plain env vars.

---

## Critical Lessons Learned

**Pinecone env vars must be lazy-loaded** — read `os.getenv()` inside functions, never at module import time. `config.py` calls `load_dotenv()` but if `crm_tool.py` reads vars at import, they're empty. This caused silent in-memory fallback for all saves.

**`save_applicant` returns `storage` field** — `"pinecone"` or `"memory_only"`. Agent must check this before confirming to user. Never say "I've saved your details" on `memory_only`.

**Calendar timezone must be `Europe/London`** — using `ZoneInfo("Europe/London")` not `timezone.utc`. UTC slots appear 1h late in summer (BST = UTC+1). Event is stored with `timeZone: Europe/London` so slots must match.

**Pinecone namespace is `__default__`** — empty string `""` raises SDK error. Applicants stored in `__default__` namespace.

**Stale server process** — fixes don't apply until server restarts. On Cloud Run this means pushing to `main` and waiting for deploy. Local testing must kill old uvicorn process first.

**Health flag `google-calendar` is misleading** — only checks `GOOGLE_CALENDAR_ID` env var is non-empty, not that SA JSON is valid. Fake slots served if SA key is placeholder `{}`.

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
| `GOOGLE_CALENDAR_SA_JSON` | No | Service account JSON for Calendar API |
| `SENDGRID_API_KEY` | No | Real emails (falls back to log-only) |
| `SENDGRID_FROM_EMAIL` | No | Verified sender address in SendGrid |
| `HOMEDATA_API_KEY` | No | HomeData UK property data — EPC, floor area, sold history, live postcode search |

---

## Running Locally

```bash
cd /Users/anoo4413/Let-copilot/LettingCopilot
pip install -r requirements.txt
export GOOGLE_API_KEY=your_gemini_key
python main.py
# → http://localhost:8080
```

Pinecone, SendGrid, and Google Calendar are all optional — Ava works end-to-end without them using in-memory/mock fallbacks.

```bash
pytest tests/ -v   # 46 tests, no GCP account needed
```

---

## CI/CD

```
push to main
    ├─ 1. Test       pytest (46 tests)
    ├─ 2. Build      docker buildx + GitHub Actions layer cache
    │                tagged: v<semver>-<sha8>  (never :latest on Cloud Run)
    └─ 3. Deploy     terraform apply → Cloud Run → smoke test /health
```
