"""Adapter Taraborelli Bariloche.

Taraborelli es la rent-a-car local más grande de la zona; su web suele ser
más simple (HTML server-rendered) — el parseo bs4 es viable acá.
"""

from __future__ import annotations

import logging

from .base import AdapterResult, BaseAdapter, RateQuery, RateQuote

log = logging.getLogger(__name__)


class TaraborelliAdapter(BaseAdapter):
    slug = "taraborelli"
    nombre = "Taraborelli Bariloche"

    SEARCH_URL = "https://www.taraborelli.com.ar/tarifas"

    def fetch(self, query: RateQuery) -> AdapterResult:
        try:
            return self._fetch_live(query)
        except Exception as e:
            log.warning("Taraborelli live fetch falló, devolviendo demo: %s", e)
            return self._fetch_demo(query)

    def _fetch_live(self, query: RateQuery) -> AdapterResult:
        # TODO: parsear el HTML de /tarifas con BeautifulSoup
        # from bs4 import BeautifulSoup
        # r = self._client.get(self.SEARCH_URL)
        # r.raise_for_status()
        # soup = BeautifulSoup(r.text, "lxml")
        # ... extraer tabla de tarifas ...
        raise NotImplementedError("Parser HTML de Taraborelli pendiente")

    def _fetch_demo(self, query: RateQuery) -> AdapterResult:
        days = query.rental_days
        demo = [
            ("Económico",  "Fiat Argo",          "Manual",     5, 22500.0),
            ("Compacto",   "Chevrolet Onix",     "Manual",     5, 29800.0),
            ("Intermedio", "Toyota Yaris",       "Manual",     5, 36900.0),
            ("SUV",        "Ford EcoSport",      "Manual",     5, 54200.0),
            ("Pickup",     "Ford Ranger 4x4",    "Manual",     5, 68900.0),
            ("Minivan",    "Renault Kangoo",     "Manual",     7, 47300.0),
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
