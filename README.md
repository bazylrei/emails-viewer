# Email Intent Viewer

Pulls emails from a shared Microsoft 365 mailbox, classifies them by business intent using Claude, and displays them in a Streamlit UI backed by Azure Table Storage.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

All scripts load credentials from `.env` automatically via `python-dotenv`.

## .env variables

| Variable | Purpose |
|---|---|
| `TENANT_ID` | Azure AD tenant ID |
| `CLIENT_ID` | App registration client ID |
| `SHARED_MAILBOX` | Email address of the shared mailbox |
| `SUBFOLDER_NAME` | Mailbox subfolder to pull from (e.g. `Printed`) |
| `OUTPUT_DIR` | Local directory for scraped JSON files (e.g. `emails`) |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Table Storage connection string |
| `ANTHROPIC_API_KEY` | Claude API key |
| `APP_PASSWORD` | Password for the Streamlit UI login |

## Workflow

### 1. Pull emails from Microsoft 365

```bash
# All emails (grouped into emails/emails_YYYY_MM.json)
python email_scraping.py

# Specific month range
python email_scraping.py --from 2026-03-01 --to 2026-04-01
```

Output: `emails/emails_2026_03.json` (one file per month)

### 2. Classify emails with Claude

```bash
# Classify a month file (resumes if interrupted)
python classify.py emails/emails_2026_03.json

# Re-classify only emails missing a question
python classify.py emails/emails_2026_03.json --backfill

# Hard reset — drop all storage and re-classify from scratch
python classify.py emails/emails_2026_03.json --reset
```

Progress indicators: `.` = existing intent/question, `+` = new intent, `?` = new question, `s` = skipped (already done)

### 3. Run the viewer UI

```bash
source venv/bin/activate
streamlit run viewer.py
```

Opens at `http://localhost:8501`. Login with `APP_PASSWORD` from `.env`.

## Storage

Classified data lives in Azure Table Storage (3 tables: `emails`, `intents`, `questions`). The local `emails/` JSON files are just the raw scrape cache.

## Other scripts

- `migrate.py` — one-time migration from old `results/*.json` format to Azure Table Storage
- `storage.py` — Azure Table Storage abstraction (not run directly)
- `auth.py` — Streamlit password check (not run directly)
