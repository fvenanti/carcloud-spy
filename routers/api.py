"""Endpoints JSON consumidos por el dashboard via fetch()."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import database as db
from scheduler import run_all

router = APIRouter()


def _row_to_dict(r) -> dict:
    return {k: r[k] for k in r.keys()}


@router.get("/rates")
def rates():
    rows = db.latest_rates()
    return {"count": len(rows), "rates": [_row_to_dict(r) for r in rows]}


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
