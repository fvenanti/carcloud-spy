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


def _ensure_bucket_column(c: sqlite3.Connection) -> None:
    """Agrega la columna `bucket` si no existe (migracion idempotente)."""
    cols = {row["name"] for row in c.execute("PRAGMA table_info(vehiculos)").fetchall()}
    if "bucket" not in cols:
        c.execute("ALTER TABLE vehiculos ADD COLUMN bucket TEXT")


def _purge_correntoso_legacy(c: sqlite3.Connection) -> None:
    """Borra vehiculos de Correntoso con categoria formato legacy 'X - desc'.

    Bug historico: cuando el live fetch de Correntoso fallaba, el fallback demo
    persistia categoria como 'B - Vehiculo 5 Puertas' (con guion + modelo) en
    vez de solo 'B'. Como el bucket mapping en scrapers/buckets.py espera la
    forma corta, esos vehiculos quedaban con bucket=NULL y nunca aparecian en
    /matriz ni /buckets. ON DELETE CASCADE de rates limpia los precios viejos.
    """
    agencia = c.execute("SELECT id FROM agencias WHERE slug='correntoso'").fetchone()
    if not agencia:
        return
    cur = c.execute(
        "DELETE FROM vehiculos WHERE agencia_id=? AND categoria LIKE '% - %'",
        (int(agencia["id"]),),
    )
    if cur.rowcount:
        log = __import__("logging").getLogger(__name__)
        log.info("Purgadas %d filas legacy de vehiculos de Correntoso", cur.rowcount)


def init_db() -> None:
    """Crea el esquema y siembra las agencias iniciales."""
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
                bucket          TEXT,
                created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agencia_id, categoria)
            );
            -- Migracion idempotente: si la columna no existe la agrega
            -- (PRAGMA en SQLite no soporta IF NOT EXISTS en ADD COLUMN antes de 3.35)

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

            CREATE TABLE IF NOT EXISTS promociones (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                agencia_id        INTEGER NOT NULL REFERENCES agencias(id) ON DELETE CASCADE,
                source            TEXT NOT NULL,
                source_url        TEXT NOT NULL,
                titulo            TEXT NOT NULL,
                descuento_pct     REAL,
                descuento_texto   TEXT,
                vigencia_desde    DATE,
                vigencia_hasta    DATE,
                raw_text          TEXT NOT NULL,
                posted_at         TIMESTAMP,
                scraped_at        TIMESTAMP NOT NULL,
                hash              TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_promos_agencia
                ON promociones(agencia_id, scraped_at DESC);
            CREATE INDEX IF NOT EXISTS idx_promos_scraped
                ON promociones(scraped_at DESC);
            """
        )

        _ensure_bucket_column(c)
        _purge_correntoso_legacy(c)

        # Seed agencias iniciales (idempotente)
        seed = [
            ("aba", "ABA Rent a Car Bariloche", "https://aba.benvert.com.ar/"),
            ("correntoso", "Correntoso Rent a Car", "http://www.correntosorentacar.com/"),
            ("hertz", "Hertz Bariloche Aeropuerto", "https://www.hertz.com.ar/"),
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
    """Upsert por (agencia_id, categoria). Actualiza modelo si rota.
    El bucket se resuelve via scrapers.buckets.get_bucket usando el slug de la agencia."""
    from scrapers.buckets import get_bucket
    with get_conn() as c:
        slug = c.execute("SELECT slug FROM agencias WHERE id=?", (agencia_id,)).fetchone()
        slug_str = slug["slug"] if slug else ""
        bucket = get_bucket(slug_str, categoria)

        row = c.execute(
            "SELECT id, modelo, transmision, pasajeros, external_code, bucket FROM vehiculos WHERE agencia_id=? AND categoria=?",
            (agencia_id, categoria),
        ).fetchone()
        if row:
            vid = int(row["id"])
            needs_update = (
                (modelo or None) != (row["modelo"] or None)
                or (transmision or None) != (row["transmision"] or None)
                or (pasajeros or None) != (row["pasajeros"] or None)
                or (external_code or None) != (row["external_code"] or None)
                or (bucket or None) != (row["bucket"] or None)
            )
            if needs_update:
                c.execute(
                    """UPDATE vehiculos
                          SET modelo=?, transmision=?, pasajeros=?, external_code=?, bucket=?
                        WHERE id=?""",
                    (modelo, transmision, pasajeros, external_code, bucket, vid),
                )
            return vid
        cur = c.execute(
            """INSERT INTO vehiculos
                 (agencia_id, categoria, modelo, transmision, pasajeros, external_code, bucket)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agencia_id, categoria, modelo, transmision, pasajeros, external_code, bucket),
        )
        return int(cur.lastrowid)


