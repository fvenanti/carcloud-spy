"""Capa de datos SQLite para CarCloudSPY.

Esquema:
    agencias            -> catálogo de rent-a-car monitoreadas
    vehiculos           -> categoría / modelo normalizado por agencia
    rates               -> snapshot histórico (1 fila por scrape por vehículo)
    scrape_runs         -> bitácora de corridas del scheduler

Diseño: append-only en `rates`. La tarifa "actual" es siempre la última fila
por (agencia_id, vehiculo_id) ordenada por captured_at DESC.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

DB_PATH = Path(__file__).parent / "data" / "carcloudspy.db"


def _ensure_dir() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Crea el esquema y siembra las 4 agencias iniciales."""
    with get_conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS agencias (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                slug            TEXT NOT NULL UNIQUE,
                nombre          TEXT NOT NULL,
                url_base        TEXT NOT NULL,
                activo          INTEGER NOT NULL DEFAULT 1,
                created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS vehiculos (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agencia_id      INTEGER NOT NULL REFERENCES agencias(id) ON DELETE CASCADE,
                categoria       TEXT NOT NULL,
                modelo          TEXT,
                transmision     TEXT,
                pasajeros       INTEGER,
                external_code   TEXT,
                created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agencia_id, categoria, modelo)
            );

            CREATE TABLE IF NOT EXISTS rates (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agencia_id      INTEGER NOT NULL REFERENCES agencias(id) ON DELETE CASCADE,
                vehiculo_id     INTEGER NOT NULL REFERENCES vehiculos(id) ON DELETE CASCADE,
                pickup_date     DATE NOT NULL,
                dropoff_date    DATE NOT NULL,
                rental_days     INTEGER NOT NULL,
                moneda          TEXT NOT NULL,
                precio_total    REAL NOT NULL,
                precio_por_dia  REAL,
                disponible      INTEGER NOT NULL DEFAULT 1,
                raw_payload     TEXT,
                captured_at     TIMESTAMP NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rates_lookup
                ON rates(agencia_id, vehiculo_id, captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_rates_captured
                ON rates(captured_at DESC);

            CREATE TABLE IF NOT EXISTS scrape_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agencia_id      INTEGER NOT NULL REFERENCES agencias(id) ON DELETE CASCADE,
                started_at      TIMESTAMP NOT NULL,
                finished_at     TIMESTAMP,
                status          TEXT NOT NULL,
                rates_count     INTEGER NOT NULL DEFAULT 0,
                error_msg       TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_runs_started
                ON scrape_runs(started_at DESC);
            """
        )

        # Seed agencias iniciales (idempotente)
        seed = [
            ("aba", "ABA Rent a Car Bariloche", "https://aba.benvert.com.ar/"),
            ("hertz", "Hertz Bariloche Aeropuerto", "https://www.hertz.com.ar/"),
            ("localiza", "Localiza Bariloche", "https://www.localiza.com/argentina/"),
            ("sixt", "Sixt Bariloche", "https://www.sixt.com.ar/"),
            ("taraborelli", "Taraborelli Bariloche Aeropuerto", "https://www.taraborellirentacar.com/"),
        ]
        c.executemany(
            "INSERT OR IGNORE INTO agencias (slug, nombre, url_base) VALUES (?, ?, ?)",
            seed,
        )


def list_agencias(only_active: bool = True) -> list[sqlite3.Row]:
    with get_conn() as c:
        q = "SELECT * FROM agencias"
        if only_active:
            q += " WHERE activo = 1"
        q += " ORDER BY nombre"
        return c.execute(q).fetchall()


def get_or_create_vehiculo(
    agencia_id: int,
    categoria: str,
    modelo: str | None = None,
    transmision: str | None = None,
    pasajeros: int | None = None,
    external_code: str | None = None,
) -> int:
    with get_conn() as c:
        row = c.execute(
            "SELECT id FROM vehiculos WHERE agencia_id=? AND categoria=? AND IFNULL(modelo,'')=IFNULL(?, '')",
            (agencia_id, categoria, modelo),
        ).fetchone()
        if row:
            return int(row["id"])
        cur = c.execute(
            """INSERT INTO vehiculos
                 (agencia_id, categoria, modelo, transmision, pasajeros, external_code)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (agencia_id, categoria, modelo, transmision, pasajeros, external_code),
        )
        return int(cur.lastrowid)


def insert_rates(rows: Iterable[dict]) -> int:
    """Inserta una tanda de rates. Cada dict debe traer todos los campos NOT NULL."""
    payload = list(rows)
    if not payload:
        return 0
    with get_conn() as c:
        c.executemany(
            """INSERT INTO rates
                 (agencia_id, vehiculo_id, pickup_date, dropoff_date, rental_days,
                  moneda, precio_total, precio_por_dia, disponible, raw_payload, captured_at)
               VALUES
                 (:agencia_id, :vehiculo_id, :pickup_date, :dropoff_date, :rental_days,
                  :moneda, :precio_total, :precio_por_dia, :disponible, :raw_payload, :captured_at)""",
            payload,
        )
        return len(payload)


def start_run(agencia_id: int) -> int:
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO scrape_runs (agencia_id, started_at, status) VALUES (?, ?, 'running')",
            (agencia_id, datetime.now(timezone.utc)),
        )
        return int(cur.lastrowid)


