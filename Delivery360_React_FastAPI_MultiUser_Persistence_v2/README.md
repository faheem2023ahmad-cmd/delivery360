# Delivery 360 — React + FastAPI, multi-user persistence POC

Built from the previous React + FastAPI package. Preserves all 20 existing business tools and the OpenAI Responses API agent. Adds user-scoped conversation storage, agent context compaction, login, logout, and persistent sessions.

## Login (LOCAL DEMO ONLY)

| Username   | Password  |
| ---------- | --------- |
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
$env:OPENAI_API_KEY = 'YOUKEY'
<h1>To Connect it to Azure</h1>
$env:DELIVERY360_AZURE_SQL_CONNECTION_STRING = 'Server=tcp:delivery360server.database.windows.net,1433;Database=delivery360_test;UID=faheem;PWD=P@ssword12;Encrypt=yes;TrustServerCertificate=no;'

*To Connect it to Local*
Remove-Item Env:DELIVERY360_AZURE_SQL_CONNECTION_STRING -ErrorAction SilentlyContinue
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

- **Complete user-visible messages** and business data are stored together in Azure SQL when `DELIVERY360_AZURE_SQL_CONNECTION_STRING` is configured. Without it, local development and tests continue to use the two SQLite files in `state/`.
- **Agent context** uses a bounded recent-turn window, durable summaries of older turns, and structured identifiers (`employee_id`, `sow_id`, `project_id`, etc.) extracted from successful tool results.
- The **20-turn hard limit is removed**. Long conversations remain open. Old messages remain viewable, but the model receives a condensed history; summaries can lose nuance and should not be mistaken for guaranteed perfect recall.
- The summary uses the configured OpenAI model. If summarization fails, a conservative bounded textual extract is retained instead.
- Historical business facts are not authoritative: the agent is instructed to query business tools for current status.
- `tool_executions` stores tool names and statuses for basic auditing; detailed tool payloads remain in bounded agent context and are not fully audited.
- The existing sample business dataset is regenerated on startup; each request gets a fresh business-tool service. Pending local action proposals are not persisted. These limitations existed in the previous POC.
- Azure SQL is the shared persistence target for multi-worker and scaled-out deployments. Configure the application identity with only the required database permissions; the connection string must be stored as a secret application setting, not committed to source.
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

Deploy the Python source files (`backend.py`, `azure_sql.py`, `context_service.py`, `delivery360_core.py`, `requirements.txt`, `startup.sh`, `data/`) and **compiled** `frontend/dist/` at ZIP root. The source ZIP provided here does not contain precompiled React assets.

App Service startup command:

```sh
sh startup.sh
```

Set `OPENAI_API_KEY`, `PORT=8000`, and `SCM_DO_BUILD_DURING_DEPLOYMENT=true`. The ZIP deployment should include compiled frontend files; Azure Python build will not automatically run `npm run build`.

**Azure safety guard:** By default, startup refuses the known demo credentials on Azure (`WEBSITE_SITE_NAME` is set). Do not expose these shared passwords publicly. Use Microsoft Entra ID before shared deployment. For a tightly restricted, synthetic-data-only temporary test, `DELIVERY360_ALLOW_INSECURE_DEMO_AUTH=true` explicitly disables this guard **at your own risk**; this is not a production setting.

For Azure deployment, configure `DELIVERY360_AZURE_SQL_CONNECTION_STRING` in App Service settings. For a system-assigned managed identity, the connection string uses `Server=tcp:delivery360server.database.windows.net,1433;Database=delivery360;Authentication=ActiveDirectoryMSI;Encrypt=yes;TrustServerCertificate=no;`. Create the identity as a database user and grant `db_datareader` and `db_datawriter`; keep schema initialization disabled in the running app. To migrate or verify the local databases, run `python migrate_sqlite_to_azure.py` in an environment with the connection setting available; it imports both `state/delivery360_poc.db` and `state/delivery360_chats.db`, preserves auth hashes and conversation history, inserts only into empty destination tables, and on reruns verifies exact row equality instead of duplicating data. The Azure schema can be created by the migration script or by setting `DELIVERY360_AZURE_SQL_INIT_SCHEMA=true` during a one-time startup with a principal allowed to create/alter dbo tables. Review per-table row counts before switching traffic. Do not configure `DELIVERY360_STATE_DIR` as the persistence layer for Azure mode.

## Verification

```powershell
python -m unittest -v test_persistence.py
python -m compileall -q backend.py context_service.py delivery360_core.py
```

The automated tests use a fake agent (no OpenAI charges) to verify both user accounts, conversation ownership, CSRF, saved messages, summary compaction, and >20 turns. The original 20-tool business validation is also available through `run_validation` in `delivery360_core.py`.

**Not yet included:** streaming tokens, enterprise SSO, rate limiting, production database migrations, complete action-workflow persistence, and dedicated functional dashboards beyond the existing workspace navigation.
