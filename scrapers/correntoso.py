"""Adapter Correntoso Rent a Car.

Sistema backend: VZone (PHP propietario). Flujo en 2 pasos:

1. POST a `http://www.correntosorentacar.com/` con campos del form de cotización
   (`lugar`, `lugar_devolucion`, `fecha_entrega` formato `DD/MM/YYYY HH:MM`,
   `fecha_devolucion`, `pasajeros`, `categoria`, `nombre`, `email`, `ajax=1`).
   La respuesta es texto plano `location.href="paso1.php";` y devuelve cookie
   `PHPSESSID`.

2. GET `http://www.correntosorentacar.com/paso1.php` con la misma cookie.
   El HTML viene server-rendered con TODAS las categorías + precios por
   método de pago (efectivo / débito / crédito 1 pago / cuotas).

Lugares (campo `lugar`):
    0 = Oficina central, 1 = Aeropuerto Bariloche, 2 = Terminal Buses, 3 = Hotel.
    Usamos 1 (aeropuerto) para alinear con las demás agencias.

Email del cliente: env var `CORRENTOSO_LEAD_EMAIL` (cae a juanita@gmail.com).
NO usar email propio para evitar exposición y ensuciar leads de Correntoso.
"""

from __future__ import annotations

import json
import logging
import os
import re

from bs4 import BeautifulSoup

from .base import AdapterResult, BaseAdapter, RateQuery, RateQuote

log = logging.getLogger(__name__)

BASE_URL = "http://www.correntosorentacar.com"
LUGAR_AEROPUERTO = 1  # id del dropdown del form

_CAT_RE = re.compile(r"^Categor[íi]a\s+([A-Z]+)\s*-\s*(.+)$")
_PRICE_RE = re.compile(r"\$\s*([\d.,]+)")


def _parse_money(s: str) -> float | None:
    m = _PRICE_RE.search(s or "")
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


class CorrentosoAdapter(BaseAdapter):
    slug = "correntoso"
    nombre = "Correntoso Rent a Car"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lead_email = os.getenv("CORRENTOSO_LEAD_EMAIL", "juanita@gmail.com").strip()
        self.lead_name  = os.getenv("CORRENTOSO_LEAD_NAME", "Juanita").strip()

    def fetch(self, query: RateQuery) -> AdapterResult:
        try:
            return self._fetch_live(query)
        except Exception as e:
            log.warning("Correntoso live fetch fallo, devolviendo demo: %s", e)
            return self._fetch_demo(query)

    def _fetch_live(self, query: RateQuery) -> AdapterResult:
        # Hora dinámica (si pickup es hoy, evita "fecha en el pasado")
        pickup_iso = query.pickup_iso(default_hour=10)
        from datetime import datetime as _dt
        pickup_dt  = _dt.fromisoformat(pickup_iso)
        dropoff_dt = _dt.combine(query.dropoff_date, _dt.min.time().replace(hour=10))

        # 1) POST inicial: crea sesión + valida fechas
        post_data = {
            "ajax": "1",
            "lugar": LUGAR_AEROPUERTO,
            "lugar_devolucion": LUGAR_AEROPUERTO,
            "fecha_entrega":   pickup_dt.strftime("%d/%m/%Y %H:%M"),
            "fecha_devolucion": dropoff_dt.strftime("%d/%m/%Y %H:%M"),
            "pasajeros": 2,
            "categoria": "B",
            "nombre": self.lead_name,
            "email":  self.lead_email,
        }
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        r1 = self._client.post(f"{BASE_URL}/", data=post_data, headers=headers)
        r1.raise_for_status()
        body1 = (r1.text or "").strip()
        if "paso1.php" not in body1:
            raise ValueError(f"Correntoso no redirigio a paso1 (resp: {body1[:200]!r})")

        # 2) GET con cookie (httpx Client la mantiene automaticamente)
        r2 = self._client.get(f"{BASE_URL}/paso1.php")
        r2.raise_for_status()
        return self._parse_paso1(r2.text, query)

    def _parse_paso1(self, html: str, query: RateQuery) -> AdapterResult:
        soup = BeautifulSoup(html, "lxml")
        days = query.rental_days
        quotes: list[RateQuote] = []
        seen: set[str] = set()

        # Cada categoría se anuncia con un div estilo bgcolor #FF9966
        for header in soup.find_all("div"):
            style = (header.get("style") or "").lower()
            if "ff9966" not in style.replace("#", ""):
                continue
            text = header.get_text(strip=True)
            m = _CAT_RE.match(text)
            if not m:
                continue
            cat_code = m.group(1).strip()
            modelo   = m.group(2).strip()
            if cat_code in seen:
                continue
            seen.add(cat_code)

            # El bloque de precios es el siguiente <table> dentro del padre
            container = header.parent
            if container is None:
                continue
            table = container.find("table")
            if table is None:
                continue

            prices: list[float] = []
            for td in table.find_all("td"):
                txt = td.get_text(strip=True)
                p = _parse_money(txt)
                if p is not None and p > 1000:  # filtrar km values y cosas chicas
                    prices.append(p)
            if not prices:
                continue

            # El menor es típicamente "efectivo" (mejor precio publicado);
            # el mayor suele ser "crédito en cuotas con recargo"
            precio_min = min(prices)
            precio_max = max(prices)

            # Inferir transmisión y pasajeros del modelo string
            mod_lower = modelo.lower()
            transmision = None
            if any(s in mod_lower for s in ("automatic", "cvt", "auto ", "automática", "auto)")):
                transmision = "Automática"
            elif "manual" in mod_lower:
                transmision = "Manual"
            pasajeros = None
            mp = re.search(r"(\d+)\s*(?:pasajero|pax)", mod_lower)
            if mp:
                pasajeros = int(mp.group(1))

            quotes.append(
                RateQuote(
                    categoria=cat_code,
                    modelo=modelo,
                    transmision=transmision,
                    pasajeros=pasajeros,
                    moneda="ARS",
                    precio_total=round(precio_min, 2),
                    precio_por_dia=round(precio_min / days, 2) if days else None,
                    external_code=cat_code,
                    disponible=True,
                    raw_payload=json.dumps({
                        "precio_efectivo": precio_min,
                        "precio_max": precio_max,
                        "prices_all": prices,
                    }, ensure_ascii=False),
                )
            )

        if not quotes:
            raise ValueError("Correntoso: no se pudieron parsear categorias en paso1.php")
        return AdapterResult(quotes=quotes)

    def _fetch_demo(self, query: RateQuery) -> AdapterResult:
        days = query.rental_days
        demo = [
            ("B", "Vehículo 5 Puertas",                          "Manual",     5, 424000.0),
            ("C", "Vehículo 4 Puertas con baúl",                 "Manual",     5, 471000.0),
            ("CVT", "Renault Sandero Caja Automática",           "Automática", 5, 551000.0),
            ("D", "VW T-Cross Caja Automática",                  "Automática", 5, 600000.0),
            ("E", "Renault Kangoo ZEN para 5/7 Pasajeros",       "Manual",     7, 650000.0),
            ("F", "Renault Alaskan 4X4",                         "Manual",     5, 850000.0),
        ]
        quotes = [
            RateQuote(
                categoria=f"{cat} - {mod}", modelo=mod, transmision=trans, pasajeros=pas,
                moneda="ARS", precio_total=total, precio_por_dia=round(total/days, 2),
                external_code=cat, disponible=True, raw_payload="demo",
            )
            for cat, mod, trans, pas, total in demo
        ]
        return AdapterResult(quotes=quotes)
