# Thai 2D Prediction Engine

**Historical Data • Statistical Analysis • Model Ranking**

A production-grade analytical platform for Thai 2D historical draw data:
automated ingestion → causal feature engineering → walk-forward validated
model ensemble → 00–99 score distribution → four-section ranking (A/B/C/D)
→ transparent dashboard (Burmese/English).

> ⚠️ **Disclaimer**: This application provides statistical analysis based on
> historical market/2D data. Model scores are estimates, **not guarantees**.
> Historical performance does not guarantee future results. When no model
> beats the frequency baseline out-of-sample, the system says so explicitly
> (*"No reliable predictive edge detected"*) and retains the baseline.

## Architecture

```
┌─────────────┐   REST    ┌──────────────┐   internal   ┌──────────────────┐
│ Web (Next)  │ ────────▶ │ API (Express)│ ───────────▶ │ Engine (FastAPI) │
│ Vercel:3000 │           │ Render :4000 │              │ Render :8000     │
└─────────────┘           └──────┬───────┘              └────────┬─────────┘
                                 │ Prisma                        │ SQLAlchemy
                                 ▼                               ▼
                    ┌─────────────────────────────────────────────┐
                    │        PostgreSQL (Supabase)                │
                    │ results · prediction_runs · scores ·        │
                    │ backtests · model_versions · sync_logs      │
                    └─────────────────────────────────────────────┘
                                 ▲
                    Thai 2D public API (thai2d provider · modular DataProvider:
                    thai2d | set (licensed) | mock (dev only))
```

**Statistical guarantees built in**
- Strict UTC storage; sessions defined in `Asia/Yangon` (12:00 PM / 4:30 PM);
  source market time (`Asia/Bangkok`) converted via IANA zones only.
- Causal features only — walk-forward chronology (60/20/20), no shuffling,
  feature selection/calibration/ensemble weights fitted on train/validation
  exclusively (leakage is covered by dedicated tests).
- Baseline-first production selection: an advanced model only becomes
  production if it beats every baseline out-of-sample; otherwise the system
  displays the DESCRIPTIVE/LOW-SIGNAL notice.
- Cold-start tiers: <100 records → uniform only; 100–499 → statistical;
  500+ → ML eligible; ML must still *earn* production status.
- Every prediction is an immutable snapshot; outcomes are appended later.

## Repository layout (monorepo)

```
apps/web            Next.js 14 + Tailwind + Recharts dashboard (mm/en)
apps/api            Express + Prisma: providers, ingestion, scheduler, REST
packages/shared     Canonical types, Yangon/Bangkok time utils, 2D normalize
services/prediction Python FastAPI engine: features, models, walk-forward,
                    calibration, drift monitoring, model registry
database/prisma     PostgreSQL schema (snake_case, shared with Python)
deployment/         Dockerfiles + DEPLOYMENT.md (Render/Supabase/Vercel)
scripts/dev-all.cmd One-click local launcher (Windows)
```

## Local development (Windows)

```powershell
copy .env.example .env          # fill DATABASE_URL etc.
docker compose up -d db         # Postgres
npm install
npm run db:push                 # create tables
scripts\dev-all.cmd             # starts API :4000, Engine :8000/8001, Web :3000
# open http://localhost:3000
```

Python engine (first time): `python -m venv .venv; .venv\Scripts\pip install -r services/prediction/requirements.txt`

## Tests

```powershell
npm run test --workspace packages/shared        # 13 tests (normalize/time/weekends)
cd apps/api;  npx vitest run                    # 11 tests (parsers/validation)
cd services/prediction; ..\..\.venv\Scripts\python.exe -m pytest tests -q
                                                # 80 tests (leakage/backtest/tiers…)
# Integration (real API, excluded by default):
pytest -m integration
```

## REST API

```
GET  /health                                  liveness (no dependencies)
GET  /api/results/latest?n=20                 recent draws
GET  /api/results/history?limit=&session=     chronological history
GET  /api/results/date/:date                  both sessions of one day
GET  /api/prediction/today                    both sessions (live or cached+flagged)
GET  /api/prediction/:session                 full prediction payload
GET  /api/prediction/:session/top?n=10        top-N candidates
GET  /api/prediction/:session/sections        A/B/C/D scores + explanations
GET  /api/backtest                            walk-forward evaluations
GET  /api/model/performance                   active model + drift status
GET  /api/sync/status · /api/sync/logs        sync audit trail
POST /api/sync?provider=thai2d&days=400       manual sync (Basic auth)
POST /api/import                              CSV import (Basic auth)
*    /api/admin/*                             quality, duplicates, missing dates,
                                              edits (Basic auth)
```

Engine (bearer `PREDICTION_API_TOKEN`): `/predict/{session}[/top|/sections]`,
`POST /backtest/run`, `/monitor/drift`, `/health`.

## Deployment

Full step-by-step: **[deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md)**
(Vercel + Render blueprint `render.yaml` + Supabase — ~30 minutes total).

## License / intent

Educational and personal research. No winning-number claims, no fabricated
data, no certainty language — the codebase enforces this.
