"""Migración one-shot: unificar vehiculos por (agencia, categoria).

ANTES: UNIQUE(agencia_id, categoria, modelo) — duplica cuando el modelo rota
DESPUES: UNIQUE(agencia_id, categoria) — el modelo se actualiza en cada scrape

Pasos:
1. Por cada (agencia, categoria) con >1 vehiculo: elegir canonico (mas rates),
   reasignar rates de los duplicados al canonico, borrar duplicados.
2. Borrar vehiculos huerfanos sin rates (legacy del demo).
3. Recrear tabla `vehiculos` con el UNIQUE nuevo.
4. SELECT final para verificar.

Idempotente. Si no hay duplicados, no hace nada destructivo.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("/app/data/carcloudspy.db")
if not DB_PATH.exists():
    DB_PATH = Path(__file__).resolve().parent.parent / "data" / "carcloudspy.db"


def main():
    print(f"DB: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    cur = conn.cursor()

    # 1. Agrupar duplicados
    dups = cur.execute("""
        SELECT agencia_id, categoria, COUNT(*) AS n
          FROM vehiculos
         GROUP BY agencia_id, categoria
        HAVING n > 1
    """).fetchall()
    print(f"\n[1] {len(dups)} categorias con duplicados:")
    moved = 0
    deleted = 0
    for d in dups:
        candidates = cur.execute("""
            SELECT v.id,
                   (SELECT COUNT(*) FROM rates r WHERE r.vehiculo_id=v.id) AS obs
              FROM vehiculos v
             WHERE v.agencia_id=? AND v.categoria=?
             ORDER BY obs DESC, v.id ASC
        """, (d["agencia_id"], d["categoria"])).fetchall()
        canonical = candidates[0]
        losers = candidates[1:]
        print(f"  agencia={d['agencia_id']} cat={d['categoria']!r}: canonical id={canonical['id']} (obs={canonical['obs']}), losers={[(l['id'], l['obs']) for l in losers]}")
        for l in losers:
            n = cur.execute("UPDATE rates SET vehiculo_id=? WHERE vehiculo_id=?",
                            (canonical["id"], l["id"])).rowcount
            moved += n
            cur.execute("DELETE FROM vehiculos WHERE id=?", (l["id"],))
            deleted += 1
    print(f"  -> rates reasignados: {moved}, vehiculos duplicados borrados: {deleted}")

    # 2. Borrar vehiculos huerfanos (sin rates).
    orphans = cur.execute("""
        SELECT v.id, v.categoria, v.modelo
          FROM vehiculos v
         WHERE NOT EXISTS (SELECT 1 FROM rates r WHERE r.vehiculo_id=v.id)
    """).fetchall()
    print(f"\n[2] {len(orphans)} vehiculos huerfanos (obs=0):")
    for o in orphans:
        print(f"  borrando id={o['id']} cat={o['categoria']!r} mod={o['modelo']!r}")
    cur.executemany("DELETE FROM vehiculos WHERE id=?", [(o["id"],) for o in orphans])

    # 3. Recrear tabla vehiculos con UNIQUE(agencia_id, categoria).
    # Verificar si ya tiene el constraint nuevo: si SI, skip.
    sql_actual = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='vehiculos'").fetchone()
    if sql_actual and "UNIQUE(agencia_id, categoria)" in sql_actual["sql"] and "categoria, modelo" not in sql_actual["sql"]:
        print("\n[3] Constraint ya esta en (agencia_id, categoria). No hace falta recrear.")
    else:
        print("\n[3] Recreando tabla vehiculos con UNIQUE(agencia_id, categoria)...")
        cur.executescript("""
            CREATE TABLE vehiculos_new (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agencia_id      INTEGER NOT NULL REFERENCES agencias(id) ON DELETE CASCADE,
                categoria       TEXT NOT NULL,
                modelo          TEXT,
                transmision     TEXT,
                pasajeros       INTEGER,
                external_code   TEXT,
                created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agencia_id, categoria)
            );
            INSERT INTO vehiculos_new
                (id, agencia_id, categoria, modelo, transmision, pasajeros, external_code, created_at)
            SELECT id, agencia_id, categoria, modelo, transmision, pasajeros, external_code, created_at
              FROM vehiculos;
            DROP TABLE vehiculos;
            ALTER TABLE vehiculos_new RENAME TO vehiculos;
        """)

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")

    # 4. Verificacion final.
    total = cur.execute("SELECT COUNT(*) FROM vehiculos").fetchone()[0]
    total_rates = cur.execute("SELECT COUNT(*) FROM rates").fetchone()[0]
    aba_k = cur.execute("""
        SELECT v.id, v.categoria, v.modelo,
               (SELECT COUNT(*) FROM rates r WHERE r.vehiculo_id=v.id) AS obs
          FROM vehiculos v JOIN agencias a ON a.id=v.agencia_id
         WHERE a.slug='aba' AND v.categoria LIKE 'K %'
    """).fetchall()
    print(f"\n[4] Final: {total} vehiculos, {total_rates} rates. K de ABA:")
    for r in aba_k:
        print(f"  id={r['id']} cat={r['categoria']!r} mod={r['modelo']!r} obs={r['obs']}")

    conn.close()
    print("\nMigracion OK.")


if __name__ == "__main__":
    sys.exit(main() or 0)
