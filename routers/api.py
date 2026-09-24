"""Endpoints JSON consumidos por el dashboard via fetch() + ingest externos."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

import database as db
from scheduler import persist_result, run_all
from scrapers.base import AdapterResult, RateQuery, RateQuote
from scrapers.promos import promo_from_ig_post

log = logging.getLogger(__name__)

router = APIRouter()


def _row_to_dict(r) -> dict:
    return {k: r[k] for k in r.keys()}


@router.get("/rates")
def rates(pickup: str | None = None):
    rows = db.latest_rates(pickup_date=pickup)
    return {"count": len(rows), "pickup": pickup, "rates": [_row_to_dict(r) for r in rows]}


@router.get("/horizons")
def horizons():
    rows = db.list_pickup_dates()
    return {"horizons": [_row_to_dict(r) for r in rows]}


@router.get("/history/{agencia_id}/{vehiculo_id}")
def history(agencia_id: int, vehiculo_id: int, limit: int = 200):
    rows = db.rate_history(agencia_id, vehiculo_id, limit=limit)
    return {"history": [_row_to_dict(r) for r in rows]}


@router.get("/runs")
def runs(limit: int = 20):
    rows = db.recent_runs(limit=limit)
    return {"runs": [_row_to_dict(r) for r in rows]}


@router.post("/refresh")
def refresh():
    """Dispara una corrida manual (útil para testing/demo)."""
    try:
        run_all()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Ingest de promociones desde Instagram (cliente local Windows)
# ============================================================

class IgPostIn(BaseModel):
    url: str
    caption: str
    posted_at: str | None = None  # ISO 8601


class IgBatchIn(BaseModel):
    agencia_slug: str
    posts: list[IgPostIn]


def _check_token(x_auth_token: str | None) -> None:
    expected = os.getenv("PROMO_INGEST_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ingest disabled: PROMO_INGEST_TOKEN not set")
    if not x_auth_token or x_auth_token.strip() != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@router.post("/promos/ingest_ig")
def ingest_ig(batch: IgBatchIn, x_auth_token: str | None = Header(None, alias="X-Auth-Token")):
    """Recibe posts de IG de una agencia. Server detecta promos y guarda matches."""
    _check_token(x_auth_token)
    log.info("ingest_ig: %s -> %d posts", batch.agencia_slug, len(batch.posts))
    detectadas = 0
    nuevas = 0
    for p in batch.posts:
        promo = promo_from_ig_post(
            agencia_slug=batch.agencia_slug,
            post_url=p.url,
            caption=p.caption,
            posted_at=p.posted_at,
        )
        if not promo:
            continue
        detectadas += 1
        if db.upsert_promo(promo.to_db_dict()):
            nuevas += 1
    return {
        "received": len(batch.posts),
        "detected": detectadas,
        "new": nuevas,
    }


# ============================================================
# Ingest de rates capturados fuera de la EC2 (GitHub Actions)
# ============================================================
# Correntoso bloquea la IP de la EC2 (403). tools/remote_scrape.py lo cotiza
# desde un runner de GitHub Actions y manda el resultado aca.

class QuoteIn(BaseModel):
    categoria: str
    modelo: str | None = None
    moneda: str
    precio_total: float
    precio_por_dia: float | None = None
    transmision: str | None = None
    pasajeros: int | None = None
    external_code: str | None = None
    disponible: bool = True
    raw_payload: str | None = None


class BatchIn(BaseModel):
    pickup_date: date
    dropoff_date: date
    captured_at: datetime
    quotes: list[QuoteIn] = []
    error: str | None = None


class RatesIngestIn(BaseModel):
    agencia_slug: str
    batches: list[BatchIn]


@router.post("/rates/ingest")
def ingest_rates(body: RatesIngestIn, x_auth_token: str | None = Header(None, alias="X-Auth-Token")):
    expected = os.getenv("RATES_INGEST_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ingest disabled: RATES_INGEST_TOKEN not set")
    if not x_auth_token or x_auth_token.strip() != expected:
        raise HTTPException(status_code=401, detail="unauthorized")

    agencia = next((a for a in db.list_agencias() if a["slug"] == body.agencia_slug), None)
    if not agencia:
        raise HTTPException(status_code=404, detail=f"agencia {body.agencia_slug!r} no existe o inactiva")
    agencia_id = int(agencia["id"])

    saved = 0
    for b in body.batches:
        run_id = db.start_run(agencia_id)
        if b.error or not b.quotes:
            db.finish_run(run_id, status="error", error_msg=f"remoto: {b.error or 'sin quotes'}")
            continue
        query = RateQuery(pickup_location="BRC", pickup_date=b.pickup_date, dropoff_date=b.dropoff_date)
        cap = b.captured_at if b.captured_at.tzinfo else b.captured_at.replace(tzinfo=timezone.utc)
        result = AdapterResult(
            quotes=[RateQuote(**q.model_dump()) for q in b.quotes],
            captured_at=cap.astimezone(timezone.utc),
        )
        n = persist_result(agencia_id, query, result)
        db.finish_run(run_id, status="ok", rates_count=n)
        saved += n
    log.info("ingest_rates: %s -> %d batches, %d rates", body.agencia_slug, len(body.batches), saved)
    return {"batches": len(body.batches), "saved": saved}
