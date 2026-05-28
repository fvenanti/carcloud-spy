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
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from zoneinfo import ZoneInfo

import database as db
from scrapers import ADAPTERS, RateAdapter
from scrapers.base import RateQuery

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _queries_from_env() -> list[RateQuery]:
    """Construye N queries (uno por horizonte) según HORIZONS_DAYS_AHEAD."""
    horizons_csv = os.getenv("HORIZONS_DAYS_AHEAD", "0,30,60,90")
    rental_days  = int(os.getenv("RENTAL_DAYS", "7"))
    location     = os.getenv("PICKUP_LOCATION", "BRC")

    today = date.today()
    queries: list[RateQuery] = []
    for raw in horizons_csv.split(","):
        raw = raw.strip()
        if not raw:
            continue
        offset = int(raw)
        # Si pickup=hoy y la hora del scrape ya pasó las 10:00 ART (default
        # del adapter Hertz), el sitio puede rechazar la fecha. Mantenemos
        # offset literal — los adapters logean error y siguen.
        pickup = today + timedelta(days=offset)
        queries.append(RateQuery(
            pickup_location=location,
            pickup_date=pickup,
            dropoff_date=pickup + timedelta(days=rental_days),
        ))
    return queries


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
    """Una corrida completa: para cada horizonte, todos los adapters activos."""
    queries = _queries_from_env()
    log.info("== Iniciando corrida de scraping (%d horizontes) ==", len(queries))
    agencias = {a["slug"]: a for a in db.list_agencias(only_active=True)}

    total = 0
    for q in queries:
        log.info("-- Horizonte pickup=%s dropoff=%s (%dd) --",
                 q.pickup_date, q.dropoff_date, q.rental_days)
        for slug, cls in ADAPTERS.items():
            agencia = agencias.get(slug)
            if not agencia:
                log.warning("Agencia %s no esta activa en DB, salteando", slug)
                continue
            with cls() as adapter:
                total += _run_adapter(adapter, int(agencia["id"]), q)
    log.info("== Corrida terminada. Total rates: %d ==", total)


def run_promo_scrape() -> None:
    """Scrape diario de promociones web (4 agencias).

    Las promos detectadas se persisten en `promociones`. La dedupe es por
    `hash` (sha256 de source+url+raw_text), asi que correr varias veces el
    mismo dia no genera filas duplicadas.

    Las promos de Instagram se ingresan via API (`/api/promos/ingest_ig`)
    desde un cliente local con Chrome real logueado.
    """
    from scrapers.promos import scrape_web_promos

    log.info("== Iniciando scrape de promos web ==")
    promos = scrape_web_promos()
    nuevas = 0
    for p in promos:
        if db.upsert_promo(p.to_db_dict()):
            nuevas += 1
    log.info("== Promos web: %d candidatas, %d nuevas ==", len(promos), nuevas)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler:
        return _scheduler

    interval_min = int(os.getenv("SCRAPE_INTERVAL_MIN", "15"))
    promo_hour   = int(os.getenv("PROMO_SCRAPE_HOUR_ART", "8"))
    art_tz       = ZoneInfo("America/Argentina/Buenos_Aires")
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
    sched.add_job(
        run_promo_scrape,
        trigger=CronTrigger(hour=promo_hour, minute=0, timezone=art_tz),
        id="promo_scrape_web",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    log.info("Scheduler arrancado: rates cada %d min, promos web diario a %02d:00 ART",
             interval_min, promo_hour)
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
