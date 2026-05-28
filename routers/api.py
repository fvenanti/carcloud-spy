"""Endpoints JSON consumidos por el dashboard via fetch() + ingest externos."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

import database as db
from scheduler import run_all
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
