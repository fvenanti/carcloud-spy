from .base import RateAdapter, RateQuote, AdapterResult
from .aba import AbaAdapter
from .hertz import HertzAdapter
from .localiza import LocalizaAdapter
from .taraborelli import TaraborelliAdapter

ADAPTERS: dict[str, type[RateAdapter]] = {
    "aba": AbaAdapter,
    "hertz": HertzAdapter,
    "localiza": LocalizaAdapter,
    "taraborelli": TaraborelliAdapter,
}

__all__ = [
    "RateAdapter",
    "RateQuote",
    "AdapterResult",
    "ADAPTERS",
    "AbaAdapter",
    "HertzAdapter",
    "LocalizaAdapter",
    "TaraborelliAdapter",
]
