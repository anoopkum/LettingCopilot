---
description: LettingCopilot agent guide — architecture, tools, pipeline, known issues, and best practices built up during implementation
---

# LettingCopilot Agent Skill

You are working on **LettingCopilot** — an AI lettings agent (Ava) that takes a renter from first message to confirmed viewing in one continuous conversation. Use the context below to answer questions, debug issues, or make changes.

---

## Project Layout

```
letting_copilot/
  agents/
    orchestrator.py     ← single agent with all tools (Ava)
    qualification.py    ← standalone qualification agent (LangGraph path only)
    matching.py
    booking.py
    followup.py
  tools/
    crm_tool.py         ← save_applicant / get_applicant → Pinecone applicants index
    property_store.py   ← search_properties → Pinecone lettingcopilot-properties index
    calendar_tool.py    ← get_available_slots / book_slot → Google Calendar API
    notification_tool.py← send_reminder / send_followup → SendGrid
  guardrails/
    input_guard.py      ← blocks injection, gibberish, off-topic at FastAPI layer
    output_guard.py     ← redacts secrets/errors from LLM responses
  app.py                ← FastAPI: /chat (ADK), /workflow (LangGraph), /a2a, /auth
  config.py             ← load_dotenv() runs here — MUST be imported before any tool module
terraform/dev/          ← Cloud Run + Secret Manager + IAM
.github/workflows/      ← test → build → terraform deploy → smoke test
```

---

## The Pipeline

```
STAGE 1  QUALIFY   → save_applicant()        check storage=="pinecone" before confirming
STAGE 2  MATCH     → search_properties()     auto after save — no user prompt needed
STAGE 3  BOOK      → get_available_slots()   auto after property chosen — call ONCE only
                   → book_slot()             pass slot "id" field, not the time string
STAGE 4  CONFIRM   → send_reminder()         auto after booking — check sent==True before saying email sent
```

All stages run on one `ava_orchestrator` agent. Sub-agents are NOT used because ADK sub-agents are single-turn and break the continuous pipeline.

---

## Critical Rules (never break these)

1. **Pinecone env vars are lazy-loaded** — `os.getenv()` is called inside functions, never at module import time. `config.py` calls `load_dotenv()` but module-level reads happen before that.

2. **Check `storage` before confirming save** — `save_applicant()` returns `{"storage": "pinecone"}` on success or `{"storage": "memory_only"}` on failure. Never tell the user their details are saved on `memory_only`.

3. **Calendar timezone is `Europe/London`** — use `ZoneInfo("Europe/London")` everywhere in `calendar_tool.py`. Never use `timezone.utc` for slot generation — slots are stored with `timeZone: Europe/London` so UTC slots appear 1h late in summer (BST = UTC+1 in June).

4. **Pinecone namespace is `"__default__"`** — empty string `""` raises an SDK error. Applies to both `upsert_records` and `fetch` in `crm_tool.py`.

5. **Never call `get_available_slots` more than once** — if it returns `available=False`, tell the user and move on. Retrying causes an infinite loop.

6. **Check `sent` before confirming email** — `send_reminder()` returns `{"sent": True/False}`. Only say "I've sent a confirmation to [email]" when `sent=True`.

7. **Echo user's exact words** — move date, budget, name. Never round, paraphrase, or drop specifics.

8. **Stale server = stale code** — fixes don't apply until the server restarts. On Cloud Run, push to `main` and wait for the deploy pipeline (~3 min).

---

## Two Pinecone Indexes

| Index | Name | Purpose |
|---|---|---|
| Properties | `lettingcopilot-properties` | Semantic property search, `multilingual-e5-large` model |
| Applicants | `applicants` | CRM records, `llama-text-embed-v2` model, host `https://applicants-2d28onu.svc.aped-4627-b74a.pinecone.io` |

Controlled by env vars `PINECONE_INDEX` and `PINECONE_APPLICANTS_INDEX`. Never share them.

---

## All Secrets Flow

```
GitHub Secrets
  → TF_VAR_* in deploy-dev.yml
    → Terraform variables.tf (sensitive=true)
      → GCP Secret Manager (for sensitive values)
      → Cloud Run env var (for plain values like index names)
        → os.getenv() in Python (lazy, inside functions)
```

Sensitive: `PINECONE_API_KEY`, `GOOGLE_CALENDAR_SA_JSON`, `SENDGRID_API_KEY`, `JWT_SECRET`, `GEMINI_API_KEY`  
Plain env vars: `PINECONE_INDEX`, `PINECONE_APPLICANTS_INDEX`, `GOOGLE_CALENDAR_ID`, `SENDGRID_FROM_EMAIL`, `GOOGLE_OAUTH_CLIENT_ID`

---

## Common Bugs & Fixes

| Symptom | Cause | Fix |
|---|---|---|
| Record not in Pinecone, agent says "I've saved your details" | `storage="memory_only"` — key not loaded at import time | Lazy-load env vars inside function; check `storage` field before confirming |
| Calendar shows 1h later than booked | Slots built in UTC, stored as Europe/London | Use `ZoneInfo("Europe/London")` for all slot datetimes |
| Agent stops after qualification | Sub-agents were single-turn | All tools on one orchestrator agent |
| "namespace must be non-empty string" | `namespace=""` in Pinecone SDK call | Use `namespace="__default__"` |
| Health shows `google-calendar` but fake slots served | Health only checks env var, not SA auth | Verify `GOOGLE_CALENDAR_SA_JSON` has `type` and `private_key` fields |
| New code not working on Cloud Run | Stale deploy | Push to `main`, wait for pipeline to complete |

---

## Running Locally

```bash
# Must run from project root so python-dotenv finds .env
cd /Users/anoo4413/Let-copilot/LettingCopilot
pip install -r requirements-dev.txt
python -m uvicorn letting_copilot.app:app --reload --port 8080

# Kill stale server before testing fixes
pkill -f "uvicorn letting_copilot"
```

---

## Deploying

Push to `main` — the GitHub Actions pipeline handles everything:
1. Tests (`pytest tests/test_tools.py tests/test_guardrails.py`)
2. Build & push Docker image (tagged `v<semver>-<sha>`)
3. Terraform apply (Cloud Run + secrets)
4. Smoke test (`GET /health`)

Check pipeline: `gh run list --repo anoopkum/LettingCopilot --limit 3`  
Live URL: `https://letting-copilot-ruzwhtmsaq-uc.a.run.app`

---

## Checking Pinecone State

```python
from dotenv import load_dotenv
load_dotenv('/Users/anoo4413/Let-copilot/LettingCopilot/.env')
from pinecone import Pinecone
import os

pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
idx = pc.Index(host='https://applicants-2d28onu.svc.aped-4627-b74a.pinecone.io')
ids = list(idx.list(namespace='__default__', limit=20))
all_ids = [item.id for r in ids for item in r.vectors]
fetched = idx.fetch(ids=all_ids, namespace='__default__')
for rid, v in fetched.get('vectors', {}).items():
    meta = v.get('metadata') or {}
    print(f"{rid}: name={meta.get('name')} | email={meta.get('email')}")
```

---

## Checking Cloud Run Logs

```bash
# All logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="letting-copilot"' \
  --project=gen-lang-client-0300667287 --limit=50 --freshness=1h

# Calendar only
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="letting-copilot" AND textPayload=~"calendar"' \
  --project=gen-lang-client-0300667287 --limit=20 --freshness=1d

# CRM / Pinecone only
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="letting-copilot" AND textPayload=~"crm"' \
  --project=gen-lang-client-0300667287 --limit=20 --freshness=1d
```
