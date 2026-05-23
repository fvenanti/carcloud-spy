"""Vista principal: dashboard de tarifas en vivo."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

import database as db
from shared_templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    rates = db.latest_rates()
    runs = db.recent_runs(limit=8)
    agencias = db.list_agencias()

    # Agrupar por agencia para la grilla
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
