from .base import RateAdapter, RateQuote, AdapterResult
from .hertz import HertzAdapter
from .localiza import LocalizaAdapter
from .sixt import SixtAdapter
from .taraborelli import TaraborelliAdapter

ADAPTERS: dict[str, type[RateAdapter]] = {
    "hertz": HertzAdapter,
    "localiza": LocalizaAdapter,
    "sixt": SixtAdapter,
    "taraborelli": TaraborelliAdapter,
}

__all__ = [
    "RateAdapter",
    "RateQuote",
    "AdapterResult",
    "ADAPTERS",
    "HertzAdapter",
    "LocalizaAdapter",
    "SixtAdapter",
    "TaraborelliAdapter",
]
