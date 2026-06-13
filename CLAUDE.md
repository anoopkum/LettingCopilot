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
├── data/properties.json          ← 20 seed listings across UK (manual data source)
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
- In-memory search filters by `area` (case-insensitive substring match)
- **Namespace:** `properties` for Pinecone upsert/search

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
- Saves applicant records (name, email, budget, move date, area, employment) to Pinecone index `applicants`
- Returns `storage` field: `"pinecone"` or `"memory_only"`
- **Agent must check `storage` field** — never confirm "saved" to user on `memory_only`
- Env vars must be lazy-loaded inside functions, not at module import time

---

## Property Data

**Source:** `data/properties.json` — 20 manually curated listings across the UK.

| Region | Areas covered |
|--------|--------------|
| London | Balham, Tooting, Clapham, Brixton, Streatham |
| North West | Liverpool (×2), Wirral (×2), Manchester (×2) |
| Midlands | Birmingham (×2) |
| Yorkshire | Leeds (×2) |
| Scotland | Edinburgh (×2) |
| Wales | Cardiff |
| South East | Brighton |
| North East | Newcastle |

**Rent range:** £850–£3,200/month. **Bedrooms:** 1–3.

To add new properties: append to `data/properties.json` following the same schema:
```json
{
  "id": "prop_021",
  "address": "Full address with postcode",
  "area": "City or neighbourhood name",
  "bedrooms": 2,
  "bathrooms": 1,
  "rent_pcm": 1200,
  "available_from": "2026-07-01",
  "features": ["furnished", "parking"],
  "description": "One line description."
}
```
If Pinecone is configured, re-seed by restarting the server (vectors are upserted on startup).

---

## Conversation Flow

Ava collects 6 things during qualification (one at a time):
1. **Preferred area/location** — asked first; picked up automatically from opening message if mentioned
2. Move date
3. Monthly budget (PCM)
4. Employment status (full-time / part-time / self-employed / student / other)
5. Guarantor availability (only if NOT full-time employed)
6. Full name + email or phone

All 6 collected → `save_applicant` → auto `search_properties` (with area) → renter picks property → `get_available_slots` → renter picks slot → `book_slot` → `send_reminder`.

**No results in requested area:** Ava broadens search (drops area filter, then raises budget +£100), presents nearest alternatives with a friendly explanation.

---

## Architecture Decisions

### No sub-agents
In ADK 2.2, delegating to a sub-agent ends the conversation turn. The full pipeline would stall after qualification waiting for the user's next message. All tools live directly on `root_agent` so the qualify → match → book → confirm flow runs in one continuous turn.

### Guardrails
- **Input:** blocks prompt injection, gibberish, off-topic queries before reaching the LLM. Location/search context words (`area`, `city`, `in`, `near`, etc.) suppress the move-date validator so area queries aren't mis-classified.
- **Output:** redacts API keys or tracebacks that leak into LLM responses, handles empty LLM responses.

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

**Guardrail false positive on area queries** — the move-date validator fires on any message containing "move" without a recognisable date. Added `location_context` check (area, city, in, near, etc.) to suppress it for location/search messages. `want`/`need`/`find` were intentionally excluded — too generic and caused "I want to move when things settle down" to bypass the check.

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
