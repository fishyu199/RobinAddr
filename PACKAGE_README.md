# RobinCop full-stack source package

Build date: 2026-09-28

This package contains the complete source needed to develop and deploy RobinCop:

- `apps/web`: public leaderboard, wallet details, Telegram Mini App integration, and the admin UI.
- `apps/api`: public/admin API, PostgreSQL models and Alembic migrations.
- `apps/worker`: Celery worker image.
- `copybot`: GMGN client, normalization, backtest, scoring and report engine.
- `deploy`: production-oriented Docker Compose and Nginx examples.
- `tests`: calculation, discovery, scheduling and reporting tests.
- `run_robinhood_standalone.py`: dependency-free single-file wallet analyzer.

## Local start

1. Copy `.env.example` to `.env`.
2. Set a real `GMGN_API_KEY`, a strong `ADMIN_API_KEY`, and production-grade database credentials.
3. For the current low-frequency collection policy, set `DISCOVERY_INTERVAL_MINUTES=120`.
4. Run `docker compose up --build`.

The public site is exposed on port 3000 and the API on port 8000 in the local compose file. Production examples are under `deploy/` and should be reviewed for the target server, domain and certificates before use.

## Verification

```bash
python3 -m unittest discover -s tests -v
cd apps/web && npm ci && npm run build
```

No `.env`, API keys, passwords, database contents, caches, dependency folders or previous deployment backups are included in this package.
