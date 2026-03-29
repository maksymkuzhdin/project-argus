# Quick Start: Launch the Dashboard

Project Argus is a Next.js + FastAPI application. Choose your launch method:

---

## Option 1: Docker Compose (Recommended for First-Time Users)

**Requires:** Docker Desktop

```bash
cd argus
docker compose up --build
```

- Backend API: **http://localhost:8000**
- Frontend Dashboard: **http://localhost:3000**
- Database: Auto-initialized with PostgreSQL

Stop with `docker compose down`.

---

## Option 2: Local Development (Recommended for Development)

**Requires:** Python 3.11+, Node.js 20+

### Step 1: Set Up Environment

```bash
cd argus

# Copy the example env file
cp .env.example .env

# Edit .env to use local Database URL:
# DATABASE_URL=sqlite:///./argus.db
# (or set up a local PostgreSQL if you prefer)
```

### Step 2: Start Backend (Terminal 1)

```bash
cd backend

# Install Python dependencies (first time only)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start FastAPI development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

You'll see:
```
Uvicorn running on http://0.0.0.0:8000
Application startup complete
```

### Step 3: Start Frontend (Terminal 2)

```bash
cd frontend

# Install Node dependencies (first time only)
npm install

# Start Next.js development server
npm run dev
```

You'll see:
```
 ▲ Next.js 16.1.6
 - Local:        http://localhost:3000
 - Ready in 2.8s
```

### Step 4: Open Dashboard

**http://localhost:3000**

---

## What You'll See

### If Database Has Data:
- **Dashboard (/)**: Declarations list, scores, flags, pagination
- **Declaration Detail**: Click any row → see scores, rule explanations, financial data
- **Person Timeline**: Click "Open multi-year profile" → multi-year comparison

### If Database Is Empty:
- "No declarations processed yet" message
- Load sample data:
  ```bash
  cd argus/scripts
  python run_ingestion.py --year 2024 --max-pages 5
  ```

---

## Development Commands

### Frontend
```bash
npm run dev        # Start dev server (auto-reload)
npm run lint       # Check code quality
npm run build      # Build for production
npm run e2e        # Run end-to-end tests
```

### Backend
```bash
cd backend
uvicorn app.main:app --reload                    # Dev server with auto-reload
python -m pytest app/tests -q                    # Run unit tests (155 tests)
python scripts/run_scoring.py --layer2           # Run scoring pipeline
```

---

## Troubleshooting

### Port Already in Use
- Backend: `lsof -i :8000` (macOS/Linux) or check Task Manager (Windows)
- Frontend: `lsof -i :3000` or check Task Manager

### Database Connection Error
- Verify `DATABASE_URL` in `.env` matches your setup
- For Docker: use `DATABASE_URL=postgresql://argus:argus_local@db:5432/argus`
- For local PostgreSQL: `DATABASE_URL=postgresql://user:password@localhost:5432/argus`
- For SQLite: `DATABASE_URL=sqlite:///./argus.db`

### Frontend Won't Load
- Ensure backend is running on port 8000
- Check browser console (F12) for API errors
- Verify `NEXT_PUBLIC_API_URL` in `.env` or docker-compose.yml

### Stale Module Cache
```bash
# Frontend
rm -rf .next node_modules && npm install && npm run dev

# Backend
rm -rf __pycache__ .pytest_cache && pip install -r requirements.txt
```

---

## Next Steps

Once dashboard is running:

1. **Load Real Data**: Run ingestion script to pull from NAZK
   ```bash
   python scripts/run_ingestion.py --year 2024 --max-pages 50
   ```

2. **View Scoring**: Check anomaly signals for flagged declarations

3. **Explore API**: Backend docs at `http://localhost:8000/docs`

4. **Read Docs**: See `docs/` folder for methodology, runbooks, and architecture

---

**Questions?** See `README.md` for more details or check specific docs in `docs/` folder.
