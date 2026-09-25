"""
Kody rabatowe ogólne — te niezwiązane z konkretną ofertą.

Kupony przypisane do produktu wyciąga parser z danych AliExpressu; tutaj
zbieramy kody typu "AFCEESE30 — 30$ mniej przy wydaniu 225$".

Źródła są w rejestrze ZRODLA i każde ma własny try/except — padnięty
agregator nie może zabrać całego raportu (ten sam układ co funkcje kursów
walut w bocie RPi5).

Stan na wrzesień 2026 — sprawdzone ręcznie przed napisaniem parserów:
  • pepper.pl      — osadza dane kuponów jako JSON (tytuł, kod, data ważności,
                     flaga weryfikacji). Źródło solidne.
  • lowcychin.pl   — ODRZUCONE: kody pojawiają się wyłącznie w komentarzach
                     użytkowników, bez dat i weryfikacji.
  • picodi / kodyrabatowe.pl — ODRZUCONE: kodów nie ma w HTML, są odsłaniane
                     dopiero po kliknięciu (model biznesowy tych serwisów).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import httpx

from .models import Coupon

logger = logging.getLogger(__name__)

NAGLOWKI = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

URL_PEPPER = "https://www.pepper.pl/kupony/aliexpress.com"

RE_KOD = re.compile(r'"code":"([A-Z0-9][A-Z0-9_-]{3,15})"')
RE_TYTUL = re.compile(r'"title":"((?:[^"\\]|\\.)*)"')
RE_KONIEC = re.compile(r'"endTime":"([^"]*)"')
RE_OPUBLIKOWANY = re.compile(r'"published":(true|false)')
RE_WARUNKI = re.compile(r'"termsAndConditions":"((?:[^"\\]|\\.)*)"')

# Kwoty w kuponach AliExpressu są dolarowe: "30$ mniej przy wydaniu 225$".
RE_KWOTA_USD = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:\$|USD)", re.I)
# Próg bywa tylko w regulaminie: "Minimalna wartość zamówienia to 269$".
RE_PROG_Z_WARUNKOW = re.compile(
    r"minimaln\w*\s+warto\w*\s+zam\w*\s+to\s*(\d+(?:[.,]\d+)?)", re.I)

# Kurs NBP — ta sama tabela, z której korzysta bot na RPi5.
URL_NBP_USD = "https://api.nbp.pl/api/exchangerates/rates/a/USD/?format=json"

# Kod musi wyglądać jak kod, a nie jak przypadkowy identyfikator z JSON-a.
RE_SENSOWNY_KOD = re.compile(r"^[A-Z]{2,}[A-Z0-9]*\d*$")


def _odkoduj(surowy: str) -> str:
    """Zamienia sekwencje typu \\u0142 na polskie znaki."""
    try:
        return json.loads(f'"{surowy}"')
    except (json.JSONDecodeError, ValueError):
        return surowy


def _ostatnie_przed(wzorzec: re.Pattern, tekst: str) -> str | None:
    trafienia = wzorzec.findall(tekst)
    return trafienia[-1] if trafienia else None


def _sformatuj_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return ""


def _wygasl(iso: str | None) -> bool:
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt < datetime.now(timezone.utc)
    except ValueError:
        return False


def _liczba(tekst: str) -> float:
    return float(tekst.replace(",", "."))


def wyciagnij_kwoty(tytul: str, warunki: str) -> tuple[float | None, float | None]:
    """
    Wydobywa (rabat, próg) w dolarach.

    W tytule kwoty idą w stałym porządku — najpierw rabat, potem próg
    ("30$ mniej przy wydaniu 225$"). Część kuponów progu w tytule nie podaje
    ("70$ przy dużych zakupach") i wtedy jedynym źródłem jest regulamin.
    """
    kwoty = [_liczba(k) for k in RE_KWOTA_USD.findall(tytul)]
    rabat = kwoty[0] if kwoty else None
    prog = kwoty[1] if len(kwoty) > 1 else None

    if prog is None and warunki:
        z_warunkow = RE_PROG_Z_WARUNKOW.search(warunki)
        if z_warunkow:
            prog = _liczba(z_warunkow.group(1))
        else:
            # W regulaminie pierwsza kwota to zwykle właśnie minimum zamówienia.
            kwoty_warunkow = [_liczba(k) for k in RE_KWOTA_USD.findall(warunki)]
            prog = kwoty_warunkow[0] if kwoty_warunkow else None

    # Rabat większy od progu znaczy, że coś źle odczytaliśmy — lepiej nie
    # obiecywać ceny, której nikt nie dostanie.
    if rabat and prog and rabat >= prog:
        return rabat, None

    return rabat, prog


def kurs_usd_pln(timeout: int = 15) -> float | None:
    """Średni kurs NBP. Bez niego nie przeliczymy dolarowych progów kuponów."""
    try:
        odpowiedz = httpx.get(URL_NBP_USD, headers={"Accept": "application/json"},
                              timeout=timeout)
        odpowiedz.raise_for_status()
        return float(odpowiedz.json()["rates"][0]["mid"])
    except Exception as blad:
        logger.warning("Nie udało się pobrać kursu USD/PLN: %s", blad)
        return None


def pobierz_pepper(timeout: int = 25) -> list[Coupon]:
    """
    Pepper trzyma kupony w blobie JSON (GraphQL) osadzonym w stronie.
    Pola idą w kolejności: title, caption1, caption2, ..., endTime, ..., code —
    czyli tytuł i data ważności zawsze poprzedzają kod w tym samym obiekcie.
    """
    odpowiedz = httpx.get(URL_PEPPER, headers=NAGLOWKI, timeout=timeout,
                          follow_redirects=True)
    odpowiedz.raise_for_status()

    # W źródle JSON jest zaescapowany wewnątrz stringa JS.
    tekst = odpowiedz.text.replace('\\"', '"')

    kupony: dict[str, Coupon] = {}
    for dopasowanie in RE_KOD.finditer(tekst):
        kod = dopasowanie.group(1)
        if kod in kupony or not RE_SENSOWNY_KOD.match(kod):
            continue

        okno = tekst[max(0, dopasowanie.start() - 3000):dopasowanie.start()]

        if _ostatnie_przed(RE_OPUBLIKOWANY, okno) == "false":
            continue

        koniec = _ostatnie_przed(RE_KONIEC, okno)
        if _wygasl(koniec):
            continue

        tytul = _odkoduj(_ostatnie_przed(RE_TYTUL, okno) or "")
        # "AliExpress kod rabatowy: 30$ mniej..." -> "30$ mniej..."
        tytul = re.sub(r"^AliExpress\s+kod\s+rabatowy:\s*", "", tytul, flags=re.I).strip()
        if not tytul:
            continue

        # Regulamin (z minimalną wartością zamówienia) stoi w JSON-ie zaraz
        # ZA kodem, więc szukamy go w oknie po drugiej stronie dopasowania.
        okno_po = tekst[dopasowanie.end():dopasowanie.end() + 1200]
        warunki = _odkoduj(RE_WARUNKI.search(okno_po).group(1)
                           if RE_WARUNKI.search(okno_po) else "")

        rabat, prog = wyciagnij_kwoty(tytul, warunki)

        kupony[kod] = Coupon(zrodlo="pepper.pl", kod=kod, opis=tytul,
                             wazny_do=_sformatuj_date(koniec),
                             rabat_usd=rabat, prog_usd=prog)

    return list(kupony.values())


ZRODLA = {
    "pepper": pobierz_pepper,
}


def pobierz_kupony(zrodla: list[str], maksymalnie: int = 12,
                   timeout: int = 25) -> tuple[list[Coupon], list[str]]:
    """Zwraca (kupony, błędy). Awaria jednego źródła nie przerywa reszty."""
    wszystkie: list[Coupon] = []
    bledy: list[str] = []

    for nazwa in zrodla:
        funkcja = ZRODLA.get(nazwa)
        if funkcja is None:
            bledy.append(f"kupony: nieznane źródło '{nazwa}'")
            continue
        try:
            wszystkie.extend(funkcja(timeout=timeout))
        except Exception as blad:
            bledy.append(f"kupony/{nazwa}: {type(blad).__name__}: {blad}")

    # Najpierw te z najbliższą datą ważności — szybciej przepadną.
    def klucz(k: Coupon) -> tuple:
        try:
            return (0, datetime.strptime(k.wazny_do, "%d.%m.%Y"))
        except (ValueError, TypeError):
            return (1, datetime.max)

    wszystkie.sort(key=klucz)
    return wszystkie[:maksymalnie], bledy