def finish_run(run_id: int, status: str, rates_count: int = 0, error_msg: str | None = None) -> None:
    with get_conn() as c:
        c.execute(
            """UPDATE scrape_runs
                  SET finished_at=?, status=?, rates_count=?, error_msg=?
                WHERE id=?""",
            (datetime.now(timezone.utc), status, rates_count, error_msg, run_id),
        )


def latest_rates(pickup_date: str | None = None) -> list[sqlite3.Row]:
    """Última tarifa conocida por (agencia, vehículo, pickup_date).

    Si `pickup_date` viene seteado (YYYY-MM-DD), filtra solo ese horizonte.
    """
    params: list = []
    where = ""
    if pickup_date:
        where = "WHERE pickup_date = ?"
        params.append(pickup_date)
    with get_conn() as c:
        return c.execute(
            f"""
            WITH latest AS (
                SELECT r.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY agencia_id, vehiculo_id, pickup_date
                           ORDER BY captured_at DESC
                       ) AS rn
                  FROM rates r
                  {where}
            )
            SELECT  a.slug      AS agencia_slug,
                    a.nombre    AS agencia_nombre,
                    v.categoria AS categoria,
                    v.modelo    AS modelo,
                    v.transmision,
                    v.pasajeros,
                    l.pickup_date,
                    l.dropoff_date,
                    l.rental_days,
                    l.moneda,
                    l.precio_total,
                    l.precio_por_dia,
                    l.disponible,
                    l.captured_at,
                    l.agencia_id,
                    l.vehiculo_id
              FROM latest l
              JOIN agencias  a ON a.id = l.agencia_id
              JOIN vehiculos v ON v.id = l.vehiculo_id
             WHERE l.rn = 1
             ORDER BY a.nombre, l.precio_total
            """,
            params,
        ).fetchall()


def list_pickup_dates(max_age_hours: int = 2) -> list[sqlite3.Row]:
    """Pickup_dates con observaciones recientes (default últimas 2h).

    Para cada pickup_date toma `rental_days`/`dropoff_date` de la observación
    más reciente (refleja la configuración activa del scheduler, no el legacy).
    """
    with get_conn() as c:
        return c.execute(
            """
            WITH latest_per_pickup AS (
                SELECT pickup_date,
                       rental_days,
                       dropoff_date,
                       captured_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY pickup_date
                           ORDER BY captured_at DESC
                       ) AS rn
                  FROM rates
            ),
            counts AS (
                SELECT pickup_date,
                       COUNT(*)        AS rates_count,
                       MAX(captured_at) AS last_captured
                  FROM rates
                 GROUP BY pickup_date
            )
            SELECT l.pickup_date,
                   l.rental_days,
                   l.dropoff_date,
                   c.rates_count,
                   c.last_captured
              FROM latest_per_pickup l
              JOIN counts c USING (pickup_date)
             WHERE l.rn = 1
               AND c.last_captured > datetime('now', ?)
             ORDER BY l.pickup_date ASC
            """,
            (f"-{max_age_hours} hours",),
        ).fetchall()


def latest_rates_all_horizons(max_age_hours: int = 6) -> list[sqlite3.Row]:
    """Última tarifa por (agencia, vehiculo, pickup_date) para horizontes activos.

    Pensada para pivot: cada fila es 1 punto del cruce. El router agrupa por
    (agencia, vehiculo) y arma columnas por pickup_date.
    """
    with get_conn() as c:
        return c.execute(
            """
            WITH latest AS (
                SELECT r.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY agencia_id, vehiculo_id, pickup_date
                           ORDER BY captured_at DESC
                       ) AS rn
                  FROM rates r
                 WHERE captured_at > datetime('now', ?)
            )
            SELECT  a.slug      AS agencia_slug,
                    a.nombre    AS agencia_nombre,
                    v.categoria AS categoria,
                    v.modelo    AS modelo,
                    v.transmision,
                    v.pasajeros,
                    l.pickup_date,
                    l.dropoff_date,
                    l.rental_days,
                    l.moneda,
                    l.precio_total,
                    l.precio_por_dia,
                    l.disponible,
                    l.captured_at,
                    l.agencia_id,
                    l.vehiculo_id
              FROM latest l
              JOIN agencias  a ON a.id = l.agencia_id
              JOIN vehiculos v ON v.id = l.vehiculo_id
             WHERE l.rn = 1
             ORDER BY a.nombre, v.categoria, l.precio_total, l.pickup_date
            """,
            (f"-{max_age_hours} hours",),
        ).fetchall()


def rate_history(agencia_id: int, vehiculo_id: int, limit: int = 200) -> list[sqlite3.Row]:
    with get_conn() as c:
        return c.execute(
            """SELECT precio_total, precio_por_dia, moneda, captured_at
                 FROM rates
                WHERE agencia_id=? AND vehiculo_id=?
                ORDER BY captured_at DESC
                LIMIT ?""",
            (agencia_id, vehiculo_id, limit),
        ).fetchall()


def recent_runs(limit: int = 20) -> list[sqlite3.Row]:
    with get_conn() as c:
        return c.execute(
            """SELECT r.*, a.nombre AS agencia_nombre, a.slug AS agencia_slug
                 FROM scrape_runs r
                 JOIN agencias a ON a.id = r.agencia_id
                ORDER BY started_at DESC
                LIMIT ?""",
            (limit,),
        ).fetchall()
