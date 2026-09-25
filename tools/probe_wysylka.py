#!/usr/bin/env python3
"""
Rekonesans: jak AliExpress oznacza darmową wysyłkę.

Sprawdza dwie drogi naraz, bo obie mogą zawieść:
  1. czy filtr da się wymusić parametrem w adresie (porównanie liczby ofert),
  2. czy pojedyncza oferta niesie znacznik darmowej wysyłki (sellingPoints).

Wynik decyduje, czy filtrujemy po stronie AliExpressu, czy u siebie.

    python tools/probe_wysylka.py
"""

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright  # noqa: E402

from alifilament.parser import najlepsza_lista  # noqa: E402
from alifilament.scraper import JS_DUMP_WINDOW, UA  # noqa: E402

KRAJE = "PL,ES,CZ,DE,FR,IT,NL,BE"
BAZA = f"https://pl.aliexpress.com/w/wholesale-sunlu-pla.html?page=1&shipFromCountry={KRAJE}"

# Kandydaci na parametr wymuszający darmową wysyłkę — sprawdzamy każdy.
WARIANTY = {
    "bez filtra": BAZA,
    "isFreeShip=y": BAZA + "&isFreeShip=y",
    "shipFree=y": BAZA + "&shipFree=y",
    "freeShipping=true": BAZA + "&freeShipping=true",
}


async def pobierz(page, url: str) -> list:
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    for _ in range(4):
        await page.mouse.wheel(0, 2200)
        await page.wait_for_timeout(800)
    await page.wait_for_timeout(1500)
    blob = await page.evaluate(JS_DUMP_WINDOW)
    _sciezka, lista = najlepsza_lista(blob)
    return lista


def znaczniki(pozycje: list) -> Counter:
    """Zlicza wszystkie znaczniki sellingPoints wraz z ich tekstem."""
    licznik = Counter()
    for it in pozycje:
        for punkt in (it.get("sellingPoints") or []):
            if not isinstance(punkt, dict):
                continue
            tresc = punkt.get("tagContent") or {}
            tekst = tresc.get("tagText") if isinstance(tresc, dict) else None
            licznik[f"{punkt.get('source')} | {tekst or '(obrazek)'}"] += 1
    return licznik


async def main():
    async with async_playwright() as pw:
        kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if os.environ.get("CHROMIUM_PATH"):
            kwargs["executable_path"] = os.environ["CHROMIUM_PATH"]
        browser = await pw.chromium.launch(**kwargs)
        ctx = await browser.new_context(user_agent=UA, locale="pl-PL",
                                        timezone_id="Europe/Warsaw",
                                        viewport={"width": 1440, "height": 900})
        await ctx.add_cookies([{
            "name": "aep_usuc_f",
            "value": "site=glo&c_tp=PLN&region=PL&b_locale=pl_PL",
            "domain": ".aliexpress.com", "path": "/",
        }])
        page = await ctx.new_page()

        wyniki = {}
        pierwsza_lista = None
        for nazwa, url in WARIANTY.items():
            pozycje = await pobierz(page, url)
            wyniki[nazwa] = [str(p.get("productId")) for p in pozycje]
            if pierwsza_lista is None:
                pierwsza_lista = pozycje
            print(f"{nazwa:<20} -> {len(pozycje):>3} ofert")
            await page.wait_for_timeout(4000)

        print()
        print("=== CZY PARAMETR COKOLWIEK ZMIENIA ===")
        baza_ids = set(wyniki["bez filtra"])
        for nazwa, ids in wyniki.items():
            if nazwa == "bez filtra":
                continue
            wspolne = len(baza_ids & set(ids))
            print(f"  {nazwa:<20} wspolnych z baza: {wspolne}/{len(ids)} "
                  f"-> {'BEZ ZMIAN' if wspolne == len(ids) == len(baza_ids) else 'INNY WYNIK'}")

        print()
        print("=== ZNACZNIKI PRZY OFERTACH (sellingPoints) ===")
        for etykieta, ile in znaczniki(pierwsza_lista).most_common(25):
            print(f"  {ile:>3}x  {etykieta[:100]}")

        print()
        print("=== SZUKAM SLOW O WYSYLCE W CALEJ OFERCIE ===")
        probka = pierwsza_lista[0]
        plaskie = {}

        def walk(n, p=""):
            if isinstance(n, dict):
                for k, v in n.items():
                    walk(v, f"{p}.{k}" if p else k)
            elif isinstance(n, list):
                for i, v in enumerate(n[:6]):
                    walk(v, f"{p}[{i}]")
            else:
                plaskie[p] = n

        walk(probka)
        for pole, wartosc in plaskie.items():
            tekst = str(wartosc).lower()
            if any(s in tekst for s in ("darmow", "free", "bezpłatn", "wysyłk", "dostawa")):
                print(f"  {pole} = {str(wartosc)[:90]}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
