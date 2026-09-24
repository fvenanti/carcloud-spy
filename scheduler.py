"""Scheduler de scraping para CarCloudSPY.

APScheduler dispara `run_all` 1 vez por dia a las `SCRAPE_HOUR_ART` (hora
Argentina). Cada corrida consulta a los adapters secuencialmente, persiste
rates y registra el run. Al arrancar, si no hubo corrida ok en las ultimas
20h, corre una inmediatamente (para no perder el dia por un deploy).

Las agencias en `REMOTE_AGENCIES` (default: correntoso, que bloquea la IP de
la EC2) no se scrapean desde aca: las cotiza un workflow de GitHub Actions
(`tools/remote_scrape.py`) y las manda a `/api/rates/ingest`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

import database as db
from scrapers import ADAPTERS, RateAdapter
from scrapers.base import AdapterResult, RateQuery, queries_from_env

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

ART = ZoneInfo("America/Argentina/Buenos_Aires")


def remote_agencies() -> set[str]:
    raw = os.getenv("REMOTE_AGENCIES", "correntoso")
    return {s.strip() for s in raw.split(",") if s.strip()}


def persist_result(agencia_id: int, query: RateQuery, result: AdapterResult) -> int:
    """Guarda las quotes de una tanda (una agencia x un horizonte)."""
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
    return db.insert_rates(rows)


def _run_adapter(adapter: RateAdapter, agencia_id: int, query: RateQuery) -> int:
    run_id = db.start_run(agencia_id)
    try:
        result = adapter.fetch(query)
        n = persist_result(agencia_id, query, result)
        db.finish_run(run_id, status="ok", rates_count=n)
        log.info("[%s] %d rates capturados", adapter.slug, n)
        return n
    except Exception as e:
        log.exception("Error en adapter %s", adapter.slug)
        db.finish_run(run_id, status="error", error_msg=str(e))
        return 0


def run_all() -> None:
    """Una corrida completa: para cada horizonte, todos los adapters locales."""
    queries = queries_from_env()
    remote = remote_agencies()
    log.info("== Iniciando corrida de scraping (%d horizontes, remotas: %s) ==",
             len(queries), ",".join(sorted(remote)) or "-")
    agencias = {a["slug"]: a for a in db.list_agencias(only_active=True)}

    total = 0
    for q in queries:
        log.info("-- Horizonte pickup=%s dropoff=%s (%dd) --",
                 q.pickup_date, q.dropoff_date, q.rental_days)
        for slug, cls in ADAPTERS.items():
            if slug in remote:
                continue
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

    scrape_hour = int(os.getenv("SCRAPE_HOUR_ART", "6"))
    promo_hour  = int(os.getenv("PROMO_SCRAPE_HOUR_ART", "8"))
    sched = BackgroundScheduler(timezone=timezone.utc)

    # Si el container arranca y no hubo corrida ok en 20h, correr ya.
    last_ok = db.last_ok_run_at()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    catch_up = last_ok is None or (now_utc - last_ok) > timedelta(hours=20)

    # OJO: next_run_time=None pausaria el job; solo se pasa si hay catch-up.
    extra = {"next_run_time": datetime.now(timezone.utc)} if catch_up else {}
    sched.add_job(
        run_all,
        trigger=CronTrigger(hour=scrape_hour, minute=0, timezone=ART),
        id="scrape_all",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        **extra,
    )
    sched.add_job(
        run_promo_scrape,
        trigger=CronTrigger(hour=promo_hour, minute=0, timezone=ART),
        id="promo_scrape_web",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    log.info("Scheduler arrancado: rates diario %02d:00 ART%s, promos web diario %02d:00 ART",
             scrape_hour, " (+ corrida de recuperacion ahora)" if catch_up else "", promo_hour)
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
