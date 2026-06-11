# Troubleshooting Log

All errors encountered during development of LettingCopilot, with root cause and fix.

---

## 1. `Connection error — is the server running?`

**When:** First time opening the chat UI after `python main.py`.

**Root cause:** The FastAPI `/chat` endpoint was crashing internally (ADK runner error) but the UI was catching all fetch failures as a generic "Connection error" — masking the real error.

**Fix:** Added proper error handling in `/chat` to catch exceptions and return meaningful HTTP error responses. Updated the UI to display `data.detail` from non-2xx responses instead of a generic string.

**File:** `letting_copilot/app.py`, `ui/index.html`

---

## 2. `429 RESOURCE_EXHAUSTED — limit: 0` (first API key)

**When:** First agent call using key `AIzaSyD6jF0945...`

**Root cause:** The original API key had exhausted its **daily free-tier quota** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier = 0`). All models on that key were blocked.

**Fix:** Replaced with a new API key from a new Google Cloud project (`gen-lang-client-0300667287` / `lettingcopilot`).

**Lesson:** Free-tier Gemini API allows ~1,500 requests/day per project. When `limit: 0` appears (not `limit: 15` or similar), the daily quota is fully consumed — wait until midnight Pacific or use a new project.

---

## 3. `404 NOT_FOUND — models/gemini-1.5-flash is not found for API version v1beta`

**When:** Switching model to `gemini-1.5-flash` after quota exhaustion.

**Root cause:** `gemini-1.5-flash` is not a valid model name for the v1beta Generative Language API. The correct alias is `gemini-flash-latest` or `gemini-2.0-flash-001`.

**Fix:** Changed `AVA_MODEL` in `.env` to `gemini-flash-latest`.

**File:** `.env`, `letting_copilot/config.py`

---

## 4. `429 RESOURCE_EXHAUSTED` on second API key (`AQ.Ab8RN...`)

**When:** Testing second API key after switching projects.

**Root cause:** The `AQ.` prefix key is a **Google Cloud Console API key**, not a Google AI Studio Gemini API key. Cloud Console keys do not carry the free Generative Language API quota (`limit: 0` on all models).

**Fix:** Discovered that this key works when passed as the `X-goog-api-key` **header** (not as a query param `?key=`). Confirmed working with `gemini-flash-latest` model via direct curl. Updated the ADK runner to set `GOOGLE_GENAI_API_KEY` env var alongside `GOOGLE_API_KEY` so the genai SDK picks up the header-style auth.

**Confirmed working:**
```bash
curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent" \
  -H 'X-goog-api-key: AQ.Ab8RN6LII9...' \
  -H 'Content-Type: application/json' -X POST \
  -d '{"contents":[{"parts":[{"text":"say hi"}]}]}'
# → OK: Hi there! How can I help you today?
```

**File:** `letting_copilot/app.py`

---

## 5. `gemini-2.0-flash is no longer available`

**When:** Curl test with `?key=` query param against `gemini-2.0-flash`.

**Root cause:** `gemini-2.0-flash` (without version suffix) has been deprecated on the v1beta endpoint for this key type.

**Fix:** Use `gemini-flash-latest` as the model name — this always resolves to the current stable Flash model.

**File:** `.env` — `AVA_MODEL=gemini-flash-latest`

---

## 6. `Agent error: Session not found: <uuid>`

**When:** Sending any message via the chat UI — every message returned this error.

**Root cause:** In **google-adk 2.2.0**, `InMemorySessionService.get_session()` returns `None` when a session doesn't exist (instead of raising an exception as in earlier versions). The original code used `try/except` to detect a missing session and call `create_session` — but since no exception was raised, `create_session` was never called. The runner then failed because the session didn't exist.

**Fix:** Changed session lookup from try/except to an explicit `None` check:

```python
# Before (broken in ADK 2.2.0)
try:
    await session_service.get_session(...)
