"""Scrape remoto: cotiza agencias que bloquean la IP de la EC2 y manda el
resultado a CarCloudSPY via POST /api/rates/ingest.

Corre en GitHub Actions (.github/workflows/remote-scrape.yml), 1 vez por dia.
Cada corrida sale de un runner con IP distinta a la EC2.

Solo usa `_fetch_live` (nunca el fallback demo): si falla, manda la tanda como
error y el server lo registra en scrape_runs.

Env vars:
    SPY_BASE_URL          ej. https://spy.aba.benvert.com.ar
    SPY_INGEST_TOKEN      igual a RATES_INGEST_TOKEN del .env del server
    REMOTE_AGENCIES       CSV de slugs (default: correntoso)
    HORIZONS_DAYS_AHEAD / RENTAL_DAYS  igual que el server
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scrapers import ADAPTERS  # noqa: E402
from scrapers.base import queries_from_env  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("remote_scrape")


def main() -> int:
    base_url = os.environ["SPY_BASE_URL"].rstrip("/")
    token = os.environ["SPY_INGEST_TOKEN"]
    slugs = [s.strip() for s in os.getenv("REMOTE_AGENCIES", "correntoso").split(",") if s.strip()]
    queries = queries_from_env()

    failed_all = True
    for slug in slugs:
        batches = []
        with ADAPTERS[slug]() as adapter:
            for q in queries:
                captured_at = datetime.now(timezone.utc)
                try:
                    result = adapter._fetch_live(q)
                    quotes = [asdict(x) for x in result.quotes]
                    batches.append({"pickup_date": q.pickup_date.isoformat(),
                                    "dropoff_date": q.dropoff_date.isoformat(),
                                    "captured_at": result.captured_at.isoformat(),
                                    "quotes": quotes})
                    log.info("[%s] %s: %d quotes", slug, q.pickup_date, len(quotes))
                    failed_all = False
                except Exception as e:
                    log.error("[%s] %s: %s", slug, q.pickup_date, e)
                    batches.append({"pickup_date": q.pickup_date.isoformat(),
                                    "dropoff_date": q.dropoff_date.isoformat(),
                                    "captured_at": captured_at.isoformat(),
                                    "error": str(e)[:500]})
        r = httpx.post(f"{base_url}/api/rates/ingest",
                       json={"agencia_slug": slug, "batches": batches},
                       headers={"X-Auth-Token": token}, timeout=60)
        log.info("[%s] POST ingest -> %d %s", slug, r.status_code, r.text[:300])
        r.raise_for_status()
    return 1 if failed_all else 0


if __name__ == "__main__":
    sys.exit(main())
