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

## Data-source boundary

The public GMGN Agent API currently provides a Smart Money activity feed but not a complete documented ranked-wallet route. The discovery service is intentionally isolated so a verified ranked-wallet connector can replace the feed fallback without changing analysis, persistence, or public pages.
