"""Config Jinja2 compartida (mismo patrón que CarCloud)."""

from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _fmt_money(value, moneda: str = "ARS") -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    symbol = {"ARS": "$", "USD": "US$", "EUR": "€"}.get(moneda, moneda + " ")
    return f"{symbol} {v:,.0f}".replace(",", ".")


def _fmt_dt(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d/%m/%Y %H:%M")


templates.env.filters["money"] = _fmt_money
templates.env.filters["dt"] = _fmt_dt
