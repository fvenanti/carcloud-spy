"""Cliente local de scraping de promos en Instagram.

Corre en la Windows del usuario. Pre-requisitos:
- Chrome real corriendo con `--remote-debugging-port=<port>` y user-data-dir
  persistente (el wrapper PowerShell se encarga).
- La sesion de IG ya quedo cacheada en ese perfil (el usuario se logueo manualmente
  la primera vez).

Flujo:
1. Connect CDP al Chrome local.
2. Por cada perfil: navega, agarra los ultimos N posts (URL + caption + fecha
   via og:description).
3. POST batch a /api/promos/ingest_ig con header X-Auth-Token.

Config via env vars (todas obligatorias):
- CARCLOUDSPY_BASE_URL      ej. https://spy.aba.benvert.com.ar
- CARCLOUDSPY_PROMO_TOKEN   token compartido con el .env del server
- CARCLOUDSPY_CDP_URL       ej. http://localhost:9223
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("ig_scrape")

# Mapping handle IG -> slug agencia en DB
PROFILES: list[tuple[str, str]] = [
    ("abarentacar",          "aba"),
    ("correntoso_rentacar",  "correntoso"),
    ("hertz_argentina",      "hertz"),
    ("taraborellirentacar",  "taraborelli"),
]
POSTS_PER_PROFILE = 6
MAX_POST_AGE_DAYS = 120   # no mandamos al server posts mas viejos que esto


def env(key: str) -> str:
    v = os.environ.get(key, "").strip()
    if not v:
        log.error("Falta env var %s", key)
        sys.exit(2)
    return v


def scrape_profile(page, handle: str) -> list[dict]:
    """Devuelve lista de {url, caption, posted_at}."""
    url_prof = f"https://www.instagram.com/{handle}/"
    log.info("-> %s", handle)
    for attempt in range(3):
        try:
            page.goto(url_prof, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning("   goto attempt %d err: %s", attempt + 1, e)
            page.wait_for_timeout(2000)
            continue
        page.wait_for_timeout(2500)
        cur = page.url
        if "/accounts/login" in cur or "/accounts/onetap" in cur or "/auth_platform" in cur:
            log.warning("   bounce a login (%s). Retry...", cur)
            page.wait_for_timeout(3000)
            continue
        break
    else:
        log.error("   %s: login redirect persistente, salteo", handle)
        return []

    post_urls: list[str] = []
    try:
        page.wait_for_selector('a[href*="/p/"], a[href*="/reel/"]', timeout=10000)
        anchors = page.locator('a[href*="/p/"], a[href*="/reel/"]').all()
        for a in anchors[: POSTS_PER_PROFILE * 3]:
            href = a.get_attribute("href") or ""
            if not (re.search(r"/p/[\w-]+/?$", href) or re.search(r"/reel/[\w-]+/?$", href)):
                continue
            if href in post_urls:
                continue
            post_urls.append(href)
            if len(post_urls) >= POSTS_PER_PROFILE:
                break
    except Exception as e:
        log.warning("   grid err: %s", e)

    out: list[dict] = []
    for u in post_urls:
        full = f"https://www.instagram.com{u}" if u.startswith("/") else u
        try:
            page.goto(full, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)
            caption = ""
            try:
                caption = page.locator('meta[property="og:description"]').get_attribute("content") or ""
            except Exception:
                pass
            posted_at = ""
            try:
                t = page.locator("time").first
                posted_at = t.get_attribute("datetime") or ""
            except Exception:
                pass
            out.append({"url": full, "caption": caption, "posted_at": posted_at})
        except Exception as e:
            log.warning("   post %s err: %s", u, e)
    return out


def filter_recent(posts: list[dict], max_age_days: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    kept = []
    for p in posts:
        if not p.get("posted_at"):
            kept.append(p)
            continue
        try:
            dt = datetime.fromisoformat(p["posted_at"].replace("Z", "+00:00"))
            if dt >= cutoff:
                kept.append(p)
        except Exception:
            kept.append(p)
    return kept


def post_batch(base_url: str, token: str, agencia_slug: str, posts: list[dict]) -> dict:
    payload = json.dumps({"agencia_slug": agencia_slug, "posts": posts}).encode("utf-8")
    req = urllib.request.Request(
        url=base_url.rstrip("/") + "/api/promos/ingest_ig",
        data=payload,
        method="POST",
        headers={
            "Content-Type":  "application/json",
            "X-Auth-Token":  token,
            "User-Agent":    "carcloudspy-ig-client/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8")
        return json.loads(body)


def main() -> None:
    base_url = env("CARCLOUDSPY_BASE_URL")
    token    = env("CARCLOUDSPY_PROMO_TOKEN")
    cdp_url  = env("CARCLOUDSPY_CDP_URL")

    log.info("== IG promo scrape inicio ==")
    log.info("base=%s cdp=%s", base_url, cdp_url)

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            log.error("CDP connect FAIL en %s: %s", cdp_url, e)
            sys.exit(3)

        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log.info("conectado CDP. url actual: %s", page.url)

        for handle, agencia_slug in PROFILES:
            posts = scrape_profile(page, handle)
            posts = filter_recent(posts, MAX_POST_AGE_DAYS)
            if not posts:
                log.info("   sin posts recientes")
                continue
            try:
                resp = post_batch(base_url, token, agencia_slug, posts)
                log.info("   POST %s -> %s", agencia_slug, resp)
            except Exception as e:
                log.error("   POST %s err: %s", agencia_slug, e)

    log.info("== fin ==")


if __name__ == "__main__":
    main()
