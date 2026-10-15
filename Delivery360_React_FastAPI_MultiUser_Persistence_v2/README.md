# Delivery 360 — React + FastAPI, multi-user persistence POC

Built from the previous React + FastAPI package. Preserves all 20 existing business tools and the OpenAI Responses API agent. Adds user-scoped conversation storage, agent context compaction, login, logout, and persistent sessions.

## Login (LOCAL DEMO ONLY)

| Username | Password |
|---|---|
| `manager1` | `manager` |
| `manager2` | `manager` |

Both accounts have identical workspaces and tools. Their conversations, messages, context summaries, and business references are isolated by authenticated owner. Passwords are salted PBKDF2 hashes, not plaintext database entries. The app uses HttpOnly session cookies, CSRF tokens, and server-side session storage. **These known demonstration passwords are not safe for public deployment.** No rate limiting, password recovery, MFA, SSO, or enterprise RBAC is implemented.

Optionally set `DELIVERY360_MANAGER1_PASSWORD` and `DELIVERY360_MANAGER2_PASSWORD` **before first launch** to change the initial seeded passwords. Once an account exists, these environment variables do not reset its password.

## Local setup in VS Code / Windows PowerShell

Requires Python 3.11+ and Node.js 18+.

Terminal 1 (project root):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:OPENAI_API_KEY = 'YOUR KEY HERE'
uvicorn backend:app --reload --port 8000
```

Terminal 2:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to FastAPI on port 8000. The login page appears automatically. Never commit an API key or a `.env` file.

## Persistence design

- **Complete user-visible messages** are saved to SQLite (`state/delivery360_chats.db` by default). The database survives local restarts.
- **Agent context** uses a bounded recent-turn window, durable summaries of older turns, and structured identifiers (`employee_id`, `sow_id`, `project_id`, etc.) extracted from successful tool results.
- The **20-turn hard limit is removed**. Long conversations remain open. Old messages remain viewable, but the model receives a condensed history; summaries can lose nuance and should not be mistaken for guaranteed perfect recall.
- The summary uses the configured OpenAI model. If summarization fails, a conservative bounded textual extract is retained instead.
- Historical business facts are not authoritative: the agent is instructed to query business tools for current status.
- `tool_executions` stores tool names and statuses for basic auditing; detailed tool payloads remain in bounded agent context and are not fully audited.
- The existing sample business dataset is regenerated on startup; each request gets a fresh business-tool service. Pending local action proposals are not persisted. These limitations existed in the previous POC.
- The SQLite implementation is for **single-instance POC deployment**, not concurrent multi-worker or scaled-out production. Use PostgreSQL with transaction-level concurrency controls for multi-instance deployment.
- Existing chats created under the old `local-demo` identity are not automatically assigned to either manager account. This prevents accidental cross-user exposure. To retain them, implement an explicit, owner-approved migration.

## Azure deployment notes

**Do not overwrite your working Gradio App Service until you have tested this locally.**

Build the React frontend before packaging:

```powershell
cd frontend
npm install
npm run build
cd ..
```

Deploy the Python source files (`backend.py`, `context_service.py`, `delivery360_core.py`, `requirements.txt`, `startup.sh`, `data/`) and **compiled** `frontend/dist/` at ZIP root. The source ZIP provided here does not contain precompiled React assets.

App Service startup command:

```sh
sh startup.sh
```

Set `OPENAI_API_KEY`, `PORT=8000`, and `SCM_DO_BUILD_DURING_DEPLOYMENT=true`. The ZIP deployment should include compiled frontend files; Azure Python build will not automatically run `npm run build`.

**Azure safety guard:** By default, startup refuses the known demo credentials on Azure (`WEBSITE_SITE_NAME` is set). Do not expose these shared passwords publicly. Use Microsoft Entra ID before shared deployment. For a tightly restricted, synthetic-data-only temporary test, `DELIVERY360_ALLOW_INSECURE_DEMO_AUTH=true` explicitly disables this guard **at your own risk**; this is not a production setting.

For persistent SQLite on a single Azure App Service instance, configure `DELIVERY360_STATE_DIR=/home/delivery360-state` on a supported persistent `/home` volume and verify write access. `/tmp` is not durable. For real users and durable backups, migrate to Azure Database for PostgreSQL before rollout.

## Verification

```powershell
python -m unittest -v test_persistence.py
python -m compileall -q backend.py context_service.py delivery360_core.py
```

The automated tests use a fake agent (no OpenAI charges) to verify both user accounts, conversation ownership, CSRF, saved messages, summary compaction, and >20 turns. The original 20-tool business validation is also available through `run_validation` in `delivery360_core.py`.

**Not yet included:** streaming tokens, enterprise SSO, rate limiting, production database migrations, complete action-workflow persistence, and dedicated functional dashboards beyond the existing workspace navigation.
