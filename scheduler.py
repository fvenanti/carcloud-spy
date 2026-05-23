"""Scheduler de scraping para CarCloudSPY.

APScheduler dispara `run_all` cada `SCRAPE_INTERVAL_MIN` minutos. Cada corrida
consulta a los 4 adapters secuencialmente, persiste rates y registra el run.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import database as db
from scrapers import ADAPTERS, RateAdapter
from scrapers.base import RateQuery

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _query_from_env() -> RateQuery:
    pickup = date.today() + timedelta(days=int(os.getenv("PICKUP_DAYS_AHEAD", "7")))
    rental_days = int(os.getenv("RENTAL_DAYS", "3"))
    return RateQuery(
        pickup_location=os.getenv("PICKUP_LOCATION", "BRC"),
        pickup_date=pickup,
        dropoff_date=pickup + timedelta(days=rental_days),
    )


def _run_adapter(adapter: RateAdapter, agencia_id: int, query: RateQuery) -> int:
    run_id = db.start_run(agencia_id)
    try:
        result = adapter.fetch(query)
        rows = []
        for q in result.quotes:
            vehiculo_id = db.get_or_create_vehiculo(
                agencia_id=agencia_id,
                categoria=q.categoria,
                modelo=q.modelo,
                transmision=q.transmision,
                pasajeros=q.pasajeros,
                external_code=q.external_code,
            )
            rows.append({
                "agencia_id": agencia_id,
                "vehiculo_id": vehiculo_id,
                "pickup_date": query.pickup_date,
                "dropoff_date": query.dropoff_date,
                "rental_days": query.rental_days,
                "moneda": q.moneda,
                "precio_total": q.precio_total,
                "precio_por_dia": q.precio_por_dia,
                "disponible": 1 if q.disponible else 0,
                "raw_payload": q.raw_payload if isinstance(q.raw_payload, str) else json.dumps(q.raw_payload),
                "captured_at": result.captured_at,
            })
        n = db.insert_rates(rows)
        db.finish_run(run_id, status="ok", rates_count=n)
        log.info("[%s] %d rates capturados", adapter.slug, n)
        return n
    except Exception as e:
        log.exception("Error en adapter %s", adapter.slug)
        db.finish_run(run_id, status="error", error_msg=str(e))
        return 0


def run_all() -> None:
    """Una corrida completa: todos los adapters activos."""
    log.info("== Iniciando corrida de scraping ==")
    query = _query_from_env()
    agencias = {a["slug"]: a for a in db.list_agencias(only_active=True)}

    total = 0
    for slug, cls in ADAPTERS.items():
        agencia = agencias.get(slug)
        if not agencia:
            log.warning("Agencia %s no está activa en DB, salteando", slug)
            continue
        with cls() as adapter:
            total += _run_adapter(adapter, int(agencia["id"]), query)
    log.info("== Corrida terminada. Total rates: %d ==", total)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler:
        return _scheduler

    interval_min = int(os.getenv("SCRAPE_INTERVAL_MIN", "15"))
    sched = BackgroundScheduler(timezone=timezone.utc)
    sched.add_job(
        run_all,
        trigger=IntervalTrigger(minutes=interval_min),
        id="scrape_all",
        next_run_time=datetime.now(timezone.utc),  # disparar inmediato al arrancar
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    log.info("Scheduler arrancado: cada %d minutos", interval_min)
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
