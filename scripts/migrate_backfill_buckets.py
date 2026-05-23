"""Migración: backfill columna `bucket` en `vehiculos` usando el mapping.

Idempotente. Se puede correr cualquier cantidad de veces sin efectos secundarios.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("/app/data/carcloudspy.db")
if not DB_PATH.exists():
    DB_PATH = Path(__file__).resolve().parent.parent / "data" / "carcloudspy.db"

# Importar el mapping
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scrapers.buckets import get_bucket  # noqa: E402


def main():
    print(f"DB: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Asegurar columna existe
    cols = {row["name"] for row in cur.execute("PRAGMA table_info(vehiculos)").fetchall()}
    if "bucket" not in cols:
        print("Agregando columna bucket...")
        cur.execute("ALTER TABLE vehiculos ADD COLUMN bucket TEXT")

    rows = cur.execute("""
        SELECT v.id, v.categoria, v.bucket, a.slug AS agencia_slug
          FROM vehiculos v JOIN agencias a ON a.id = v.agencia_id
    """).fetchall()

    print(f"\nVehiculos a evaluar: {len(rows)}")
    updates = 0
    sin_mapping: list[tuple[str, str]] = []
    for r in rows:
        new_bucket = get_bucket(r["agencia_slug"], r["categoria"])
        if (new_bucket or None) != (r["bucket"] or None):
            cur.execute("UPDATE vehiculos SET bucket=? WHERE id=?", (new_bucket, r["id"]))
            updates += 1
        if not new_bucket:
            sin_mapping.append((r["agencia_slug"], r["categoria"]))

    conn.commit()
    print(f"\n[OK] {updates} vehiculos actualizados.")

    if sin_mapping:
        print(f"\n[!] {len(sin_mapping)} vehiculos sin mapping (quedaron en bucket NULL):")
        for slug, cat in sin_mapping:
            print(f"  - {slug:15} {cat!r}")

    # Resumen por bucket
    print("\n--- Resumen por bucket ---")
    counts = cur.execute("""
        SELECT COALESCE(bucket, '(sin bucket)') AS bucket, COUNT(*) AS n
          FROM vehiculos GROUP BY bucket ORDER BY n DESC
    """).fetchall()
    for r in counts:
        print(f"  {r['bucket']:25} {r['n']:>3} vehiculos")

    conn.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
