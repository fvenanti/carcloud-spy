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


@router.get("/matriz", response_class=HTMLResponse)
def matriz_view(request: Request):
    """Matriz pivot completa: filas=buckets, cols=agencia×horizonte."""
    from scrapers.buckets import bucket_label, bucket_order
    from datetime import date as _date

    rows = db.matrix_data()
    horizons = db.list_pickup_dates()
    agencias = db.list_agencias()

    # pickup_dates únicos en orden cronológico
    pickup_dates = [h["pickup_date"] for h in horizons]
    today = _date.today().isoformat()

    def horizon_label(pd: str) -> str:
        try:
            from datetime import datetime as dt_
            d = dt_.fromisoformat(pd).date()
            delta_days = (d - _date.today()).days
            if delta_days <= 1:
                return "Hoy"
            if 25 <= delta_days <= 35:
                return "+1m"
            if 55 <= delta_days <= 65:
                return "+2m"
            if 85 <= delta_days <= 95:
                return "+3m"
            return f"+{delta_days}d"
        except Exception:
            return pd

    pickup_labels = [(pd, horizon_label(pd)) for pd in pickup_dates]
    agencia_list = [(a["slug"], a["nombre"]) for a in agencias]

    # Pivot: {bucket: {agencia_slug: {pickup_date: precio}}}
    matrix: dict[str, dict[str, dict[str, dict]]] = {}
    for r in rows:
        b = r["bucket"]
        matrix.setdefault(b, {}).setdefault(r["agencia_slug"], {})[r["pickup_date"]] = {
            "precio": r["precio"],
            "moneda": r["moneda"],
        }

    # Ordenar buckets
    bucket_rows = []
    for b in sorted(matrix.keys(), key=bucket_order):
        bucket_rows.append({
            "slug": b,
            "label": bucket_label(b),
            "data": matrix[b],
        })

    return templates.TemplateResponse(
        "matriz.html",
        {
            "request": request,
            "agencias": agencia_list,
            "pickup_labels": pickup_labels,
            "buckets": bucket_rows,
            "moneda_default": "ARS",
        },
    )


@router.get("/buckets", response_class=HTMLResponse)
def buckets_view(request: Request, pickup: str | None = None):
    """Comparativo por bucket canónico cross-agencia para un horizonte.

    Por cada bucket muestra una fila por agencia con su precio (la categoría
    nativa más barata si hay varias). Permite cruzar precios "manzana con manzana".
    """
    from scrapers.buckets import bucket_label, bucket_order, BUCKET_META

    horizons = db.list_pickup_dates()
    selected_pickup = pickup or (horizons[0]["pickup_date"] if horizons else None)

    rows = db.latest_rates_by_bucket(pickup_date=selected_pickup) if selected_pickup else []
    agencias = db.list_agencias()
    agencia_slugs = [a["slug"] for a in agencias]
    agencia_names = {a["slug"]: a["nombre"] for a in agencias}

    # Pivot: {bucket: {agencia_slug: [rows...]}}
    pivot: dict[str, dict[str, list]] = {}
    for r in rows:
        b = r["bucket"] or "_unmapped"
        pivot.setdefault(b, {}).setdefault(r["agencia_slug"], []).append(dict(r))

    # Construir filas ordenadas. Cada fila: {bucket, label, agencies: {slug: best_row|None}}
    table_rows = []
    seen_buckets = set()
    for bucket_slug in sorted(pivot.keys(), key=bucket_order):
        if bucket_slug == "_unmapped":
            continue
        seen_buckets.add(bucket_slug)
        per_agency = pivot[bucket_slug]
        cells = {}
        for slug in agencia_slugs:
            cands = per_agency.get(slug, [])
            best = min(cands, key=lambda x: x["precio_total"]) if cands else None
            cells[slug] = best
        prices = [c["precio_total"] for c in cells.values() if c]
        cheapest_slug = None
        if prices:
            min_p = min(prices)
            cheapest_slug = next(slug for slug, c in cells.items() if c and c["precio_total"] == min_p)
        table_rows.append({
            "bucket": bucket_slug,
            "label": bucket_label(bucket_slug),
            "cells": cells,
            "cheapest_slug": cheapest_slug,
        })

    # Categorías sin bucket asignado (info para el usuario)
    unmapped = []
    for slug, per_agency in pivot.items():
        if slug != "_unmapped":
            continue
        for agency_slug, items in per_agency.items():
            for it in items:
                unmapped.append({
                    "agencia": agency_slug,
                    "categoria": it["categoria"],
                    "modelo": it["modelo"],
                    "precio_total": it["precio_total"],
                })

    return templates.TemplateResponse(
        "buckets.html",
        {
            "request": request,
            "horizons": horizons,
            "selected_pickup": selected_pickup,
            "table_rows": table_rows,
            "agencia_slugs": agencia_slugs,
            "agencia_names": agencia_names,
            "unmapped": unmapped,
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
