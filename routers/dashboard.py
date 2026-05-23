"""Vista principal: dashboard de tarifas en vivo."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

import database as db
from shared_templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, pickup: str | None = None):
    horizons = db.list_pickup_dates()
    # Si el query string no especifica pickup, default al primero (más cercano).
    selected_pickup = pickup or (horizons[0]["pickup_date"] if horizons else None)

    rates = db.latest_rates(pickup_date=selected_pickup) if selected_pickup else []
    runs = db.recent_runs(limit=8)
    agencias = db.list_agencias()

    grouped: dict[str, list] = {}
    for r in rates:
        grouped.setdefault(r["agencia_nombre"], []).append(r)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "grouped": grouped,
            "runs": runs,
            "agencias": agencias,
            "total_rates": len(rates),
            "horizons": horizons,
            "selected_pickup": selected_pickup,
        },
    )


@router.get("/historial/{agencia_id}/{vehiculo_id}", response_class=HTMLResponse)
def historial(request: Request, agencia_id: int, vehiculo_id: int):
    history = db.rate_history(agencia_id, vehiculo_id, limit=500)
    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "history": history,
            "agencia_id": agencia_id,
            "vehiculo_id": vehiculo_id,
        },
    )
