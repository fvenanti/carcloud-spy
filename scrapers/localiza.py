"""Adapter Localiza Bariloche.

Localiza opera en BRC (aeropuerto) y centro de Bariloche. Su web es SPA con
APIs internas. Mismo patrón que Hertz: live (TODO) + demo fallback.
"""

from __future__ import annotations

import logging

from .base import AdapterResult, BaseAdapter, RateQuery, RateQuote

log = logging.getLogger(__name__)


class LocalizaAdapter(BaseAdapter):
    slug = "localiza"
    nombre = "Localiza Bariloche"

    SEARCH_URL = "https://www.localiza.com/argentina/es-ar/"

    def fetch(self, query: RateQuery) -> AdapterResult:
        try:
            return self._fetch_live(query)
        except Exception as e:
            log.warning("Localiza live fetch falló, devolviendo demo: %s", e)
            return self._fetch_demo(query)

    def _fetch_live(self, query: RateQuery) -> AdapterResult:
        raise NotImplementedError("Endpoint XHR de Localiza pendiente de mapear")

    def _fetch_demo(self, query: RateQuery) -> AdapterResult:
        days = query.rental_days
        demo = [
            ("Económico",  "Fiat Mobi",          "Manual",     4, 24900.0),
            ("Compacto",   "Fiat Cronos",        "Manual",     5, 32100.0),
            ("Intermedio", "Volkswagen Polo",    "Manual",     5, 39800.0),
            ("SUV",        "Volkswagen Taos",    "Automático", 5, 62300.0),
            ("Pickup",     "Volkswagen Amarok",  "Manual",     5, 75800.0),
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
