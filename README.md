# InterviewAI — Full-Stack Setup Guide

## Project Structure

```
project/
├── backend/
│   ├── main.py                  ← FastAPI server (NEW)
│   ├── interview_platform.py    ← Your existing engine (copy here)
│   ├── requirements.txt
│   └── .env
└── frontend/
    ├── src/
    │   ├── api/client.js        ← API calls to backend
    │   ├── components/Nav.jsx
    │   ├── pages/
    │   │   ├── Home.jsx         ← Landing page
    │   │   ├── Setup.jsx        ← Upload resume + JD
    │   │   ├── InterviewRun.jsx ← Live interview Q&A
    │   │   └── Report.jsx       ← Final performance report
    │   ├── App.jsx
    │   └── main.jsx
    ├── index.html
    ├── package.json
    └── vite.config.js
```

---

## Step 1 — Copy your existing file

```bash
cp interview_platform.py project/backend/interview_platform.py
```

---

## Step 2 — Backend Setup

```bash
cd project/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env and fill in your keys
```

**.env file:**
```
OPENAI_API_KEY=your-openai-api-key
QDRANT_HOST=your-qdrant-host
QDRANT_API_KEY=your-qdrant-api-key
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password
```

**Start the backend:**
```bash
uvicorn main:app --reload --port 8000
```

Backend runs at: http://localhost:8000
API docs at:     http://localhost:8000/docs

---

## Step 3 — Frontend Setup

```bash
cd project/frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

Frontend runs at: http://localhost:5173

The Vite dev server automatically proxies `/api/*` → `http://localhost:8000/*`
so no CORS issues during development.

---

## Step 4 — Make sure Docker services are running

```bash
# Qdrant
docker run -p 6333:6333 qdrant/qdrant

# Neo4j
docker run -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:latest
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/session/start` | Upload resume PDF + JD, start session |
| GET | `/session/{id}/question` | Get current question |
| POST | `/session/{id}/answer` | Submit answer, get evaluation |
| GET | `/session/{id}/report` | Generate final report |
| DELETE | `/session/{id}` | Clean up session |

---

## User Flow

```
/ (Home)
  └── Click "Start Interview"
        └── /interview (Setup)
              └── Upload PDF + JD + choose mode → POST /session/start
                    └── /interview/run (Live Q&A)
                          ├── GET /session/{id}/question  ← fetch question
                          ├── POST /session/{id}/answer   ← submit answer
                          └── interview_complete == true
                                └── /interview/report
                                      └── GET /session/{id}/report
```

---

## Production Build

```bash
# Build frontend
cd frontend
npm run build
# Output in frontend/dist/

# Serve with FastAPI (add to main.py):
# from fastapi.staticfiles import StaticFiles
# app.mount("/", StaticFiles(directory="../frontend/dist", html=True))

# Run production server
uvicorn main:app --host 0.0.0.0 --port 8000
```