def matrix_data(max_age_hours: int = 6) -> list[sqlite3.Row]:
    """Para la vista matriz: por (bucket, agencia, pickup_date) el precio
    mínimo (la categoría nativa más barata de ese bucket para esa agencia)."""
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
            SELECT v.bucket          AS bucket,
                   a.slug            AS agencia_slug,
                   a.nombre          AS agencia_nombre,
                   l.pickup_date     AS pickup_date,
                   MIN(l.precio_total) AS precio,
                   MIN(l.moneda)     AS moneda
              FROM latest l
              JOIN agencias  a ON a.id = l.agencia_id
              JOIN vehiculos v ON v.id = l.vehiculo_id
             WHERE l.rn = 1 AND v.bucket IS NOT NULL
             GROUP BY v.bucket, a.slug, l.pickup_date
             ORDER BY v.bucket, a.slug, l.pickup_date
            """,
            (f"-{max_age_hours} hours",),
        ).fetchall()


def latest_rates_by_bucket(pickup_date: str | None = None) -> list[sqlite3.Row]:
    """Última tarifa por (agencia, vehiculo, pickup_date) con bucket info.

    Para la vista comparativa cross-agencia agrupada por bucket canónico.
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
                    v.categoria,
                    v.modelo,
                    v.transmision,
                    v.pasajeros,
                    v.bucket,
                    l.pickup_date,
                    l.dropoff_date,
                    l.rental_days,
                    l.moneda,
                    l.precio_total,
                    l.precio_por_dia,
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


def rate_history(agencia_id: int, vehiculo_id: int, limit: int = 1000) -> list[sqlite3.Row]:
    """Histórico completo, ordenado cronológicamente, incluyendo pickup_date
    para que el cliente pueda separar las series por horizonte."""
    with get_conn() as c:
        return c.execute(
            """SELECT pickup_date, precio_total, precio_por_dia, moneda, captured_at
                 FROM rates
                WHERE agencia_id=? AND vehiculo_id=?
                ORDER BY captured_at ASC
                LIMIT ?""",
            (agencia_id, vehiculo_id, limit),
        ).fetchall()


def upsert_promo(p: dict) -> bool:
    """Inserta promo si su `hash` no existe ya. True si fue nueva fila."""
    with get_conn() as c:
        agencia = c.execute("SELECT id FROM agencias WHERE slug=?", (p["agencia_slug"],)).fetchone()
        if not agencia:
            return False
        try:
            c.execute(
                """INSERT INTO promociones
                     (agencia_id, source, source_url, titulo, descuento_pct, descuento_texto,
                      vigencia_desde, vigencia_hasta, raw_text, posted_at, scraped_at, hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(agencia["id"]),
                    p["source"],
                    p["source_url"],
                    p["titulo"],
                    p.get("descuento_pct"),
                    p.get("descuento_texto"),
                    p.get("vigencia_desde"),
                    p.get("vigencia_hasta"),
                    p["raw_text"],
                    p.get("posted_at"),
                    datetime.now(timezone.utc),
                    p["hash"],
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def latest_promos(max_age_days: int = 60) -> list[sqlite3.Row]:
    """Promos detectadas en los ultimos N dias, mas recientes primero.

    Ordena por posted_at (si tiene, caso IG) y si no por scraped_at.
    """
    with get_conn() as c:
        return c.execute(
            """SELECT p.*,
                      a.slug   AS agencia_slug,
                      a.nombre AS agencia_nombre
                 FROM promociones p
                 JOIN agencias a ON a.id = p.agencia_id
                WHERE p.scraped_at > datetime('now', ?)
                ORDER BY COALESCE(p.posted_at, p.scraped_at) DESC""",
            (f"-{max_age_days} days",),
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
