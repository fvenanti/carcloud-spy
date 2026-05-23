from .base import RateAdapter, RateQuote, AdapterResult
from .aba import AbaAdapter
from .hertz import HertzAdapter
from .localiza import LocalizaAdapter
from .sixt import SixtAdapter
from .taraborelli import TaraborelliAdapter

ADAPTERS: dict[str, type[RateAdapter]] = {
    "aba": AbaAdapter,
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
    "AbaAdapter",
    "HertzAdapter",
    "LocalizaAdapter",
    "SixtAdapter",
    "TaraborelliAdapter",
]