except Exception:
    await session_service.create_session(...)

# After (correct)
session = await session_service.get_session(...)
if session is None:
    await session_service.create_session(...)
```

**File:** `letting_copilot/app.py`

---

## 7. `gcloud: command not found`

**When:** Running `gcloud` commands for GCP deployment.

**Root cause:** gcloud SDK was installed but not in the shell PATH used by the Claude Code environment.

**Fix:** gcloud found at `/Users/anoo4413/Documents/Learning/GCP/google-cloud-sdk/bin/gcloud`. Add to PATH:
```bash
export PATH="$PATH:/Users/anoo4413/Documents/Learning/GCP/google-cloud-sdk/bin"
```
Or add permanently to `~/.zshrc`.

---

## 8. `ERROR: [Errno 48] Address already in use` (port 8080)

**When:** Restarting the server after a code change.

**Root cause:** Previous `python main.py` process still running in the background.

**Fix:**
```bash
lsof -ti:8080 | xargs kill -9
```

---

## Known Limitations (POC)

| Limitation | Impact | Prod fix |
|---|---|---|
| `InMemorySessionService` | Sessions lost on server restart | Replace with Firestore session service |
| In-memory property store | Data resets on restart | Replace with Firestore / Cloud SQL |
| In-memory CRM | Applicant records lost on restart | Replace with Cloud SQL or CRM API |
| Notifications log only | No real SMS/email sent | Integrate Twilio / SendGrid |
| No auth on `/chat` | Anyone can call the API | ✅ Fixed — JWT bearer auth added |

---

## 9. `/properties` returns empty list `[]`

**When:** Calling `GET /properties` after the deep architecture commit.

**Root cause:** `app.py` did `from letting_copilot.tools.property_store import _load, _PROPERTIES`. This copies the reference to the list object at import time. When `_load()` later does `_PROPERTIES = json.loads(...)`, it rebinds the module-level name to a new list — but the imported name in `app.py` still points to the original empty list.

**Fix:** Import the module itself and access the attribute through it:
```python
# Before (broken)
from letting_copilot.tools.property_store import _load, _PROPERTIES
_load()
return _PROPERTIES   # always []

# After (correct)
import letting_copilot.tools.property_store as ps
ps._load()
return ps._PROPERTIES  # reads the current module attribute
```

**File:** `letting_copilot/app.py`

---

## 10. `/workflow` times out (60s) on Cloud Run

**When:** Calling `POST /workflow` with the LangGraph pipeline.

**Root cause:** The graph was set up to loop through all 4 nodes (qualify → match → book → followup) in a single request. Each node calls an ADK agent which makes a Gemini API call (~10–15s on free tier). 4 sequential calls = ~60s, which hit Cloud Run's default 60s request timeout.

**Fix 1:** Raised Cloud Run `timeout` to `300s` in `terraform/dev/main.tf`.

**Fix 2:** Changed graph routing to single-turn mode — qualify node always returns to END on the first pass unless `needs_matching=True`. Each turn returns to the caller; the UI/orchestrator drives the next step via `/chat` or subsequent `/workflow` calls.

**File:** `letting_copilot/workflow/graph.py`, `terraform/dev/main.tf`

---

## 11. GitHub push protection blocked API key in `.tfvars.example`

**When:** Pushing a commit that included a real API key in `terraform/dev/terraform.tfvars.example`.

**Root cause:** GitHub Secret Scanning detected the `AQ.Ab8RN6LII9...` key pattern in the example file and blocked the push.

**Fix:** Replaced the real key with the placeholder `YOUR_GEMINI_API_KEY` in the example file, then force-pushed with `--force-with-lease`.

**File:** `terraform/dev/terraform.tfvars.example`

**Lesson:** Always use placeholder values in `.example` files, even if the real file is gitignored.

---

## 12. `ImportError: cannot import name 'JWTBearer' from 'letting_copilot.auth'`

**When:** Container started after adding Google OAuth support.

**Root cause:** `auth/__init__.py` still exported `JWTBearer` which had been removed. Any import of the auth package caused a crash-loop.

**Fix:** Updated `auth/__init__.py` to export only what exists:
```python
from .jwt_handler import create_token, verify_token, verify_google_id_token, is_oauth_enabled
__all__ = ["create_token", "verify_token", "verify_google_id_token", "is_oauth_enabled"]
```

**File:** `letting_copilot/auth/__init__.py`

---

## 13. `Error 400: origin_mismatch` — Google OAuth blocked

**When:** Clicking "Sign in with Google" on the live Cloud Run URL.

**Root cause:** The Cloud Run URL (`https://letting-copilot-913660829167.us-central1.run.app`) was not listed in the **Authorised JavaScript origins** for the OAuth 2.0 client in GCP Console.

