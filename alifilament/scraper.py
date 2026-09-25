"""
Pobieranie stron wyszukiwania AliExpress przez Playwright.

AliExpress nie renderuje wyników po stronie serwera — cała lista produktów
jest wstrzykiwana JavaScriptem do zmiennej w window, więc potrzebny jest
prawdziwy silnik przeglądarki, a nie zwykłe HTTP.

Zasada działania przy blokadzie: przerywamy przebieg i mówimy o tym wprost.
Ponawianie w pętli tylko pogłębia blokadę i zamienia cichą awarię w trwałą.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re

from playwright.async_api import async_playwright

from .config import Config
from .models import Offer
from .parser import parsuj

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")

BLOCK_MARKERS = ("x5sec", "_____tmd_____", "punish", "slide to verify",
                 "captcha", "nc_1_n1z")

# Ten sam zrzut co w rekonesansie — własna serializacja, bo runParams
# potrafi zawierać cykle i węzły DOM, których JSON.stringify nie przełknie.
JS_DUMP_WINDOW = """
() => {
  const seen = new WeakSet();
  const strip = (v, depth) => {
    if (depth > 14) return 'OBCIETE';
    if (v === null || v === undefined) return v;
    const t = typeof v;
    if (t === 'function') return 'FUNKCJA';
    if (t !== 'object') return v;
    if (typeof Node !== 'undefined' && v instanceof Node) return 'DOM';
    if (seen.has(v)) return 'CYKL';
    seen.add(v);
    if (Array.isArray(v)) return v.slice(0, 120).map(x => strip(x, depth + 1));
    const o = {};
    for (const k of Object.keys(v)) {
      try { o[k] = strip(v[k], depth + 1); } catch (e) { o[k] = 'BLAD_ODCZYTU'; }
    }
    return o;
  };
  const out = {};
  for (const k of Object.getOwnPropertyNames(window)) {
    if (!/^(runParams|_dida_config_|__AER|_init_data_|__INITIAL|__NEXT_DATA__|__APOLLO)/i.test(k)) continue;
    try { out[k] = strip(window[k], 0); } catch (e) { out[k] = 'BLAD'; }
  }
  return out;
}
"""


class Zablokowany(Exception):
    """AliExpress pokazał captchę albo stronę blokady."""


def zbuduj_url(zapytanie: str, kraj: str, strona: int = 1) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", zapytanie.lower()).strip("-")
    url = f"https://pl.aliexpress.com/w/wholesale-{slug}.html?page={strona}"
    if kraj:
        url += f"&shipFromCountry={kraj}"
    return url


class Scraper:
    """Jedna sesja przeglądarki na cały przebieg skanera."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._pw = None
        self._kontekst = None

    async def __aenter__(self) -> "Scraper":
        self._pw = await async_playwright().start()

        argumenty = ["--disable-dev-shm-usage", "--no-sandbox",
                     "--disable-blink-features=AutomationControlled"]
        opcje = {
            "user_data_dir": str(self.cfg.profil_przegladarki),
            "headless": True,
            "args": argumenty,
            "user_agent": UA,
            "locale": "pl-PL",
            "timezone_id": "Europe/Warsaw",
            "viewport": {"width": 1440, "height": 900},
        }
        if self.cfg.chromium_path:
            opcje["executable_path"] = self.cfg.chromium_path

        self.cfg.profil_przegladarki.mkdir(parents=True, exist_ok=True)
        self._kontekst = await self._pw.chromium.launch_persistent_context(**opcje)

        # Bez tego ciasteczka ceny przyjdą w USD, a wysyłka liczona będzie
        # do innego kraju niż nasz.
        await self._kontekst.add_cookies([{
            "name": "aep_usuc_f",
            "value": (f"site=glo&c_tp={self.cfg.waluta}"
                      f"&region={self.cfg.wysylka_do}&b_locale=pl_PL"),
            "domain": ".aliexpress.com",
            "path": "/",
        }])
        return self

    async def __aexit__(self, *_wyjatek) -> None:
        try:
            if self._kontekst:
                await self._kontekst.close()
        finally:
            if self._pw:
                await self._pw.stop()

    async def _odczekaj(self) -> None:
        """Losowa przerwa — równe odstępy same w sobie wyglądają jak bot."""
        await asyncio.sleep(random.uniform(self.cfg.opoznienie_min_s,
                                           self.cfg.opoznienie_max_s))

    async def szukaj(self, zapytanie: str, kraj: str, strona: int = 1) -> list[Offer]:
        """Zwraca surowe oferty z jednej strony wyników. Rzuca Zablokowany."""
        url = zbuduj_url(zapytanie, kraj, strona)
        strona_www = await self._kontekst.new_page()
        try:
            try:
                await strona_www.goto(url, wait_until="domcontentloaded",
                                      timeout=self.cfg.timeout_strony_s * 1000)
            except Exception as blad:
                logger.warning("Nie udało się otworzyć %s: %s", url, blad)

            # Kafelki doładowują się dopiero przy przewijaniu.
            for _ in range(4):
                await strona_www.mouse.wheel(0, 2200)
                await strona_www.wait_for_timeout(800)
            await strona_www.wait_for_timeout(1500)

            html = (await strona_www.content()).lower()
            adres = strona_www.url.lower()
            trafienia = [m for m in BLOCK_MARKERS if m in html or m in adres]
            if trafienia:
                raise Zablokowany(f"sygnatury: {', '.join(trafienia)}")

            blob = await strona_www.evaluate(JS_DUMP_WINDOW)
        finally:
            await strona_www.close()

        oferty, sciezka = parsuj(blob, kraj)
        logger.info("%-22s %-14s strona %d -> %3d ofert  [%s]",
                    zapytanie, kraj or "wszystkie", strona, len(oferty), sciezka or "brak listy")
        return oferty
