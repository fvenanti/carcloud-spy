from .base import RateAdapter, RateQuote, AdapterResult
from .aba import AbaAdapter
from .correntoso import CorrentosoAdapter
from .hertz import HertzAdapter
from .taraborelli import TaraborelliAdapter

ADAPTERS: dict[str, type[RateAdapter]] = {
    "aba": AbaAdapter,
    "correntoso": CorrentosoAdapter,
    "hertz": HertzAdapter,
    "taraborelli": TaraborelliAdapter,
}

__all__ = [
    "RateAdapter",
    "RateQuote",
    "AdapterResult",
    "ADAPTERS",
    "AbaAdapter",
    "CorrentosoAdapter",
    "HertzAdapter",
    "TaraborelliAdapter",
]
