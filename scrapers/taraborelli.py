"""Adapter Taraborelli Bariloche.

Backend: api.builderduck.com (plataforma SaaS Rently — mismo provider que
Hertz Argentina, pero tenant distinto).

Endpoint: GET https://api.builderduck.com/api/booking/search
Auth:     header `Referer: https://www.taraborellirentacar.com/es`
          (la API usa el referer para identificar el tenant — sin él da 404)
Params:
    fromPlace, toPlace        # int — id de sucursal (Bariloche Aeropuerto = 2)
    from, to                  # "YYYY-MM-DD HH:MM"  (OJO: precisa el :MM, no solo HH)
    kilometers, promotionCode # vacios
    language                  # "es"
    ilimitedKm                # false
    showFinalPrice            # true
    onlyFullAvailability      # false

Sucursales Bariloche (de /api/data/places):
    Bariloche Aeropuerto       -> id=2
    Bariloche Centro           -> id=503
    Bariloche Km 7.5 (Charming)-> id=978
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta

from .base import AdapterResult, BaseAdapter, RateQuery, RateQuote

log = logging.getLogger(__name__)

BRANCH_BARILOCHE_AIRPORT = 2
REFERER = "https://www.taraborellirentacar.com/es"


def _format_for_taraborelli(d, default_hour: int = 10) -> str:
    """Acepta date o datetime. Devuelve 'YYYY-MM-DD HH:MM'."""
    if isinstance(d, datetime):
        dt = d
    else:
        dt = datetime.combine(d, time(default_hour, 0))
    return dt.strftime("%Y-%m-%d %H:%M")


class TaraborelliAdapter(BaseAdapter):
    slug = "taraborelli"
    nombre = "Taraborelli Bariloche Aeropuerto"

    SEARCH_URL = "https://api.builderduck.com/api/booking/search"

    def fetch(self, query: RateQuery) -> AdapterResult:
        try:
            return self._fetch_live(query)
        except Exception as e:
            log.warning("Taraborelli live fetch fallo, devolviendo demo: %s", e)
            return self._fetch_demo(query)

    def _fetch_live(self, query: RateQuery) -> AdapterResult:
        # Reusar la logica de "si pickup=hoy, usar now+2h" via pickup_iso(),
        # parsearlo de vuelta a datetime y reformatear al shape Taraborelli.
        pickup_iso = query.pickup_iso(default_hour=10)
        pickup_dt = datetime.fromisoformat(pickup_iso)
        dropoff_dt = datetime.combine(query.dropoff_date, time(10, 0))

        params = {
            "fromPlace": BRANCH_BARILOCHE_AIRPORT,
            "toPlace":   BRANCH_BARILOCHE_AIRPORT,
            "from":      _format_for_taraborelli(pickup_dt),
            "to":        _format_for_taraborelli(dropoff_dt),
            "kilometers": "",
            "promotionCode": "",
            "language":  "es",
            "ilimitedKm": "false",
            "showFinalPrice": "true",
            "onlyFullAvailability": "false",
        }
        r = self._client.get(self.SEARCH_URL, params=params, headers={"Referer": REFERER})
        r.raise_for_status()
        data = r.json()

        if isinstance(data, dict) and data.get("errorMessage"):
            raise ValueError(f"Taraborelli: {data.get('errorMessage')} (code {data.get('errorCode')})")

        if not isinstance(data, list) or not data:
            raise ValueError("Taraborelli devolvio respuesta vacia")

        days = query.rental_days
        quotes: list[RateQuote] = []
        for it in data:
            if not isinstance(it, dict):
                continue
            cat = (it.get("category") or {})
            car = (it.get("car") or {})
            model = (car.get("model") or {})

            price_total = it.get("customerPrice") or it.get("price")
            if price_total is None:
                continue
            try:
                price_total_f = float(price_total)
            except (TypeError, ValueError):
                continue

            daily = it.get("averageDayPrice")
            if daily is None and days:
                daily = price_total_f / days

            brand = (model.get("brand") or {}).get("name", "").strip()
            desc  = (model.get("description") or "").strip()
            modelo = f"{brand} {desc}".strip() if brand and not desc.lower().startswith(brand.lower()) else (desc or model.get("name"))

            gearbox_raw = (model.get("gearbox") or "").strip()
            # "A" es ambiguo (parece "Automática" truncado en Compass) -> normalizo
            transmision = gearbox_raw
            if gearbox_raw == "A":
                transmision = "Automática"

            additionals_at_airport = next(
                (a.get("additional", {}).get("name") for a in (it.get("additionals") or [])
                 if "Aeropuerto" in (a.get("additional", {}).get("name") or "")),
                None,
            )

            quotes.append(
                RateQuote(
                    categoria=(cat.get("name") or "?").strip(),
                    modelo=modelo or None,
                    transmision=transmision or None,
                    pasajeros=model.get("passengers"),
                    moneda=it.get("currency") or "ARS",
                    precio_total=round(price_total_f, 2),
                    precio_por_dia=round(float(daily), 2) if daily else None,
                    external_code=str(model.get("id") or cat.get("id") or ""),
                    disponible=True,
                    raw_payload=json.dumps({
                        "franchise": it.get("franchise"),
                        "totalDays": it.get("totalDays"),
                        "ilimitedKm": it.get("ilimitedKm"),
                        "extra_aeropuerto": additionals_at_airport,
                    }, ensure_ascii=False),
                )
            )

        if not quotes:
            raise ValueError("Taraborelli: ningun item con precio valido")
        return AdapterResult(quotes=quotes)

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
                categoria=cat, modelo=mod, transmision=trans, pasajeros=pas,
                moneda="ARS", precio_por_dia=ppd,
                precio_total=round(ppd * days, 2), disponible=True, raw_payload="demo",
            )
            for cat, mod, trans, pas, ppd in demo
        ]
        return AdapterResult(quotes=quotes)
