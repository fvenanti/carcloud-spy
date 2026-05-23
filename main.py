"""CarCloudSPY — monitor de tarifas de rent-a-car en Bariloche.

Stack: FastAPI + Jinja2 SSR + SQLite + APScheduler (alineado a CarCloud).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import database as db
from routers import api as api_router
from routers import dashboard as dashboard_router
from scheduler import start_scheduler, stop_scheduler

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("carcloudspy")

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Inicializando DB...")
    db.init_db()
    log.info("Arrancando scheduler...")
    start_scheduler()
    yield
    log.info("Deteniendo scheduler...")
    stop_scheduler()


app = FastAPI(
    title="CarCloudSPY",
    description="Monitor en tiempo real de tarifas de rent-a-car en San Carlos de Bariloche",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(dashboard_router.router)
app.include_router(api_router.router, prefix="/api")
