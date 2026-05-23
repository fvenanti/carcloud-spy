"""Interfaz común para los adaptadores de scraping.

Cada adapter implementa `fetch(query)` y devuelve un `AdapterResult` con la
lista de `RateQuote`. El scheduler se encarga de persistir.

Filosofía:
- Los sitios son SPAs internacionales que cargan tarifas vía XHR.
- Cada adapter debe identificar el endpoint XHR real (DevTools → Network)
  y replicar el request con `httpx`. Como fallback, parsear HTML con bs4.
- Si un sitio no responde o cambia el contrato, el adapter debe levantar
  excepción — el scheduler la registra en `scrape_runs` y sigue con el resto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Protocol

import httpx


@dataclass(frozen=True)
class RateQuery:
    pickup_location: str       # ej. "BRC" (código IATA aeropuerto Bariloche)
    pickup_date: date
    dropoff_date: date

    @property
    def rental_days(self) -> int:
        return max(1, (self.dropoff_date - self.pickup_date).days)


@dataclass
class RateQuote:
    categoria: str
    modelo: str | None
    moneda: str
    precio_total: float
    precio_por_dia: float | None = None
    transmision: str | None = None
    pasajeros: int | None = None
    external_code: str | None = None
    disponible: bool = True
    raw_payload: str | None = None


@dataclass
class AdapterResult:
    quotes: list[RateQuote] = field(default_factory=list)
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RateAdapter(Protocol):
    """Cada agencia implementa esta interfaz."""

    slug: str
    nombre: str

    def fetch(self, query: RateQuery) -> AdapterResult: ...


class BaseAdapter:
    """Helper común: cliente httpx con UA + timeout."""

    slug: str = ""
    nombre: str = ""

    def __init__(self, user_agent: str | None = None, timeout: float = 20.0):
        self._client = httpx.Client(
            headers={
                "User-Agent": user_agent or (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
            },
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
