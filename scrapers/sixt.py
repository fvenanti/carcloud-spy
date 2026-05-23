"""Adapter Sixt Bariloche."""

from __future__ import annotations

import logging

from .base import AdapterResult, BaseAdapter, RateQuery, RateQuote

log = logging.getLogger(__name__)


class SixtAdapter(BaseAdapter):
    slug = "sixt"
    nombre = "Sixt Bariloche"

    SEARCH_URL = "https://www.sixt.com.ar/alquiler-coches/argentina/bariloche/"

    def fetch(self, query: RateQuery) -> AdapterResult:
        try:
            return self._fetch_live(query)
        except Exception as e:
            log.warning("Sixt live fetch falló, devolviendo demo: %s", e)
            return self._fetch_demo(query)

    def _fetch_live(self, query: RateQuery) -> AdapterResult:
        raise NotImplementedError("Endpoint XHR de Sixt pendiente de mapear")

    def _fetch_demo(self, query: RateQuery) -> AdapterResult:
        days = query.rental_days
        demo = [
            ("Económico",  "Renault Kwid",     "Manual",     4, 27800.0),
            ("Compacto",   "Renault Logan",    "Manual",     5, 34600.0),
            ("Intermedio", "Peugeot 208",      "Manual",     5, 41200.0),
            ("Premium",    "Audi A3",          "Automático", 5, 89400.0),
            ("SUV",        "Peugeot 2008",     "Automático", 5, 64200.0),
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