**Fix:** GCP Console → APIs & Services → Credentials → OAuth 2.0 Client → add the exact Cloud Run URL to Authorised JavaScript origins. No trailing slash.

**Lesson:** Every environment URL (local, staging, prod) must be explicitly added. Google rejects the sign-in silently if the origin doesn't match exactly.

---

## 14. ADK pipeline stops after qualification — no matching, booking, or follow-up

**When:** User provided all 5 qualification details. Ava said "Thanks!" and went silent.

**Root cause:** The original design used `sub_agents` — the orchestrator delegated to a `qualification_agent` via `AgentTool`. In ADK 2.2.0, sub-agent delegation is **single-turn per HTTP request**. After the qualification sub-agent responded, the turn ended. The orchestrator never continued to matching.

**Fix:** Removed all `sub_agents`. All 7 tools (`save_applicant`, `search_properties`, `get_available_slots`, `book_slot`, `send_reminder`, `send_followup`, `save_offer`) placed directly on `root_agent`. The orchestrator instruction mandates the full pipeline runs continuously without stopping between stages.

**File:** `letting_copilot/agents/orchestrator.py`

**Lesson:** ADK `AgentTool` sub-agents terminate the turn. For a continuous multi-stage pipeline in one conversation turn, all tools must live on the root agent.

---

## 15. Empty response from ADK after tool calls (`parts[0].text = None`)

**When:** Agent successfully booked a slot but returned a blank response to the user.

**Root cause:** ADK fires `is_final_response()` on tool-call turns too. Those turns have `parts` containing `function_call` or `function_response` objects — `part.text` is `None`. The code was reading `parts[0].text` directly and treating `None` as the final response.

**Fix:** Iterate all parts looking for the first non-empty `.text`:
```python
for part in event.content.parts:
    text = getattr(part, "text", None)
    if text:
        response_text = text
        break
```

**File:** `letting_copilot/app.py`

---

## 16. Google Calendar API returns `403 — Calendar API has not been used in project`

**When:** First real calendar slot request after adding Google Calendar integration.

**Root cause:** The Google Calendar API was not enabled in GCP project `gen-lang-client-0300667287`.

**Fix:** GCP Console → APIs & Services → Enable APIs → enable **Google Calendar API**. Takes ~1 minute to propagate.

**Lesson:** Each Google API must be explicitly enabled per project even if credentials exist.

---

## 17. Agent hangs for 5+ minutes on booking — no slots returned

**When:** Applicant picked a property and Ava called `get_available_slots`. No response for 5+ minutes.

**Root cause:** Two compounding issues:
1. Calendar was fully booked for the next 7 days — `get_available_slots` returned an empty list `[]`
2. The orchestrator instruction said to call `get_available_slots` "until slots are found" — the LLM entered a retry loop calling it repeatedly, each call taking 10–15s

**Fix:**
1. `get_available_slots` now returns a dict `{"slots": [...], "available": bool, "message": str}` — when `available=False` the LLM knows to stop
2. Lookahead extended from 7 days to 30 days
3. Orchestrator instruction updated: call `get_available_slots` **once only**; if `available=False` tell the applicant you'll be in touch

