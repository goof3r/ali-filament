"""
Kiedy wysłać raport.

Godziny ustawia się komendą w czacie, a zmiana timera systemd wymagałaby
uprawnień roota. Dlatego timer budzi skaner co 15 minut, a decyzję "czy to
już ta pora" podejmuje ten moduł na podstawie ustawień z bazy.

Koszt: kilkadziesiąt uruchomień dziennie procesu, który po ćwierć sekundy
stwierdza, że nie jego kolej, i kończy pracę — bez dotykania przeglądarki.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# Jak długo po wyznaczonej porze wolno jeszcze nadrobić zaległy raport.
# Dzięki temu RPi5 włączony o 9:30 wyśle raport z 8:00, ale wybudzony
# o 3 w nocy nie zasypie skrzynki zaległościami z całej doby.
MAX_OPOZNIENIE_H = 3

# Zabezpieczenie przed dwoma raportami z tej samej pory.
MIN_ODSTEP_MIN = 45

RE_GODZINA = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?$")


def parsuj_godzine(tekst: str) -> str | None:
    """"8" / "8:30" / "08.30" -> "08:30". Zwraca None, gdy to nie godzina."""
    dopasowanie = RE_GODZINA.match(tekst.strip())
    if not dopasowanie:
        return None
    godzina = int(dopasowanie.group(1))
    minuta = int(dopasowanie.group(2) or 0)
    if not (0 <= godzina <= 23 and 0 <= minuta <= 59):
        return None
    return f"{godzina:02d}:{minuta:02d}"


def parsuj_godziny(czesci: list[str]) -> tuple[list[str], list[str]]:
    """Zwraca (poprawne_godziny, odrzucone_wpisy) — posortowane i bez duplikatów."""
    poprawne: list[str] = []
    odrzucone: list[str] = []
    for czesc in czesci:
        for fragment in czesc.replace(",", " ").split():
            godzina = parsuj_godzine(fragment)
            if godzina is None:
                odrzucone.append(fragment)
            elif godzina not in poprawne:
                poprawne.append(godzina)
    return sorted(poprawne), odrzucone


def _na_dzis(godzina: str, teraz: datetime) -> datetime:
    hh, mm = godzina.split(":")
    return teraz.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)


def zalegly_przebieg(godziny: list[str], ostatni_ts: str | None,
                     teraz: datetime | None = None,
                     max_opoznienie_h: int = MAX_OPOZNIENIE_H) -> str | None:
    """
    Ostatnia minięta pora, dla której nie poszedł jeszcze raport.

    Pytamy o zaległość, a nie o "czy trafiliśmy w okno", bo RPi5 bywa
    wyłączony. Przy sztywnym oknie raport z 8:00 przepadłby, gdyby maszyna
    wstała o 8:30; tak — zostanie nadrobiony, o ile mieści się w limicie
    opóźnienia.
    """
    teraz = teraz or datetime.now()
    if not godziny:
        return None

    minione = [_na_dzis(g, teraz) for g in godziny if _na_dzis(g, teraz) <= teraz]
    if not minione:
        return None

    ostatnia_pora = max(minione)
    if (teraz - ostatnia_pora) > timedelta(hours=max_opoznienie_h):
        return None

    if ostatni_ts:
        try:
            poprzedni = datetime.fromisoformat(ostatni_ts)
        except (TypeError, ValueError):
            poprzedni = None
        if poprzedni and poprzedni >= ostatnia_pora:
            return None      # raport dla tej pory już poszedł

    return ostatnia_pora.strftime("%H:%M")


def nastepny_przebieg(godziny: list[str], teraz: datetime | None = None) -> datetime | None:
    """Najbliższy termin z harmonogramu — dziś albo jutro."""
    if not godziny:
        return None
    teraz = teraz or datetime.now()
    kandydaci = [_na_dzis(g, teraz) for g in godziny]
    przyszle = [k for k in kandydaci if k > teraz]
    return min(przyszle) if przyszle else min(kandydaci) + timedelta(days=1)


def za_wczesnie_po_poprzednim(ostatni_ts: str | None, teraz: datetime | None = None,
                              min_odstep_min: int = MIN_ODSTEP_MIN) -> bool:
    """Czy poprzedni raport poszedł na tyle niedawno, że to wciąż to samo okno."""
    if not ostatni_ts:
        return False
    teraz = teraz or datetime.now()
    try:
        poprzedni = datetime.fromisoformat(ostatni_ts)
    except (TypeError, ValueError):
        return False
    return (teraz - poprzedni).total_seconds() / 60 < min_odstep_min
