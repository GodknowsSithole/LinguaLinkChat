# LinguaLink Chat SA

A real-time direct messaging starter app. Users register or log in, choose a preferred language, select another user and chat. Every message is stored in its original form and translated for the recipient into that recipient's preferred language.

## Architecture
- Next.js UI
- FastAPI REST and authenticated WebSocket notifications
- PostgreSQL 16 persistence (psycopg 3 with a connection pool), or SQLite for local development
- JWT login with Argon2 password hashes
- NLLB-200 distilled 600M translation

## Run locally without Docker (Windows)

Install Python 3.11–3.13 and Node.js 22 (including npm), then open PowerShell in the project folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

The script installs dependencies into `backend/.venv` and `frontend/node_modules`, creates a persistent local login secret, and starts the API and frontend. Open http://localhost:3000. Keep the terminal open; press Ctrl+C to stop both servers. Logs are in `data/logs`.

This mode stores accounts and chats in `data/lingualink.db` using SQLite, so no database server or administrator installation is required. It creates a separate local database; it does not import existing PostgreSQL data. Translation uses the same NLLB model on the CPU. The first setup and model download need internet access and several GB of disk space; model loading and translation can take time.

To install dependencies without starting the servers, add `-SetupOnly`. If Python is not on PATH, pass `-PythonPath "C:\path\to\python.exe"`.

For manual startup in two PowerShell terminals after installing dependencies:

```powershell
# Terminal 1, from the project folder
$env:DATABASE_URL = "sqlite:///../data/lingualink.db"
$env:JWT_SECRET = (Get-Content .\data\local-jwt-secret.txt -Raw).Trim()
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2, from the project folder
cd frontend
npm run dev
```

## Run locally with PostgreSQL

You can also install PostgreSQL 16 directly on your computer, create a `lingualink` database and user, and set `DATABASE_URL` to match. Alternatively, start PostgreSQL with Docker:
```bash
docker run -d --name lingualink-pg -e POSTGRES_USER=lingualink -e POSTGRES_PASSWORD=lingualink_dev -e POSTGRES_DB=lingualink -p 5432:5432 postgres:16-alpine
```
Backend (PowerShell; the explicit URL below uses port 5432, while the legacy application default uses 5433):
```powershell
cd backend
python -m venv .venv
# Windows
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://lingualink:lingualink_dev@localhost:5432/lingualink"
$env:JWT_SECRET = "replace-this-with-a-long-random-value"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```
Frontend in a second terminal:
```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:3000 and create two accounts in separate browsers. Give each user a different preferred language. The first translation downloads the model and may be slow.

Or run everything (PostgreSQL, API, web) with `docker compose up --build`.

## Flow
1. User registers with a preferred language.
2. Login returns a signed JWT.
3. The chat WebSocket is authenticated using that token.
4. Sender chooses the language they are typing in.
5. Backend looks up the recipient's preferred language.
6. Backend translates, stores the original and recipient translation, and pushes the message in real time.
7. A user can change their preferred language from the sidebar. New messages use the updated preference, and older received text messages can be re-translated from the message menu (the three dots) with **Re-translate**.

## Google Cloud Translation

To use Google instead of NLLB, save these backend settings in the root `.env` file (ignored by Git):

```dotenv
TRANSLATION_PROVIDER=google
GOOGLE_TRANSLATE_API_KEY=your-api-key
```

The backend loads this file automatically. Restart the app with `start-local.ps1` after changing it. Variables already set in the launching terminal take priority. The key stays on the backend and is sent only in an HTTPS authentication header to `translation.googleapis.com`; never place it in a frontend or `NEXT_PUBLIC_` variable.

Enable Cloud Translation API and billing on the Google Cloud project associated with the key. Restrict the key to that API. See [Google's setup guide](https://docs.cloud.google.com/translate/docs/setup). Message text and document chunks are sent to Google for detection and translation and may incur usage charges.

The backend checks the key and Google's actual supported-language list at startup. Unavailable languages are disabled in the selectors. Southern Ndebele uses code `nr`; Tshivenda availability is determined by the API rather than assumed. Cloud service failures produce readable errors and preserve the message draft.

New translations use Google. Existing chat history remains stored; use **Re-translate** on older messages to replace cached NLLB output. The cache records the provider to avoid reusing translations from the previous engine. Google mode does not load NLLB and its large model. To switch back, set `TRANSLATION_PROVIDER=nllb` and optionally `MODEL_ID=facebook/nllb-200-3.3B` before restarting.

## Performance tuning

Translation runs on the CPU, so speed matters. The model is preloaded when the API starts, so the first message is not delayed. Environment variables for the API:
- `NUM_BEAMS` (default `2`): beam-search width. `5` gives slightly better quality but is about twice as slow on CPU; `1` is fastest.
- `QUANTIZE_INT8` (default `0`; `1` in `docker-compose.yml`): dynamic int8 quantisation on x86 CPUs to reduce memory use (do not use on ARM).
- Docker Desktop: give Docker at least 4 GB of RAM (Settings > Resources) and close heavy applications.

## Before production
Put translation jobs on a queue, use Redis for WebSocket scaling, enforce HTTPS/WSS, use a strong secret, add refresh-token rotation, rate limits, abuse controls, delivery/read states and data-retention settings. Do not treat machine translations as authoritative for legal, medical or financial communication.
