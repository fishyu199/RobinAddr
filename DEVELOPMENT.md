# RobinCop development

RobinCop discovers Robinhood Chain Smart Money wallets, replays up to 5,000 spot trades with a 2.5% worse entry and time-sensitive sell slippage, and publishes only wallets scoring above 30.

## Services

- `apps/web`: English public leaderboard/detail pages and Chinese admin UI.
- `apps/api`: FastAPI public/admin API and PostgreSQL models.
- `apps/worker`: Celery analysis and discovery workers.
- `copybot`: deterministic copy-trading backtest engine.
- `run_robinhood.py`: wallet analysis and multilingual Telegram report entrypoint.

## Local configuration

Copy `.env.example` to `.env` and provide `GMGN_API_KEY` and a strong `ADMIN_API_KEY`. Never commit `.env`.

The default schedules are encoded in the worker configuration:

- GMGN discovery: every 30 minutes by default, 7D realized-profit ranking, top 200.
- Published-wallet reanalysis: every 7 days.
- Publication threshold: strictly greater than 30.
- GMGN request pacing: 48 requests/second by default, leaving headroom under a 50-weight/second plan.
- Analysis worker: one wallet at a time. Inside that wallet, BUY and SELL keep separate concurrent cursor streams; pages inside each stream remain sequential for correctness.

## Start the stack

Run `docker compose up --build`. The public site is served on port 3000 and the API on port 8000.

## Tests

Run `python3 -m unittest discover -s tests -v` for the calculation engine and `npm run build` from `apps/web` for the site.

The same checks are available from the project root as `make test` and `make web-build`.

## Stored wallet reports

The API and workers must use the same release. Apply migration `0005` before starting the updated workers; API containers already run `alembic upgrade head` at startup. From the project root, with the API dependencies installed and `DATABASE_URL` configured for the intended database:

```bash
PYTHONPATH=.:apps/api python3 -m alembic -c apps/api/alembic.ini upgrade head
```

Successful analyses store the default English Telegram HTML `report_text` alongside metrics in `published_wallets`. Only the latest successful report is retained for each address; historical `analysis_runs.result` keeps its compact audit summary. Failed analyses preserve the previous successful metrics/report pair. Detail responses include `report_text` in every mode; list responses omit it.

Existing rows have a null report until their next successful analysis or a backfill. Preview missing reports using the persisted metrics, then apply if desired:

```bash
PYTHONPATH=.:apps/api python3 -m robincop_api.backfill_reports
PYTHONPATH=.:apps/api python3 -m robincop_api.backfill_reports --apply
```

Both commands default to English. To rewrite every existing stored report in English without recalculating or fetching GMGN data, add `--overwrite` to the preview and apply commands. `--lang` is available for an explicit supported language when needed.

Add `--address 0x...` to limit either command to one wallet. In Docker Compose, use `docker compose exec api python -m robincop_api.backfill_reports` (and `--apply` to persist). The command never requests GMGN or recalculates scores. By default it fills only null reports; `--overwrite` safely rewrites existing reports. It preserves the analysis timestamp and skips a row if its analysis or stored report changed after it was read. Incomplete stored metrics are reported as errors without stopping other rows; an error gives a nonzero exit status. Reports reconstructed from older metrics use the current report template and may differ from text sent in the past.

## Data-source boundary

The public GMGN Agent API currently provides a Smart Money activity feed but not a complete documented ranked-wallet route. The discovery service is intentionally isolated so a verified ranked-wallet connector can replace the feed fallback without changing analysis, persistence, or public pages.
