"""Detector y scraper de promociones.

Dos fuentes:
- **Web**: el server hace HTTP GET a las URLs configuradas por agencia y
  aplica heuristicas sobre el HTML rendered (estatico). Corre 1 vez por dia
  desde el scheduler.
- **Instagram**: el cliente local (Windows con Chrome real) recolecta posts
  via CDP y los POSTea a `/api/promos/ingest_ig`. El server aplica las mismas
  heuristicas sobre el caption.

El detector apunta a precision sobre recall: preferimos perder una promo a
inundar la UI con falsos positivos.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# URLs a inspeccionar por agencia (slug debe coincidir con `agencias.slug`).
WEB_PROMO_URLS: dict[str, list[str]] = {
    "aba":         ["https://abarentacar.com.ar/"],
    "correntoso":  ["http://www.correntosorentacar.com/"],
    "hertz":       ["https://www.hertz.com.ar/", "https://www.hertz.com.ar/en/hotsale"],
    "taraborelli": ["https://www.taraborellirentacar.com/es"],
}

# Cualquiera de estas evidencias dispara el match — pero la senial debil
# (solo "promo" o "descuento") tambien necesita acompanarse de algo "fuerte".
_KEYWORD_RE = re.compile(
    r"((?<!\d)\d{1,2}\s*%\s*(?:off|de\s*descuento|descuento)?)"
    r"|(cuotas?\s*sin\s*inter[ée]s)"
    r"|(promo(?:ci[oó]n)?)"
    r"|(descuento)"
    r"|(ofert[a])"
    r"|(hot\s*sale)"
    r"|(travel\s*sale)"
    r"|(black\s*friday)"
    r"|(cyber\s*monday)"
    r"|(2x1|3x2)"
    r"|(pago\s*anticipad)"
    r"|(sin\s*inter[ée]s)",
    re.IGNORECASE,
)

# "Senial fuerte": un numero % (no parte de 100%), cuotas s/i, sale conocido,
# multiplicador, o "hasta el X de <mes>"
_STRONG_RE = re.compile(
    r"((?<!\d)\d{1,2}\s*%"
    r"|cuotas?\s*sin\s*inter[ée]s"
    r"|hot\s*sale|travel\s*sale|black\s*friday"
    r"|2x1|3x2"
    r"|hasta\s+(?:el\s+)?\d{1,2}\s*(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre))",
    re.IGNORECASE,
)

_PCT_RE = re.compile(r"(?<!\d)(\d{1,2})\s*%", re.IGNORECASE)

_MONTH_MAP = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_DATE_RE = re.compile(
    r"hasta\s+(?:el\s+)?(\d{1,2})\s*(?:de\s+)?(" + "|".join(_MONTH_MAP) + r")\s*(?:de\s*)?(\d{4})?",
    re.IGNORECASE,
)


@dataclass
class Promo:
    agencia_slug: str
    source: str  # 'web' | 'instagram'
    source_url: str
    titulo: str
    raw_text: str
    descuento_pct: float | None = None
    descuento_texto: str = ""
    vigencia_desde: str | None = None
    vigencia_hasta: str | None = None
    posted_at: str | None = None

    def hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.source.encode())
        h.update(self.source_url.encode())
        h.update(self.raw_text[:500].encode("utf-8", errors="ignore"))
        return h.hexdigest()

    def to_db_dict(self) -> dict:
        d = {
            "agencia_slug":    self.agencia_slug,
            "source":          self.source,
            "source_url":      self.source_url,
            "titulo":          self.titulo,
            "descuento_pct":   self.descuento_pct,
            "descuento_texto": self.descuento_texto,
            "vigencia_desde":  self.vigencia_desde,
            "vigencia_hasta":  self.vigencia_hasta,
            "raw_text":        self.raw_text,
            "posted_at":       self.posted_at,
            "hash":            self.hash(),
        }
        return d


def _line_containing(text: str, pos: int) -> str:
    """Devuelve la linea de `text` que contiene el indice `pos`."""
    start = text.rfind("\n", 0, pos) + 1
    end_nl = text.find("\n", pos)
    end = end_nl if end_nl != -1 else len(text)
    return text[start:end].strip()


def detect_promo(text: str) -> Promo | None:
    """Aplica heuristicas y devuelve un Promo sin source/url/slug (los setea el caller).

    Retorna None si el texto no aparenta ser una promo.
    """
    if not text:
        return None
    cleaned = text.strip()
    if len(cleaned) < 30:
        return None
    if not _KEYWORD_RE.search(cleaned):
        return None
    strong = _STRONG_RE.search(cleaned)
    if not strong:
        return None

    pct: float | None = None
    # buscamos % cerca del strong match (no en otra parte del bloque)
    pct_search = _PCT_RE.search(cleaned)
    if pct_search:
        try:
            v = int(pct_search.group(1))
            if 5 <= v <= 90:
                pct = float(v)
        except ValueError:
            pass

    hasta: str | None = None
    md = _DATE_RE.search(cleaned)
    if md:
        try:
            d = int(md.group(1))
            mes = md.group(2).lower()
            anio = int(md.group(3)) if md.group(3) else date.today().year
            mm = _MONTH_MAP[mes]
            hasta = date(anio, mm, d).isoformat()
        except Exception:
            pass

    # Titulo: linea que contiene la senial fuerte (mas relevante que la
    # primera linea del bloque, que suele ser navbar/branding).
    titulo = _line_containing(cleaned, strong.start())
    if len(titulo) < 10:
        # fallback: primera linea con >= 10 chars
        for line in cleaned.splitlines():
            l = line.strip()
            if len(l) >= 10:
                titulo = l
                break
    titulo = titulo[:140] if titulo else cleaned[:140]

    return Promo(
        agencia_slug="",
        source="",
        source_url="",
        titulo=titulo,
        raw_text=cleaned[:2000],
        descuento_pct=pct,
        descuento_texto=pct_search.group(0).strip() if pct_search else "",
        vigencia_hasta=hasta,
    )


def scrape_web_promos() -> list[Promo]:
    """Recorre `WEB_PROMO_URLS`, devuelve promos detectadas (dedupe por titulo)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    }
    out: list[Promo] = []
    with httpx.Client(headers=headers, timeout=httpx.Timeout(25.0), follow_redirects=True) as client:
        for slug, urls in WEB_PROMO_URLS.items():
            for url in urls:
                try:
                    r = client.get(url)
                except Exception as e:
                    log.warning("[%s] %s GET err: %s", slug, url, e)
                    continue
                if r.status_code >= 400:
                    log.info("[%s] %s -> HTTP %d", slug, url, r.status_code)
                    continue

                soup = BeautifulSoup(r.text, "lxml")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()

                candidates: list[str] = []
                for block in soup.find_all(["section", "article", "div", "p", "li"]):
                    txt = block.get_text(separator="\n", strip=True)
                    if 40 <= len(txt) <= 2000:
                        candidates.append(txt)

                # Dedupe por (titulo, pct, vigencia). Coincide bien con como una promo
                # aparece duplicada en divs anidados o en la misma pagina con CTAs distintos.
                def _sig(p: Promo) -> str:
                    base = re.sub(r"\s+", " ", p.titulo).strip().lower()[:120]
                    return f"{base}|{p.descuento_pct}|{p.vigencia_hasta}"

                seen_sig: set[str] = set()
                detected_here = 0
                for txt in candidates:
                    promo = detect_promo(txt)
                    if not promo:
                        continue
                    sig = _sig(promo)
                    if sig in seen_sig:
                        continue
                    seen_sig.add(sig)
                    promo.agencia_slug = slug
                    promo.source = "web"
                    promo.source_url = url
                    out.append(promo)
                    detected_here += 1

                log.info("[%s] %s -> %d promos", slug, url, detected_here)
    return out


def promo_from_ig_post(
    agencia_slug: str,
    post_url: str,
    caption: str,
    posted_at: str | None,
) -> Promo | None:
    """Aplica detect_promo y setea metadata IG."""
    p = detect_promo(caption or "")
    if not p:
        return None
    p.agencia_slug = agencia_slug
    p.source = "instagram"
    p.source_url = post_url
    p.posted_at = posted_at
    return p
