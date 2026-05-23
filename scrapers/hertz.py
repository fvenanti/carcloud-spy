"""Adapter Hertz Bariloche.

Sucursal: Aeropuerto Bariloche (IATA: BRC).
Hertz expone su buscador en https://www.hertz.com.ar/ — el detalle de tarifas
se obtiene vía XHR a `/api/availability` (verificar contrato real en DevTools).

NOTA: Este archivo trae el esqueleto + datos demo. El parseo XHR real depende
del payload actual del sitio. Reemplazar `_fetch_demo` por la llamada real
cuando se inspeccione el endpoint.
"""

from __future__ import annotations

import logging

from .base import AdapterResult, BaseAdapter, RateQuery, RateQuote

log = logging.getLogger(__name__)


class HertzAdapter(BaseAdapter):
    slug = "hertz"
    nombre = "Hertz Bariloche"

    SEARCH_URL = "https://www.hertz.com.ar/rentacar/reservation/"

    def fetch(self, query: RateQuery) -> AdapterResult:
        try:
            return self._fetch_live(query)
        except Exception as e:
            log.warning("Hertz live fetch falló, devolviendo demo: %s", e)
            return self._fetch_demo(query)

    def _fetch_live(self, query: RateQuery) -> AdapterResult:
        # TODO: completar con el endpoint XHR real.
        # Pasos para reverse-engineer:
        #   1. Abrir https://www.hertz.com.ar/ en Chrome
        #   2. DevTools > Network > XHR
        #   3. Hacer una búsqueda BRC pickup/dropoff
        #   4. Copiar URL + payload del XHR de tarifas
        #   5. Replicar acá con self._client.post(...)
        raise NotImplementedError("Endpoint XHR de Hertz pendiente de mapear")

    def _fetch_demo(self, query: RateQuery) -> AdapterResult:
        days = query.rental_days
        demo = [
            ("Económico",  "Chevrolet Onix",     "Manual",     5, 28500.0),
            ("Compacto",   "Chevrolet Cruze",    "Manual",     5, 35200.0),
            ("Intermedio", "Toyota Corolla",     "Automático", 5, 42800.0),
            ("SUV",        "Jeep Renegade",      "Automático", 5, 58900.0),
            ("Pickup",     "Toyota Hilux 4x4",   "Manual",     5, 71500.0),
        ]
        quotes = [
            RateQuote(
                categoria=cat,
                modelo=mod,
                transmision=trans,
                pasajeros=pas,
                moneda="ARS",
                precio_por_dia=ppd,
                precio_total=round(ppd * days, 2),
                disponible=True,
                raw_payload="demo",
            )
            for cat, mod, trans, pas, ppd in demo
        ]
        return AdapterResult(quotes=quotes)
