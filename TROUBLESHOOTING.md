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
| No auth on `/chat` | Anyone can call the API | Add API key or OAuth middleware |
