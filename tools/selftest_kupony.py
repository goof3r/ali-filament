#!/usr/bin/env python3
"""
Test doboru kodów rabatowych do konkretnej oferty.

Kupony AliExpressu działają od progu wartości zamówienia i nie łączą się
ze sobą, więc przy każdej ofercie trzeba pokazać te, które przy TEJ kwocie
faktycznie wejdą — posortowane od największego rabatu.

    python tools/selftest_kupony.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alifilament.coupons import wyciagnij_kwoty  # noqa: E402
from alifilament.models import Coupon, Offer  # noqa: E402
from alifilament.report import (  # noqa: E402
    MAKS_KUPONOW_NA_KARCIE, karta_oferty, najlepszy_kupon, pasujace_kupony,
)

bledy = []


def sprawdz(opis, otrzymano, oczekiwano):
    ok = otrzymano == oczekiwano
    print(f"  [{'OK  ' if ok else 'BLAD'}] {opis}")
    if not ok:
        print(f"         oczekiwano: {oczekiwano!r}")
        print(f"         otrzymano : {otrzymano!r}")
        bledy.append(opis)


KURS = 4.0   # okragly kurs, zeby progi wychodzily na rowne kwoty

# Progi w PLN przy kursie 4.0: 12, 40, 120, 400
KUPONY = [
    Coupon("pepper.pl", "MALY", "3$ od 3$", rabat_usd=1.0, prog_usd=3.0),     # 4 zl od 12 zl
    Coupon("pepper.pl", "SREDNI", "5$ od 10$", rabat_usd=5.0, prog_usd=10.0),  # 20 zl od 40 zl
    Coupon("pepper.pl", "DUZY", "15$ od 30$", rabat_usd=15.0, prog_usd=30.0),  # 60 zl od 120 zl
    Coupon("pepper.pl", "OGROMNY", "50$ od 100$", rabat_usd=50.0, prog_usd=100.0),  # 200 od 400
]

print("\n=== PROGI: co wchodzi przy jakiej kwocie ===")
sprawdz("przy 10 zl nie wchodzi nic", [k.kod for k in pasujace_kupony(10.0, KUPONY, KURS)], [])
sprawdz("przy 15 zl tylko MALY", [k.kod for k in pasujace_kupony(15.0, KUPONY, KURS)], ["MALY"])
sprawdz("przy 50 zl SREDNI i MALY (od najlepszego)",
        [k.kod for k in pasujace_kupony(50.0, KUPONY, KURS)], ["SREDNI", "MALY"])
sprawdz("przy 200 zl trzy kody, najlepszy pierwszy",
        [k.kod for k in pasujace_kupony(200.0, KUPONY, KURS)], ["DUZY", "SREDNI", "MALY"])

print("\n  limit pozycji na karcie:")
sprawdz("przy 500 zl pasuja 4, pokazujemy 3",
        len(pasujace_kupony(500.0, KUPONY, KURS)), MAKS_KUPONOW_NA_KARCIE)
sprawdz("i sa to trzy najlepsze",
        [k.kod for k in pasujace_kupony(500.0, KUPONY, KURS)], ["OGROMNY", "DUZY", "SREDNI"])

print("\n=== NAJLEPSZY KUPON ===")
sprawdz("przy 200 zl najlepszy to DUZY", najlepszy_kupon(200.0, KUPONY, KURS).kod, "DUZY")
sprawdz("gdy nic nie pasuje - None", najlepszy_kupon(5.0, KUPONY, KURS), None)
sprawdz("bez kursu nie zgadujemy", pasujace_kupony(200.0, KUPONY, None), [])

print("\n=== KARTA OFERTY ===")
oferta = Offer("1", "SUNLU PLA+ 1.75mm 1KG", "https://x/1", 200.0,
               kraj_wysylki="PL", darmowa_wysylka=True,
               opis_wysylki="Darmowa dostawa", masa_g=1000)
karta = karta_oferty(oferta, 1, 60.0, KUPONY, KURS)
print("\n".join("    " + w for w in karta.splitlines()))
print()
sprawdz("na karcie sa trzy kody",
        sum(1 for k in ("MALY", "SREDNI", "DUZY") if k in karta), 3)
sprawdz("kod z za wysokim progiem NIE trafil na karte", "OGROMNY" in karta, False)
sprawdz("jest adnotacja o nielaczeniu", "nie łączą się" in karta, True)
sprawdz("najlepszy oznaczony gwiazdka", "⭐" in karta, True)
sprawdz("cena po najlepszym rabacie (200-60=140)", "140,00 zł" in karta, True)
sprawdz("zl/kg po rabacie", "140,00 zł/kg po rabacie" in karta, True)

print("\n  jedna pasujaca pozycja - liczba pojedyncza, bez gwiazdki:")
tania = Offer("2", "SUNLU PLA 1KG", "https://x/2", 15.0, masa_g=1000)
karta_tania = karta_oferty(tania, 1, None, KUPONY, KURS)
sprawdz("naglowek w liczbie pojedynczej", "Kod rabatowy:" in karta_tania, True)
sprawdz("bez gwiazdki", "⭐" in karta_tania, False)

print("\n  gdy nic nie pasuje - mowimy od jakiej kwoty:")
bardzo_tania = Offer("3", "SUNLU PLA 1KG", "https://x/3", 5.0, masa_g=1000)
karta_bez = karta_oferty(bardzo_tania, 1, None, KUPONY, KURS)
sprawdz("informacja o progu", "Kody wchodzą dopiero od 12,00 zł" in karta_bez, True)

print("\n=== PARSOWANIE KWOT Z OPISOW PEPPERA ===")
for tytul, warunki, oczekiwane in [
    ("30$ mniej przy wydaniu 225$", "", (30.0, 225.0)),
    ("6$ mniej przy zakupach od 59$. Wpisz kod", "", (6.0, 59.0)),
    ("Największy kupon: 70$ przy dużych zakupach",
     "Minimalna wartość zamówienia to 699$.", (70.0, 699.0)),
    ("Kod daje 16$ rabatu", "", (16.0, None)),
]:
    sprawdz(f"{tytul[:44]}", wyciagnij_kwoty(tytul, warunki), oczekiwane)

print("\n  rabat nie moze byc wiekszy od progu (znak zlego odczytu):")
sprawdz("prog odrzucony", wyciagnij_kwoty("50$ rabatu od 10$", ""), (50.0, None))

print("\n" + "=" * 60)
if bledy:
    print(f"NIEPOWODZENIE: {len(bledy)} testow nie przeszlo")
    for b in bledy:
        print(f"  - {b}")
    sys.exit(1)
print("WSZYSTKIE TESTY PRZESZLY")
