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


@router.get("/comparativo", response_class=HTMLResponse)
def comparativo(request: Request):
    """Tabla pivot: filas=(agencia, vehiculo), columnas=horizonte. Delta vs hoy."""
    horizons = db.list_pickup_dates()
    pickup_dates = [h["pickup_date"] for h in horizons]
    rows = db.latest_rates_all_horizons()

    # Pivot: {agencia_nombre: {(categoria, modelo, transmision, pasajeros, agencia_id, vehiculo_id): {pickup_date: row}}}
    pivot: dict[str, dict[tuple, dict[str, dict]]] = {}
    for r in rows:
        key = (r["categoria"], r["modelo"] or "", r["transmision"] or "",
               r["pasajeros"] or 0, r["agencia_id"], r["vehiculo_id"])
        pivot.setdefault(r["agencia_nombre"], {}).setdefault(key, {})[r["pickup_date"]] = dict(r)

    # Ordenar filas dentro de cada agencia: por precio del primer horizonte
    sorted_pivot: dict[str, list[tuple]] = {}
    base_pd = pickup_dates[0] if pickup_dates else None
    for agencia, vehiculos in pivot.items():
        items = list(vehiculos.items())
        items.sort(key=lambda kv: (
            kv[1].get(base_pd, {}).get("precio_total") or 9e15,
            kv[0][0],  # categoria
        ))
        sorted_pivot[agencia] = items

    return templates.TemplateResponse(
        "comparativo.html",
        {
            "request": request,
            "horizons": horizons,
            "pickup_dates": pickup_dates,
            "pivot": sorted_pivot,
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
