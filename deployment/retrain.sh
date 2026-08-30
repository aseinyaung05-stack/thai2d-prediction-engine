#!/bin/sh
# Daily retrain job (Render Cron) — sync fresh results, then walk-forward
# backtest both sessions and update the model registry.
set -u

echo "[retrain] syncing fresh results..."
curl -fsS --max-time 600 -X POST "$API_URL/api/sync?provider=thai2d" \
  -u "$ADMIN_USERNAME:$ADMIN_PASSWORD" || echo "[retrain] sync failed (continuing)"

echo "[retrain] backtest MORNING..."
curl -fsS --max-time 1500 -X POST "$ENGINE_URL/backtest/run" \
  -H "Authorization: Bearer $PREDICTION_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session":"MORNING"}' || echo "[retrain] morning backtest failed"

echo "[retrain] backtest AFTERNOON..."
curl -fsS --max-time 1500 -X POST "$ENGINE_URL/backtest/run" \
  -H "Authorization: Bearer $PREDICTION_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session":"AFTERNOON"}' || echo "[retrain] afternoon backtest failed"

echo "[retrain] done."
