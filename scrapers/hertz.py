"""Adapter Hertz Argentina — Sucursal Bariloche Aeropuerto.

API descubierta:
    POST https://www.hertz.com.ar/api/search
    Content-Type: application/json
    body: {
        locale: "es",
        pickup_place:   45,          # id sucursal Bariloche Aeropuerto
        return_place:   45,
        pickup_date:    "YYYY-MM-DDTHH:MM:SS",
        return_date:    "YYYY-MM-DDTHH:MM:SS",
        promotionalCode: ""          # string vacio, NO undefined
    }

Sucursales Bariloche (mapa slug -> id obtenido del HTML RSC de la home):
    Bariloche Aeropuerto               -> 45 (isAirport=true) <-- esta usamos
    Bariloche Centro - Oficina principal -> 6666
    Bariloche Centro Elflein           -> 46
    Bariloche Circuito Chico           -> 6601

Respuesta: lista de items. Cada item:
    category.name         -> "(C) Económico MT"
    car.brand, car.name   -> "Fiat" "MOBI EASY 1.0 8V"
    car.gear_type         -> "Manual" / "Automático"
    car.passenger_quantity
    prices.price_now      -> precio total con promo aplicada
    prices.full_price     -> precio total sin promo
    promotions[]          -> list de promos vigentes
"""

from __future__ import annotations

import json
import logging

from .base import AdapterResult, BaseAdapter, RateQuery, RateQuote

log = logging.getLogger(__name__)

# Sucursal Bariloche Aeropuerto en Hertz.com.ar
BRANCH_BARILOCHE_AIRPORT = 45


class HertzAdapter(BaseAdapter):
    slug = "hertz"
    nombre = "Hertz Bariloche Aeropuerto"

    SEARCH_URL = "https://www.hertz.com.ar/api/search"

    def fetch(self, query: RateQuery) -> AdapterResult:
        try:
            return self._fetch_live(query)
        except Exception as e:
            log.warning("Hertz live fetch fallo, devolviendo demo: %s", e)
            return self._fetch_demo(query)

    def _fetch_live(self, query: RateQuery) -> AdapterResult:
        payload = {
            "locale": "es",
            "pickup_place": BRANCH_BARILOCHE_AIRPORT,
            "return_place": BRANCH_BARILOCHE_AIRPORT,
            "pickup_date":  query.pickup_iso(default_hour=10),
            "return_date":  query.dropoff_iso(default_hour=10),
            "promotionalCode": "",
        }
        headers = {
            "Content-Type": "application/json",
            "Origin":  "https://www.hertz.com.ar",
            "Referer": "https://www.hertz.com.ar/",
        }
        r = self._client.post(self.SEARCH_URL, headers=headers, content=json.dumps(payload))
        r.raise_for_status()
        data = r.json()

        if isinstance(data, dict):
            if data.get("error"):
                raise ValueError(f"Hertz error: {data['error']}")
            items = data.get("data") or []
        elif isinstance(data, list):
            items = data
        else:
            raise ValueError(f"Respuesta inesperada: {type(data).__name__}")

        if not items:
            raise ValueError("Hertz devolvio 0 vehiculos para Bariloche aeropuerto")

        days = query.rental_days
        quotes: list[RateQuote] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            cat = (it.get("category") or {})
            car = (it.get("car") or {})
            prices = (it.get("prices") or {})

            price_now = prices.get("price_now")
            full_price = prices.get("full_price")
            if price_now is None:
                continue
            try:
                price_now_f = float(price_now)
            except (TypeError, ValueError):
                continue

            brand = (car.get("brand") or "").strip()
            name  = (car.get("name") or "").strip()
            modelo = f"{brand} {name}".strip() if brand and not name.lower().startswith(brand.lower()) else name

            promo_names = [
                p.get("name") for p in (it.get("promotions") or []) if isinstance(p, dict) and p.get("name")
            ]

            quotes.append(
                RateQuote(
                    categoria=(cat.get("name") or f"Cat #{cat.get('id')}").strip(),
                    modelo=modelo or None,
                    transmision=(car.get("gear_type") or "").strip() or None,
                    pasajeros=car.get("passenger_quantity"),
                    moneda="ARS",
                    precio_total=round(price_now_f, 2),
                    precio_por_dia=round(price_now_f / days, 2) if days else None,
                    external_code=str(car.get("model_id") or cat.get("id") or ""),
                    disponible=True,
                    raw_payload=json.dumps({
                        "full_price": full_price,
                        "promotions": promo_names,
                        "franchise": prices.get("franchise"),
                    }, ensure_ascii=False),
                )
            )

        if not quotes:
            raise ValueError("Hertz: ningun item con price_now valido")
        return AdapterResult(quotes=quotes)

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
                categoria=cat, modelo=mod, transmision=trans, pasajeros=pas,
                moneda="ARS", precio_por_dia=ppd,
                precio_total=round(ppd * days, 2), disponible=True, raw_payload="demo",
            )
            for cat, mod, trans, pas, ppd in demo
        ]
        return AdapterResult(quotes=quotes)
