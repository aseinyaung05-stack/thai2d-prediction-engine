# 🚀 Production Deployment Guide

Deploy the full stack online:

| Component | Platform | URL pattern |
|---|---|---|
| Web dashboard (Next.js) | **Vercel** | `https://<your-app>.vercel.app` |
| API (Express + Prisma) | **Render** (web service) | `https://thai2d-api.onrender.com` |
| Prediction Engine (FastAPI) | **Render** (Docker service) | internal `http://thai2d-engine:10000` |
| PostgreSQL | **Supabase** | external |

---

## STEP 0 — Prerequisites

- Code pushed to a **GitHub repo** (Render, Vercel deploy from Git).
- Free accounts: [supabase.com](https://supabase.com), [render.com](https://render.com), [vercel.com](https://vercel.com).
- Local machine has Node 20+, Python not required for deployment.

---

## STEP 1 — Supabase database (5 min)

1. Supabase dashboard → **New project** (choose region `Singapore`).
2. Set a strong **database password** (you'll need it twice below).
3. When ready, open **Connect → Connection string** and copy TWO URIs:
   - **Session pooler** (port `5432`, host `aws-0-<region>.pooler.supabase.com`) → for Prisma.
   - The same host/credentials work for the Python engine.
4. Convert to the two formats the services need:

```
# DATABASE_URL (Prisma) — session pooler:
DATABASE_URL="postgresql://postgres.<ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres"

# PREDICTION_DATABASE_URL (SQLAlchemy/psycopg2):
PREDICTION_DATABASE_URL="postgresql+psycopg2://postgres.<ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres"
```

5. **Create the tables** from your machine (one-time):

```powershell
$env:DATABASE_URL="<paste the Prisma URI>"
npx prisma db push --schema database/prisma/schema.prisma
```

✅ Checkpoint: Supabase → Table editor shows `results`, `prediction_runs`,
`prediction_scores`, `backtests`, `model_versions`, `data_sync_logs`.

---

## STEP 2 — Render: API + Engine (10 min)

1. Render dashboard → **New → Blueprint** → select your GitHub repo.
   Render reads `render.yaml` and creates **two services**:
   - `thai2d-api` (Node, runs `npx tsx apps/api/src/index.ts`)
   - `thai2d-engine` (Docker, builds `deployment/Dockerfile.prediction`)
2. When prompted / after creation, fill the `sync: false` variables:

   On **thai2d-api**:
   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | Supabase Prisma URI (Step 1) |
   | `ADMIN_PASSWORD` | a strong password (NOT `change-me-now`) |
   | `CORS_ORIGINS` | `https://<your-vercel-app>.vercel.app` (add after Step 3, re-deploy) |

   Render **auto-generates** `PREDICTION_API_TOKEN` on the API.
   Copy it from the API's Environment tab, then on **thai2d-engine** set:
   | Variable | Value |
   |---|---|
   | `PREDICTION_DATABASE_URL` | Supabase psycopg2 URI (Step 1) |
   | `PREDICTION_API_TOKEN` | **paste the same token** as the API's |

3. Wait for both deploys to go live. ✅ Checkpoint:

```
https://thai2d-api.onrender.com/health        -> {"status":"ok"}
https://thai2d-engine.onrender.com/health     -> {"status":"ok",...}
```

> Engine internal URL: Render wires `PREDICTION_SERVICE_URL` automatically
> via `fromService.hostport` (e.g. `http://thai2d-engine:10000`).

---

## STEP 3 — Vercel: Web dashboard (5 min)

1. Vercel → **Add New → Project** → import the same GitHub repo.
2. **Root Directory: `apps/web`** (framework auto-detects Next.js).
3. Environment variable:

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://thai2d-api.onrender.com` |

4. Deploy. ✅ Checkpoint: the dashboard loads; header shows
   **"ထိုင်း 2D ခန့်မှန်းချက် အင်ဂျင်"**.

> `NEXT_PUBLIC_*` is baked in at build time — if you change the API URL
> later, trigger a **Redeploy** on Vercel.

---

## STEP 4 — First data import + backtest (10 min)

From your machine (or any terminal):

```powershell
# 1. Import full history (~5-8 min; upserts are idempotent)
$pair="admin:<YOUR_ADMIN_PASSWORD>"; $b64=[Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
Invoke-RestMethod -Method Post `
  -Uri "https://thai2d-api.onrender.com/api/sync?provider=thai2d&days=400" `
  -Headers @{ Authorization = "Basic $b64" }

# 2. Train + walk-forward backtest both sessions (persists model registry)
#    (engine endpoint; bearer token = PREDICTION_API_TOKEN)
$tok = "<PREDICTION_API_TOKEN>"
Invoke-RestMethod -Method Post -Uri "https://thai2d-engine.onrender.com/backtest/run" `
  -Headers @{ Authorization = "Bearer $tok" } `
  -Body '{"session":"MORNING"}' -ContentType "application/json"
Invoke-RestMethod -Method Post -Uri "https://thai2d-engine.onrender.com/backtest/run" `
  -Headers @{ Authorization = "Bearer $tok" } `
  -Body '{"session":"AFTERNOON"}' -ContentType "application/json"
```

✅ Checkpoint: dashboard shows **LIVE** predictions for both sessions,
`/history` fills with real draws, `/backtest` shows the honest verdict
(often *"No reliable predictive edge detected"* — that is correct behavior,
never fabricated).

---

## STEP 5 — Operations

**Automatic (already configured):**
- API scheduler syncs every `SYNC_INTERVAL_MINUTES` (10 min) — new results
  trigger predictions on demand; every prediction is an immutable snapshot.
- Weekend-aware: no sync attempts Sat/Sun (SET closed); next-session logic
  rolls to Monday automatically.

**Automatic daily retraining (included in `render.yaml`):**
The blueprint defines a `thai2d-daily-retrain` **Cron Job** — Mon-Fri at
11:30 UTC (18:00 Yangon, after the 4:30 PM draw): syncs fresh results, then
re-runs both sessions' walk-forward backtests and updates the model registry.
Fill `ADMIN_PASSWORD` + `PREDICTION_API_TOKEN` in its Environment tab after
first deploy. No manual curl needed.

**Free-tier caveats:**
- Render free services **sleep after 15 min idle** → first request has a
  ~30-60 s cold start. Upgrade to *Starter* for always-on.
- Vercel hobby is fine; the dashboard is light.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| API logs `Database 'thai2d' does not exist` / P1001 | Wrong Supabase URI — use the **pooler** host + correct password; re-run `prisma db push` |
| API 401 on `/api/sync` | `ADMIN_PASSWORD` mismatch — send exactly what's in the dashboard |
| Dashboard shows *"Live source unavailable"* | API sleeping (free tier) — wake it with any request, or upgrade plan |
| Predictions `stale: true` | Engine unreachable — check both services share the SAME `PREDICTION_API_TOKEN` |
| Engine 401 from API | Token mismatch (see above) |
| CORS errors in browser | Add your Vercel domain to API's `CORS_ORIGINS`, redeploy API |
| Supabase IPv6 connection issues | Always use the `pooler.supabase.com` hostnames (IPv4) |

## Security checklist (production)

- [x] `NODE_ENV=production`, `ALLOW_MOCK_DATA=false` (mock records rejected)
- [x] Strong `ADMIN_PASSWORD` (protects `/api/sync`, `/api/import`, `/api/admin/*`)
- [x] Random `PREDICTION_API_TOKEN` shared API↔engine (never exposed to frontend)
- [x] `CORS_ORIGINS` locked to your Vercel domain
- [x] Rate limiting on all API routes; helmet enabled
- [x] Secrets only in Render/Vercel dashboards — never in Git
