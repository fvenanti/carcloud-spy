"""Adapter ABA — API dedicada con X-API-Key.

Endpoint: GET https://aba.benvert.com.ar/api/disponibilidad
Auth:     header X-API-Key (lee de env var ABA_API_KEY)
Params:   inicio, fin (YYYY-MM-DD), sucursal, hora_inicio, hora_fin

Respuesta:
    {"vehiculos": [
        {
            "Categoría":       "M",
            "Descripcion":     "4X4 / AUT / SUV / GDE",
            "MODELO":          "Honda CRV o Similar",
            "Tarifa_Final":    "$149.000",
            "Tarifa_Efectivo": "$134.100",
            "Detalle_Breve":   "...",
            "IdAutos":         241,
            "Sucursal":        "Bariloche",
            "Pasajeros":       5,
            "Valijas":         4,
            "Transmision":     "automatica" | "manual" | null,
            "Sena_Pct":        50,
            ...
        }
    ]}

La API devuelve UNA categoría representativa por tipo disponible, asi que no
hace falta deduplicar como en Hertz.
"""

from __future__ import annotations

import json
import logging
import os
import re

from .base import AdapterResult, BaseAdapter, RateQuery, RateQuote

log = logging.getLogger(__name__)

_MONEY_RE = re.compile(r"[^\d,.-]")


def _parse_money(s: str | None) -> float | None:
    """`$ 149.000` -> 149000.0  (formato argentino: punto = miles)."""
    if not s:
        return None
    cleaned = _MONEY_RE.sub("", s).replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


class AbaAdapter(BaseAdapter):
    slug = "aba"
    nombre = "ABA Rent a Car Bariloche"

    BASE_URL = "https://aba.benvert.com.ar/api/disponibilidad"
    SUCURSAL = "Bariloche"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = os.getenv("ABA_API_KEY", "").strip()

    def fetch(self, query: RateQuery) -> AdapterResult:
        if not self.api_key:
            log.warning("ABA_API_KEY no esta configurada, devolviendo demo")
            return self._fetch_demo(query)
        try:
            return self._fetch_live(query)
        except Exception as e:
            log.warning("ABA live fetch fallo, devolviendo demo: %s", e)
            return self._fetch_demo(query)

    def _fetch_live(self, query: RateQuery) -> AdapterResult:
        params = {
            "inicio":   query.pickup_date.isoformat(),
            "fin":      query.dropoff_date.isoformat(),
            "sucursal": self.SUCURSAL,
            "hora_inicio": 10,
            "hora_fin":    10,
        }
        headers = {"X-API-Key": self.api_key}
        r = self._client.get(self.BASE_URL, params=params, headers=headers)
        if r.status_code == 401:
            raise PermissionError("ABA respondio 401 — verificar X-API-Key")
        r.raise_for_status()
        data = r.json()
        items = data.get("vehiculos") or []
        if not items:
            raise ValueError("ABA devolvio 0 vehiculos disponibles")

        days = query.rental_days
        quotes: list[RateQuote] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            cat = (it.get("Categoría") or it.get("Categoria") or "").strip()
            descripcion = (it.get("Descripcion") or "").strip()
            modelo = (it.get("MODELO") or "").strip()
            tarifa_final = _parse_money(it.get("Tarifa_Final"))
            tarifa_efectivo = _parse_money(it.get("Tarifa_Efectivo"))
            if tarifa_final is None:
                continue

            transmision = (it.get("Transmision") or "").strip().lower() or None
            # Normalizar a forma consistente con otros adapters
            if transmision == "manual":
                transmision = "Manual"
            elif transmision == "automatica":
                transmision = "Automática"

            categoria_label = f"{cat} - {descripcion}" if cat and descripcion else (cat or descripcion or "?")

            quotes.append(
                RateQuote(
                    categoria=categoria_label,
                    modelo=modelo or None,
                    transmision=transmision,
                    pasajeros=it.get("Pasajeros"),
                    moneda="ARS",
                    precio_total=round(tarifa_final, 2),
                    precio_por_dia=round(tarifa_final / days, 2) if days else None,
                    external_code=str(it.get("IdAutos") or cat),
                    disponible=True,
                    raw_payload=json.dumps({
                        "tarifa_efectivo": tarifa_efectivo,
                        "sena_pct": it.get("Sena_Pct"),
                        "valijas": it.get("Valijas"),
                        "matricula": it.get("MATRICULA"),
                        "detalle_breve": it.get("Detalle_Breve"),
                    }, ensure_ascii=False),
                )
            )

        if not quotes:
            raise ValueError("ABA: ningun vehiculo con Tarifa_Final valida")
        return AdapterResult(quotes=quotes)

    def _fetch_demo(self, query: RateQuery) -> AdapterResult:
        days = query.rental_days
        demo = [
            ("C - 5P AA DA",            "Fiat Argo o Similar",       "Manual",      5, 374220.0),
            ("D - 4P MD BAUL",          "Onix Plus Joy o Similar",   "Manual",      5, 405540.0),
            ("F - PICK UP / 4P",        "Strada o Similar",          "Manual",      5, 540000.0),
            ("M - 4X4 / AUT / SUV GDE", "Honda CRV o Similar",       "Automática",  5, 660000.0),
        ]
        quotes = [
            RateQuote(
                categoria=cat, modelo=mod, transmision=trans, pasajeros=pas,
                moneda="ARS", precio_total=total, precio_por_dia=round(total/days, 2),
                disponible=True, raw_payload="demo",
            )
            for cat, mod, trans, pas, total in demo
        ]
        return AdapterResult(quotes=quotes)
