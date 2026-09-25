#!/usr/bin/env python3
"""
Jeden przebieg skanera — to jest program odpalany przez timer systemd.

Świadomie jednorazowy: Chromium potrafi zjeść 600–800 MB, więc lepiej żeby
proces wstał, zrobił swoje i oddał pamięć, niż miał wisieć całą dobę.

    python -m alifilament.scan --test-telegram     # sprawdź token i chat ID
    python -m alifilament.scan --limit 1 --dry-run # jedno zapytanie, bez wysyłki
    python -m alifilament.scan --dry-run           # pełny przebieg na konsolę
    python -m alifilament.scan                     # pełny przebieg + Telegram
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import config as konfiguracja
from . import report
from . import harmonogram
from .coupons import kurs_usd_pln, pobierz_kupony
from .filters import (filtruj_wysylke, odduplikuj, posortuj_i_utnij, przefiltruj)
from .models import ScanResult
from .notifier import Telegram
from .scraper import Scraper, Zablokowany
from .store import Store

logger = logging.getLogger("alifilament")


async def zbierz_oferty(cfg, limit_zapytan: int | None, kraj_override: str) -> ScanResult:
    wynik = ScanResult()
    zapytania = cfg.lista_zapytan()
    if limit_zapytan:
        zapytania = zapytania[:limit_zapytan]

    kraje = [kraj_override] if kraj_override else cfg.kraje_do_przeszukania()
    wynik.magazyny = [k for kraj in kraje for k in kraj.split(",")]

    surowe = []
    async with Scraper(cfg) as scraper:
        for zapytanie in zapytania:
            for kraj in kraje:
                for strona in range(1, cfg.stron_na_zapytanie + 1):
                    wynik.zapytan += 1
                    try:
                        oferty = await scraper.szukaj(zapytanie, kraj, strona)
                        surowe.extend(oferty)
                    except Zablokowany as blokada:
                        wynik.zablokowany = True
                        wynik.bledy.append(f"blokada przy '{zapytanie}' ({kraj}): {blokada}")
                        logger.error("AliExpress zablokował skan: %s", blokada)
                        wynik.surowych_ofert = len(surowe)
                        return wynik
                    except Exception as blad:
                        wynik.bledy.append(
                            f"{zapytanie} / {kraj}: {type(blad).__name__}: {blad}")
                        logger.warning("Błąd zapytania %s/%s: %s", zapytanie, kraj, blad)
                    await scraper._odczekaj()

    wynik.surowych_ofert = len(surowe)
    wynik.oferty = odduplikuj(surowe)
    return wynik


def wyslij_raport(tg: Telegram, wynik: ScanResult, top, kupony, cfg,
                  kurs: float | None = None) -> None:
    if wynik.zablokowany:
        tg.wyslij(report.komunikat_blokady(wynik))
        return

    tg.wyslij(report.naglowek(wynik, top, cfg.alert_zl_za_kg))

    # Lista wszystkich kodów świadomie NIE leci na końcu raportu — kody
    # pasujące do danej kwoty są już na kartach ofert, a pełny spis (także
    # tych z wysokimi progami) jest na żądanie pod /kody.
    for pozycja, oferta in enumerate(top, 1):
        tg.odczekaj()
        tg.wyslij_zdjecie(
            oferta.img_url,
            report.karta_oferty(oferta, pozycja, cfg.alert_zl_za_kg, kupony, kurs),
            przycisk_url=oferta.url,
        )


def powod_pominiecia(magazyn: Store, cfg) -> str:
    """
    Czy ten przebieg ma prawo się odbyć.

    Timer budzi skaner co 15 minut, bo godziny ustawia się z czatu, a nie
    w jednostce systemd. Tu zapada decyzja, czy to właśnie ta pora — i czy
    użytkownik w ogóle chce teraz dostawać raporty.
    """
    if not magazyn.powiadomienia_wlaczone():
        return "wysyłka wstrzymana komendą /stop"

    ostatni = magazyn.ostatni_skan()
    ostatni_ts = ostatni["ts"] if ostatni else None

    godziny = magazyn.godziny(cfg.godziny)
    pora = harmonogram.zalegly_przebieg(godziny, ostatni_ts)
    if not pora:
        return f"nie ta pora (harmonogram: {', '.join(godziny) or 'brak'})"

    # Siatka bezpieczeństwa na wypadek, gdyby dwa procesy wstały obok siebie.
    if harmonogram.za_wczesnie_po_poprzednim(ostatni_ts):
        return f"raport dla pory {pora} właśnie poszedł"

    logger.info("Wykonuję raport dla pory %s", pora)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Skaner filamentu AliExpress")
    ap.add_argument("--dry-run", action="store_true",
                    help="raport na konsolę, bez wysyłki i bez zapisu do bazy")
    ap.add_argument("--test-telegram", action="store_true",
                    help="sprawdź token i chat ID, nic nie skanuj")
    ap.add_argument("--force", action="store_true",
                    help="zignoruj harmonogram i wstrzymanie (ręczne /skanuj)")
    ap.add_argument("--limit", type=int, metavar="N",
                    help="użyj tylko pierwszych N zapytań (szybki test)")
    ap.add_argument("--kraj", default="", metavar="KOD",
                    help="wymuś jeden magazyn, np. PL")
    ap.add_argument("--bez-kuponow", action="store_true", help="pomiń agregatory kodów")
    ap.add_argument("--verbose", "-v", action="store_true", help="logi debug")
    args = ap.parse_args()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
        stream=sys.stdout,
    )
    # httpx loguje na poziomie INFO pełny URL żądania, a token bota siedzi
    # w ścieżce adresu Bot API. Bez tego sekret wyląduje w journalu.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    cfg = konfiguracja.wczytaj()

    if args.test_telegram:
        try:
            klient = Telegram(cfg.token, cfg.chat_id)
        except ValueError as blad:
            print(f"❌ {blad}")
            return 1
        ok = klient.test()
        klient.zamknij()
        return 0 if ok else 1

    magazyn = Store(cfg.baza)
    try:
        # Brama harmonogramu. Sprawdzana zanim ruszy przeglądarka, bo timer
        # budzi nas co 15 minut, a większość tych budzeń kończy się tutaj.
        if not args.force and not args.dry_run:
            powod = powod_pominiecia(magazyn, cfg)
            if powod:
                logger.info("Pomijam przebieg — %s", powod)
                return 0

        return _przebieg(args, cfg, magazyn)
    finally:
        magazyn.zamknij()


def _przebieg(args, cfg, magazyn: Store) -> int:
    # Kupony lecą zwykłym HTTP, więc zbieramy je niezależnie od przeglądarki —
    # gdyby AliExpress zablokował skan, kody i tak mamy skąd wziąć.
    kupony, bledy_kuponow = ([], [])
    if not args.bez_kuponow:
        kupony, bledy_kuponow = pobierz_kupony(cfg.zrodla_kuponow, cfg.max_kuponow)
        logger.info("Kupony: %d (błędy: %s)", len(kupony), bledy_kuponow or "brak")

    wynik = asyncio.run(zbierz_oferty(cfg, args.limit, args.kraj))
    wynik.bledy.extend(bledy_kuponow)
    logger.info("Zebrano %d surowych ofert w %d zapytaniach",
                wynik.surowych_ofert, wynik.zapytan)

    przefiltrowane, odrzuty = przefiltruj(
        wynik.oferty, cfg.marki, cfg.materialy, cfg.blacklist, cfg.magazyny_eu,
        min_zl_za_kg=cfg.min_zl_za_kg)
    wynik.oferty = przefiltrowane
    logger.info("Po filtrach: %d ofert (odrzuty: %s)", len(przefiltrowane), odrzuty)

    magazyn.oznacz_wzgledem_historii(wynik.oferty)

    # Do raportu idzie tryb z konfiguracji, ale w bazie ląduje CAŁA pula —
    # dzięki temu /szukaj platne|bezplatne|wszystkie i /porownaj działają
    # natychmiast, bez ponownego odpytywania AliExpressu.
    do_raportu = filtruj_wysylke(wynik.oferty, cfg.tryb_wysylki)
    logger.info("Tryb wysyłki '%s': %d z %d ofert",
                cfg.tryb_wysylki, len(do_raportu), len(wynik.oferty))

    # Liczbę pozycji można zmienić komendą /ile bez restartu usługi.
    top = posortuj_i_utnij(do_raportu, magazyn.ile_ofert_w_raporcie(cfg.top_n))

    # Kurs potrzebny do przeliczenia progów kuponów (podawanych w dolarach)
    # na złotówki, w których mamy ceny ofert.
    kurs = kurs_usd_pln() if kupony else None

    if args.dry_run:
        print()
        print(report.raport_tekstowy(wynik, top, kupony, cfg.alert_zl_za_kg, kurs))
        print()
        print(f"[dry-run] Nic nie wysłano i nic nie zapisano. Odrzuty: {odrzuty}")
        return 0

    magazyn.oznacz_i_zapisz_kupony(kupony)
    magazyn.zapisz_oferty(wynik.oferty)
    # Do bazy trafia pełna pula posortowana po zł/kg — /szukaj i /porownaj
    # sięgają właśnie tutaj, nie do samej czołówki raportu.
    magazyn.zapisz_skan(wynik, posortuj_i_utnij(wynik.oferty, len(wynik.oferty)))

    try:
        klient = Telegram(cfg.token, cfg.chat_id)
    except ValueError as blad:
        logger.error("Telegram nieskonfigurowany: %s", blad)
        return 1
    try:
        wyslij_raport(klient, wynik, top, kupony, cfg, kurs)
    finally:
        klient.zamknij()

    logger.info("Gotowe: %d ofert w raporcie, %d nowych, %d tańszych",
                len(top), wynik.nowych, wynik.tanszych)
    return 2 if wynik.zablokowany else 0


if __name__ == "__main__":
    sys.exit(main())
