#!/usr/bin/env python3
"""
Test decyzji "czy teraz wysyłać raport".

Timer budzi skaner co 15 minut, więc ta logika uruchamia się kilkadziesiąt razy
dziennie i musi trafić dokładnie raz na każdą ustawioną porę — ani zero razy
(przegapiony raport), ani dwa (podwójna wysyłka).

    python tools/selftest_harmonogram.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alifilament.harmonogram import (  # noqa: E402
    nastepny_przebieg, parsuj_godzine, parsuj_godziny, zalegly_przebieg,
)

bledy = []


def sprawdz(opis, otrzymano, oczekiwano):
    ok = otrzymano == oczekiwano
    print(f"  [{'OK  ' if ok else 'BLAD'}] {opis}")
    if not ok:
        print(f"         oczekiwano: {oczekiwano!r}")
        print(f"         otrzymano : {otrzymano!r}")
        bledy.append(opis)


GODZINY = ["08:00", "13:00", "20:00"]


def o(dzien, godz, minuta=0):
    return datetime(2026, 9, dzien, godz, minuta)


print("\n=== PARSOWANIE GODZIN ===")
sprawdz("samo 8 -> 08:00", parsuj_godzine("8"), "08:00")
sprawdz("08:30", parsuj_godzine("08:30"), "08:30")
sprawdz("7.45 z kropka", parsuj_godzine("7.45"), "07:45")
sprawdz("23:59", parsuj_godzine("23:59"), "23:59")
sprawdz("24 odpada", parsuj_godzine("24"), None)
sprawdz("8:75 odpada", parsuj_godzine("8:75"), None)
sprawdz("tekst odpada", parsuj_godzine("rano"), None)

sprawdz("lista sortowana bez duplikatow",
        parsuj_godziny(["20", "8", "13", "8"])[0], ["08:00", "13:00", "20:00"])
sprawdz("przecinki tez dzialaja", parsuj_godziny(["8,13,20"])[0],
        ["08:00", "13:00", "20:00"])
sprawdz("smieci raportowane", parsuj_godziny(["8", "rano"])[1], ["rano"])

print("\n=== POJEDYNCZY DZIEN: dokladnie raz na kazda pore ===")
# Symulujemy budzenia co 15 minut przez calą dobę i liczymy wysyłki.
ostatni = None
wyslane = []
for godzina in range(24):
    for minuta in (0, 15, 30, 45):
        teraz = o(24, godzina, minuta)
        pora = zalegly_przebieg(GODZINY, ostatni, teraz)
        if pora:
            wyslane.append((pora, f"{godzina:02d}:{minuta:02d}"))
            ostatni = teraz.isoformat(timespec="seconds")

sprawdz("liczba raportow w ciagu doby", len(wyslane), 3)
sprawdz("pory, dla ktorych poszly raporty", [p for p, _ in wyslane], GODZINY)
sprawdz("wyslane punktualnie", [k for _, k in wyslane], ["08:00", "13:00", "20:00"])

print("\n=== NADRABIANIE PO WYLACZONYM RPI5 ===")
# Ostatni raport wczoraj o 20:00, maszyna wstaje dzis o 9:30.
wczoraj_2000 = o(23, 20, 0).isoformat(timespec="seconds")
sprawdz("start o 9:30 nadrabia raport z 8:00",
        zalegly_przebieg(GODZINY, wczoraj_2000, o(24, 9, 30)), "08:00")
sprawdz("start o 12:00 juz nie nadrabia (ponad 3h po porze)",
        zalegly_przebieg(GODZINY, wczoraj_2000, o(24, 12, 0)), None)
sprawdz("start o 3 w nocy nie zasypuje zaleglosciami",
        zalegly_przebieg(GODZINY, wczoraj_2000, o(24, 3, 0)), None)

print("\n=== BRAK PODWOJNEJ WYSYLKI ===")
po_raporcie = o(24, 8, 2).isoformat(timespec="seconds")
sprawdz("15 minut po raporcie - cisza",
        zalegly_przebieg(GODZINY, po_raporcie, o(24, 8, 15)), None)
sprawdz("dwie godziny po raporcie - nadal cisza",
        zalegly_przebieg(GODZINY, po_raporcie, o(24, 10, 0)), None)
sprawdz("ale o 13:00 juz kolejny",
        zalegly_przebieg(GODZINY, po_raporcie, o(24, 13, 0)), "13:00")

print("\n=== PRZYPADKI BRZEGOWE ===")
sprawdz("pusty harmonogram nic nie wysyla",
        zalegly_przebieg([], None, o(24, 8, 0)), None)
sprawdz("przed pierwsza pora dnia - cisza",
        zalegly_przebieg(GODZINY, o(23, 20, 0).isoformat(), o(24, 7, 0)), None)
sprawdz("pierwszy raz w zyciu (pusta baza) o 8:05",
        zalegly_przebieg(GODZINY, None, o(24, 8, 5)), "08:00")
sprawdz("uszkodzony znacznik czasu nie wywala",
        zalegly_przebieg(GODZINY, "to-nie-data", o(24, 8, 5)), "08:00")

print("\n=== NASTEPNY PRZEBIEG ===")
sprawdz("o 9:00 nastepny to 13:00",
        nastepny_przebieg(GODZINY, o(24, 9, 0)), o(24, 13, 0))
sprawdz("o 21:00 nastepny to jutro 8:00",
        nastepny_przebieg(GODZINY, o(24, 21, 0)), o(25, 8, 0))
sprawdz("pusty harmonogram nie ma nastepnego",
        nastepny_przebieg([], o(24, 9, 0)), None)

print("\n" + "=" * 60)
if bledy:
    print(f"NIEPOWODZENIE: {len(bledy)} testow nie przeszlo")
    for b in bledy:
        print(f"  - {b}")
    sys.exit(1)
print("WSZYSTKIE TESTY PRZESZLY")