**File:** `letting_copilot/tools/calendar_tool.py`, `letting_copilot/agents/orchestrator.py`

---

## 18. Fake calendar slot ID mismatch — booking fails silently

**When:** Agent presented slots as `"3:00 PM Thursday"` but `book_slot` was called with `"slot_0"`.

**Root cause:** Fake slot IDs were generated as `slot_0`, `slot_1` etc. but the LLM passed back the human-readable time string the user selected, not the internal ID.

**Fix:** Fake slot IDs are now human-readable datetime strings (e.g. `"Thursday 11 June at 3pm"`). `_fake_book()` does fuzzy substring matching so `"3pm"`, `"Thursday"`, or `"11 June"` all resolve to the correct slot. Last resort: takes the first available slot.

**File:** `letting_copilot/tools/calendar_tool.py`

---

## 19. Terraform `dynamic` env blocks not supported in `google_cloud_run_v2_service`

**When:** `terraform apply` failed after adding optional env vars (Calendar, SendGrid).

**Root cause:** The `google_cloud_run_v2_service` resource does not support `dynamic` blocks with `for_each = toset([...])` for `env` blocks. Terraform throws a provider-level error.

**Fix:** Use always-present `env` blocks for every variable. When a service is not configured, store a placeholder (`"{}"` for JSON, `"not-configured"` for strings) in Secret Manager. Python checks for the placeholder before using the value.

**File:** `terraform/dev/main.tf`

---

## 20. Shell arg splitting broke `terraform apply` with JSON secret

**When:** Passing `google_calendar_sa_json` (a JSON blob) as `-var="google_calendar_sa_json=..."` in CI.

**Root cause:** Bash splits on spaces and special characters inside JSON. The JSON value containing `{`, `}`, `:`, `"` was mangled before Terraform ever saw it.

**Fix:** All secrets passed via `TF_VAR_*` environment variables in the CI step's `env:` block — GitHub Actions handles quoting correctly and the values are never shell-split.

```yaml
env:
  TF_VAR_google_calendar_sa_json: ${{ secrets.GOOGLE_CALENDAR_SA_JSON }}
```

**File:** `.github/workflows/deploy-dev.yml`

---

## 21. Terraform state lock collision — concurrent CI runs

**When:** A manual `workflow_dispatch` run and an automatic push-triggered run both reached the Terraform Apply step at the same time.

**Root cause:** Two jobs tried to acquire the GCS state lock simultaneously. The second one failed with `Error 412: conditionNotMet`.

**Fix:** Not a code bug — stale lock clears automatically once the first run finishes. Avoid triggering manual runs while a push-triggered run is already deploying. The state lock is a safety feature, not an error.

**File:** None

---

## 22. SendGrid `401 — invalid authorization grant`

**When:** Booking confirmed, `send_reminder` called, email never arrived.

**Root cause:** The SendGrid API key stored in Secret Manager had been revoked or expired.

**Fix:** Generate a new key in SendGrid (Settings → API Keys), update `SENDGRID_API_KEY` GitHub secret, then update Secret Manager directly for immediate effect without a redeploy:
```bash
echo -n "SG.NEW_KEY" | gcloud secrets versions add sendgrid-api-key --data-file=- --project=gen-lang-client-0300667287
```

**Lesson:** `SENDGRID_API_KEY` was being read at module load time — if the env var wasn't available at startup, the key was empty forever. Fixed to read at call time via `os.getenv()` inside the function.

**File:** `letting_copilot/tools/notification_tool.py`

---

## 23. LLM says "I've sent an email" when send failed (`sent=False`)

**When:** SendGrid returned a non-202 error but Ava told the user the confirmation was sent.

**Root cause:** The orchestrator instruction said to tell the user "I've sent a reminder to [email]" unconditionally after calling `send_reminder`. The LLM didn't check the tool's return value.

