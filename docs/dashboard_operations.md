# Dashboard Operations Guide

This guide details operations, configuration, and troubleshooting procedures for the Market Sniffer 2000 Flask web app.

## Launching the Web Server

Start the local server using:

```bash
python -m market_sniffer.cli web serve --host 127.0.0.1 --port 8765
```

For testing using simulated fixture clients:

```bash
python -m market_sniffer.cli web serve --host 127.0.0.1 --port 8765 --fixture
```

## Troubleshooting Setup Error States

When starting up or loading the home page, you may see specific troubleshooting screens indicating that data or calculation requirements are missing.

### 1. Database Unavailable / Empty Database
- **Symptoms**: Page load fails with "Database Unavailable" or "Database is Empty".
- **Action**: Run the database initialization command to build the SQLite tables and bootstrap the registry:
  ```bash
  python -m market_sniffer.cli db init
  ```

### 2. Canonical Data Missing
- **Symptoms**: Page load fails with "Canonical Data Missing".
- **Action**: Seed the historical data warehouse by running a backfill:
  ```bash
  python -m market_sniffer.cli backfill --profile core --months 24
  ```

### 3. Metrics Not Calculated
- **Symptoms**: Page load fails with "Metrics Not Calculated".
- **Action**: Run the derived metrics backfill command:
  ```bash
  python -m market_sniffer.cli metrics backfill --profile core
  ```

### 4. Evidence Not Evaluated
- **Symptoms**: Page shows "Evidence Not Evaluated" error.
- **Action**: Run evidence evaluation for the target date:
  ```bash
  python -m market_sniffer.cli evidence evaluate --as-of <date>
  ```

## Yahoo Quote Snapshot Persistence

- Manual quote lookups via `POST /quotes/lookup` or `GET /api/quotes/<symbol>` do not write to the database by default.
- To persist a quote snapshot, submit the form with the **"Persist snapshot to Database"** checkbox checked, or pass the query parameter `?persist=true` to the JSON API endpoint.
- This creates a `QuoteSnapshot` entry marked as user-requested. Regular polling remains completely disabled.