**Fix:**
1. `_send_email()` now returns `(bool, str)` — `(success, error_detail)`
2. Return dict includes `"error"` key when send fails
3. Orchestrator instruction updated: check `sent=True` before confirming; if `sent=False` tell the user honestly

**File:** `letting_copilot/tools/notification_tool.py`, `letting_copilot/agents/orchestrator.py`

---

## 24. Input guardrail blocking "no", "yes", "ok"

**When:** After booking, user replied "no" to "Any other questions?" — got guardrail error instead of a natural goodbye.

**Root cause:** Input guard had `len(stripped) < 3` as a block condition. "no" is 2 characters.

**Fix:** Changed condition to only block pure punctuation/symbols or a single non-alpha character. Any real word — regardless of length — passes through to the LLM.

```python
# Before (blocks "no", "ok", "hi")
if len(stripped) < 3 or re.fullmatch(r"[^a-zA-Z0-9]+", stripped):

# After (only blocks "!", "???" etc)
if re.fullmatch(r"[^a-zA-Z0-9]+", stripped) or (len(stripped) == 1 and not stripped.isalpha()):
```

**File:** `letting_copilot/guardrails/input_guard.py`

---

## 25. Pinecone SDK v9 API mismatch — search returns no results

**When:** `PINECONE_API_KEY` was set and index existed, but `search_properties` always returned `[]`.

**Root cause:** Three API shape mismatches between the code and Pinecone SDK v9:
1. `upsert_records` requires `_id` field (not `id`) as the record identifier
2. `search()` takes flat keyword args (`inputs=`, `top_k=`, `filter=`) — not a nested `query` dict
3. `search()` returns a `SearchRecordsResponse` object — results accessed via `results.result.hits` not `.get("result", {}).get("hits", [])`

**Fix:**
```python
# upsert — use _id
{"_id": p["id"], "text": text, ...}

# search — flat kwargs
results = index.search(namespace="properties", top_k=5, inputs={"text": search_text}, filter=filters)

# results — object attribute access
hits = results.result.hits if hasattr(results, "result") else []
hit_id = hit.id  # not hit["id"]
```

**File:** `letting_copilot/tools/property_store.py`

---

## 26. Docker build reinstalls all packages on every CI run (~3 min)

**When:** Every push triggered a full `pip install` even when `requirements.txt` hadn't changed.

**Root cause:** `docker build` has no cache by default in GitHub Actions — each runner starts fresh.

**Fix:** Switched to `docker buildx build` with GitHub Actions cache backend:
```yaml
- uses: docker/setup-buildx-action@v3
- run: |
    docker buildx build \
      --cache-from type=gha \
      --cache-to   type=gha,mode=max \
      --push \
      ...
```
The pip install layer is now cached between runs. Build time drops from ~3 min to ~30s when `requirements.txt` is unchanged.

**File:** `.github/workflows/deploy-dev.yml`

---

## 27. SendGrid emails rejected by Hotmail — sender not verified

**When:** SendGrid returned `202 Accepted` but emails never arrived at `loganoop@hotmail.com`.

**Root cause:** `SENDGRID_FROM_EMAIL` was set to `loganoop@gmail.com`. Gmail and Hotmail both have strict DMARC policies (`p=reject`) — third-party services cannot send *as* those addresses. Hotmail silently drops emails where the `From` domain DMARC check fails.

**Fix:**
1. Changed `SENDGRID_FROM_EMAIL` to `loganoop@hotmail.com`
2. Verified that address as a Single Sender in SendGrid (Settings → Sender Authentication → Verify a Single Sender)
3. Updated Cloud Run env var immediately via `gcloud run services update --update-env-vars`

**Lesson:** Never use `@gmail.com` or `@hotmail.com` as a SendGrid sender address unless it is verified as a Single Sender in SendGrid. For production, use a custom domain with SPF/DKIM configured.
