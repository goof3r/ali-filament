#!/usr/bin/env python3
"""
Test logiki odsiewu na tytułach w stylu tych, które AliExpress faktycznie zwraca.

Nie zastępuje testu na żywych danych — sprawdza to, co da się sprawdzić bez sieci:
rozpoznawanie marki i materiału, pułapki przy parsowaniu masy (1.75mm to nie masa!)
i poprawność przeliczenia na zł/kg.

    python tools/selftest_filters.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alifilament.filters import (  # noqa: E402
    czy_darmowa_wysylka, filtruj_wysylke, masa_i_uwaga, na_czarnej_liscie,
    odduplikuj, parsuj_mase, porownanie_wysylki, rozpoznaj_tryb,
    posortuj_i_utnij,
    przefiltruj, rozpoznaj_marke, rozpoznaj_material, wariantowy_listing,
)
from alifilament.models import Offer  # noqa: E402

MARKI = ["jayo", "sunlu", "kingroon"]
MATERIALY = ["PLA", "PLA+", "PETG", "ABS", "ASA"]
BLACKLIST = ["suszarka", "dryer", "nozzle", "dysza", "uchwyt", "holder",
             "próbka", "sample", "100g", "50g", "czyszcząc", "cleaning"]
MAGAZYNY = ["PL", "ES", "CZ", "DE", "FR", "IT", "NL", "BE"]

bledy = []


def sprawdz(opis: str, otrzymano, oczekiwano):
    ok = otrzymano == oczekiwano
    status = "OK  " if ok else "BLAD"
    print(f"  [{status}] {opis}")
    if not ok:
        print(f"         oczekiwano: {oczekiwano!r}")
        print(f"         otrzymano : {otrzymano!r}")
        bledy.append(opis)


print("\n=== MASA ===")
PRZYPADKI_MASY = [
    ("SUNLU PLA+ Filament 1.75mm 1KG Czarny", 1000),
    ("JAYO PLA Meta 1.1KG 1.75mm", 1100),
    ("KINGROON ABS 1.75 mm 250 g probnik", 250),
    ("3x1KG SUNLU PETG Filament 1.75mm", 3000),
    ("2 x 1 kg SUNLU PLA", 2000),
    ("SUNLU PLA 1.75mm 1KG/2KG/3KG do wyboru", 1000),
    ("SUNLU PLA Filament 1.75mm bez podanej masy", None),
    ("KINGROON PETG 1000G szpula", 1000),
    ("SUNLU ASA 1.75mm 5KG duza szpula", 5000),
]
for tytul, oczekiwana in PRZYPADKI_MASY:
    sprawdz(f"masa z: {tytul[:52]}", parsuj_mase(tytul), oczekiwana)

print("\n  pulapki (nie moga zostac uznane za mase):")
sprawdz("1.75mm nie jest masa", parsuj_mase("SUNLU PLA 1.75mm"), None)
sprawdz("0.4mm dysza nie jest masa", parsuj_mase("KINGROON nozzle 0.4mm"), None)
sprawdz("temperatura 220 stopni", parsuj_mase("PLA 190-220 stopni"), None)

print("\n=== LISTINGI WIELOWARIANTOWE ===")
print("  (AliExpress podaje przy nich cene NAJTANSZEGO wariantu, wiec")
print("   zestawienie jej z masa z tytulu dawaloby fikcyjne zl/kg)")
WARIANTOWE = [
    "JAYO PLA/PLA META/PETG/SILK/PLA+/Wood/ABS/Marble Filament 5KG",
    "Filament do drukarki 3D JAYO 5.5KG PETG/PLA/PLA PLUS 1.75mm",
    "SUNLU PLA 1.75mm 1KG/2KG/3KG do wyboru",
]
for tytul in WARIANTOWE:
    sprawdz(f"wariantowy: {tytul[:46]}", wariantowy_listing(tytul), True)
    masa, uwaga = masa_i_uwaga(tytul)
    sprawdz("  -> masa odrzucona", masa, None)
    sprawdz("  -> jest uzasadnienie", bool(uwaga), True)

print("\n  pojedyncze warianty musza przejsc:")
for tytul, oczekiwana in [
    ("SUNLU PLA+ Filament 1.75mm 1KG Czarny", 1000),
    ("JAYO 9.9KG 3D PETG/PETG Przezroczysty Filament 1.75mm", 9900),
    ("2 x 1 kg SUNLU PLA", 2000),
]:
    masa, uwaga = masa_i_uwaga(tytul)
    sprawdz(f"masa zachowana: {tytul[:44]}", masa, oczekiwana)

print("\n=== MARKA ===")
sprawdz("SUNLU", rozpoznaj_marke("SUNLU PLA+ 1KG", MARKI), "SUNLU")
sprawdz("jayo malymi literami", rozpoznaj_marke("jayo petg 1kg", MARKI), "JAYO")
sprawdz("KINGROON w srodku", rozpoznaj_marke("Filament KINGROON ABS 1kg", MARKI), "KINGROON")
sprawdz("obca marka odpada", rozpoznaj_marke("Eryone PLA 1kg", MARKI), "")
sprawdz("nie lapie fragmentu slowa", rozpoznaj_marke("SUNLUX lampa", MARKI), "")

print("\n=== MATERIAL ===")
sprawdz("PLA+ ma pierwszenstwo przed PLA",
        rozpoznaj_material("SUNLU PLA+ 1.75mm 1KG", MATERIALY), "PLA+")
sprawdz("PLA PLUS to tez PLA+",
        rozpoznaj_material("SUNLU PLA PLUS 1KG", MATERIALY), "PLA+")
sprawdz("zwykle PLA", rozpoznaj_material("SUNLU PLA 1.75mm 1KG", MATERIALY), "PLA")
sprawdz("PETG", rozpoznaj_material("JAYO PETG 1.1KG", MATERIALY), "PETG")
sprawdz("ABS", rozpoznaj_material("KINGROON ABS 1KG", MATERIALY), "ABS")
sprawdz("ASA", rozpoznaj_material("SUNLU ASA UV 1KG", MATERIALY), "ASA")
sprawdz("PLAstic to nie PLA", rozpoznaj_material("PLAstic box organizer", MATERIALY), "")

print("\n=== CZARNA LISTA ===")
sprawdz("suszarka odpada", bool(na_czarnej_liscie("SUNLU Filament Dryer S4", BLACKLIST)), True)
sprawdz("dysza odpada", bool(na_czarnej_liscie("KINGROON nozzle 0.4mm", BLACKLIST)), True)
sprawdz("probka z ogonkiem odpada",
        bool(na_czarnej_liscie("SUNLU PLA probka 100g", BLACKLIST)), True)
sprawdz("normalna szpula przechodzi",
        bool(na_czarnej_liscie("SUNLU PLA+ 1KG czarny", BLACKLIST)), False)

print("\n=== PELNE SITO + ZL/KG ===")
oferty = [
    Offer("1", "SUNLU PLA+ Filament 1.75mm 1KG Czarny", "u1", 62.90, kraj_wysylki="PL"),
    Offer("2", "JAYO PETG Filament 1.75mm 1.1KG Przezroczysty", "u2", 71.50, kraj_wysylki="CZ"),
    Offer("3", "KINGROON ABS 1.75mm 250g probny", "u3", 30.00, kraj_wysylki="ES"),
    Offer("4", "3x1KG SUNLU ASA 1.75mm", "u4", 150.00, kraj_wysylki="PL"),
    Offer("5", "Eryone PLA 1KG", "u5", 40.00, kraj_wysylki="PL"),          # obca marka
    Offer("6", "SUNLU Filament Dryer S4 suszarka", "u6", 199.00, kraj_wysylki="PL"),  # akcesorium
    Offer("7", "SUNLU PLA+ 1.75mm 1KG", "u7", 55.00, kraj_wysylki="CN"),   # spoza EU
    Offer("8", "SUNLU PLA 1.75mm 1KG", "u8", 0.0, kraj_wysylki="PL"),      # brak ceny
]
przeszly, odrzuty = przefiltruj(oferty, MARKI, MATERIALY, BLACKLIST, MAGAZYNY)

sprawdz("przeszly 4 oferty", len(przeszly), 4)
sprawdz("odrzut: obca marka", odrzuty["brak_marki"], 1)
sprawdz("odrzut: akcesorium", odrzuty["czarna_lista"], 1)
sprawdz("odrzut: spoza EU", odrzuty["spoza_eu"], 1)
sprawdz("odrzut: brak ceny", odrzuty["brak_ceny"], 1)

print("\n  przeliczenie na zl/kg:")
wg_id = {o.product_id: o for o in przeszly}
sprawdz("1kg za 62.90 -> 62.90 zl/kg", wg_id["1"].zl_za_kg, 62.90)
sprawdz("1.1kg za 71.50 -> 65.00 zl/kg", wg_id["2"].zl_za_kg, 65.00)
sprawdz("250g za 30.00 -> 120.00 zl/kg", wg_id["3"].zl_za_kg, 120.00)
sprawdz("3kg za 150.00 -> 50.00 zl/kg", wg_id["4"].zl_za_kg, 50.00)

print("\n  sortowanie (najtansze zl/kg na gorze):")
top = posortuj_i_utnij(przeszly, 10)
sprawdz("kolejnosc wg zl/kg", [o.product_id for o in top], ["4", "1", "2", "3"])

print("\n  oferta bez masy ladnie na koncu, ale nie wypada:")
bez_masy = Offer("9", "SUNLU PLA Filament 1.75mm czarny", "u9", 45.0, kraj_wysylki="PL")
przeszly2, _ = przefiltruj([bez_masy] + oferty, MARKI, MATERIALY, BLACKLIST, MAGAZYNY)
top2 = posortuj_i_utnij(przeszly2, 10)
sprawdz("bez masy jest w wyniku", "9" in [o.product_id for o in top2], True)
sprawdz("bez masy na koncu", top2[-1].product_id, "9")

print("\n=== DEDUPLIKACJA ===")
dupy = [
    Offer("7", "SUNLU PLA+ 1KG", "u7", 70.0, kraj_wysylki="PL"),
    Offer("7", "SUNLU PLA+ 1KG", "u7", 62.0, kraj_wysylki="PL"),
    Offer("8", "JAYO PETG 1KG", "u8", 80.0, kraj_wysylki="PL"),
]
odd = odduplikuj(dupy)
sprawdz("zostaly 2 unikalne", len(odd), 2)
sprawdz("zachowana tansza cena", next(o.cena for o in odd if o.product_id == "7"), 62.0)

print("\n  scalanie opisow miedzy wystapieniami:")
print("  (AliExpress dorysowuje znaczniki przy przewijaniu, wiec ta sama oferta")
print("   raz przychodzi z nimi, a raz bez - samo wybieranie jednego wystapienia")
print("   gubilo informacje o darmowej wysylce)")
bogata = Offer("9", "SUNLU PLA 1KG", "u9", 80.0, kraj_wysylki="PL",
               opis_wysylki="Darmowa dostawa", dostawa="Dostawa: Wrz 27",
               ocena=4.8, liczba_ocen=120, sklep="SUNLU Store")
uboga = Offer("9", "SUNLU PLA 1KG", "u9", 70.0, kraj_wysylki="PL")   # tansza, ale bez opisow

for kolejnosc, opis in [([bogata, uboga], "bogata pierwsza"), ([uboga, bogata], "uboga pierwsza")]:
    wynik = odduplikuj(list(kolejnosc))[0]
    sprawdz(f"{opis}: cena z tanszej", wynik.cena, 70.0)
    sprawdz(f"{opis}: znacznik wysylki ocalal", wynik.opis_wysylki, "Darmowa dostawa")
    sprawdz(f"{opis}: ocena ocalala", wynik.ocena, 4.8)
    sprawdz(f"{opis}: sklep ocalal", wynik.sklep, "SUNLU Store")

print("\n=== DARMOWA WYSYLKA ===")
sprawdz("brak znacznika = platna", czy_darmowa_wysylka("", 100.0), False)
sprawdz("bezwarunkowa", czy_darmowa_wysylka("Darmowa dostawa", 50.0), True)
sprawdz("progowa, cena powyzej progu",
        czy_darmowa_wysylka("Darmowa dostawa powyżej 40zł", 62.90), True)
sprawdz("progowa, cena ponizej progu",
        czy_darmowa_wysylka("Darmowa dostawa powyżej 40zł", 35.00), False)
sprawdz("progowa, cena dokladnie na progu",
        czy_darmowa_wysylka("Darmowa dostawa powyżej 40zł", 40.00), True)
sprawdz("prog bez ogonkow tez dziala",
        czy_darmowa_wysylka("Darmowa dostawa powyzej 100zl", 50.00), False)

print("\n  sito NIE odrzuca po wysylce - tylko znaczy:")
print("  (jeden skan musi obsluzyc /szukaj platne, bezplatne i wszystkie)")
z_wysylka = [
    Offer("a", "SUNLU PLA 1.75mm 1KG", "ua", 62.0, kraj_wysylki="PL",
          opis_wysylki="Darmowa dostawa"),
    Offer("b", "JAYO PETG 1.75mm 1KG", "ub", 70.0, kraj_wysylki="PL"),          # platna
    Offer("c", "KINGROON ABS 1.75mm 1KG", "uc", 35.0, kraj_wysylki="PL",
          opis_wysylki="Darmowa dostawa powyżej 40zł"),                          # prog niespelniony
]
przeszly3, odrzuty3 = przefiltruj(z_wysylka, MARKI, MATERIALY, BLACKLIST, MAGAZYNY)
sprawdz("wszystkie trzy w puli", len(przeszly3), 3)
sprawdz("licznik platnych dziala", odrzuty3["platna_wysylka"], 2)
sprawdz("znacznik nadany poprawnie",
        [o.darmowa_wysylka for o in przeszly3], [True, False, False])

print("\n=== TRYBY WYSYLKI (/szukaj) ===")
sprawdz("bezplatne", rozpoznaj_tryb("bezplatne"), "darmowa")
sprawdz("bezpłatne z ogonkiem", rozpoznaj_tryb("bezpłatne"), "darmowa")
sprawdz("darmowe", rozpoznaj_tryb("darmowe"), "darmowa")
sprawdz("platne", rozpoznaj_tryb("platne"), "platna")
sprawdz("płatne z ogonkiem", rozpoznaj_tryb("płatne"), "platna")
sprawdz("wszystkie", rozpoznaj_tryb("wszystkie"), "wszystkie")
sprawdz("WIELKIE LITERY tez", rozpoznaj_tryb("PLATNE"), "platna")
sprawdz("nieznany tryb", rozpoznaj_tryb("jakos"), None)

sprawdz("tryb darmowa", [o.product_id for o in filtruj_wysylke(przeszly3, "darmowa")], ["a"])
sprawdz("tryb platna", [o.product_id for o in filtruj_wysylke(przeszly3, "platna")], ["b", "c"])
sprawdz("tryb wszystkie", len(filtruj_wysylke(przeszly3, "wszystkie")), 3)

print("\n=== POROWNANIE: DARMOWA vs PLATNA ===")
print("  (koszt wysylki nie istnieje w danych AliExpressu, wiec liczymy")
print("   prog oplacalnosci: ile moze kosztowac dostawa, zeby platna wygrala)")
do_porownania = [
    # darmowa: 1 kg za 60 zl -> 60 zl/kg
    Offer("d1", "SUNLU PLA 1.75mm 1KG", "u", 60.0, kraj_wysylki="PL",
          opis_wysylki="Darmowa dostawa", darmowa_wysylka=True, masa_g=1000),
    Offer("d2", "SUNLU PLA 1.75mm 1KG", "u", 70.0, kraj_wysylki="PL",
          opis_wysylki="Darmowa dostawa", darmowa_wysylka=True, masa_g=1000),
    # platna: 2 kg za 100 zl -> 50 zl/kg
    Offer("p1", "JAYO PETG 2KG", "u", 100.0, kraj_wysylki="PL", masa_g=2000),
    Offer("p2", "JAYO PETG 1KG", "u", 80.0, kraj_wysylki="PL", masa_g=1000),
]
dane = porownanie_wysylki(do_porownania)
sprawdz("liczba darmowych", dane["ile_darmowych"], 2)
sprawdz("liczba platnych", dane["ile_platnych"], 2)
sprawdz("najlepsza darmowa to 60 zl/kg", dane["najlepsza_darmowa"].zl_za_kg, 60.0)
sprawdz("najlepsza platna to 50 zl/kg", dane["najlepsza_platna"].zl_za_kg, 50.0)
sprawdz("mediana darmowych", dane["mediana_darmowa"], 65.0)
sprawdz("mediana platnych", dane["mediana_platna"], 65.0)
sprawdz("platna tansza o 10 zl/kg", dane["roznica_za_kg"], 10.0)
sprawdz("zapas na dostawe = 10 zl/kg x 2 kg", dane["zapas_na_dostawe"], 20.0)

print("\n  gdy darmowa jest tansza, roznica schodzi ponizej zera:")
odwrotnie = porownanie_wysylki([
    Offer("d", "SUNLU PLA 1KG", "u", 40.0, kraj_wysylki="PL",
          darmowa_wysylka=True, masa_g=1000),
    Offer("p", "JAYO PETG 1KG", "u", 90.0, kraj_wysylki="PL", masa_g=1000),
])
sprawdz("roznica ujemna", odwrotnie["roznica_za_kg"], -50.0)

print("\n  brak jednej z grup nie wywala porownania:")
tylko_darmowe = porownanie_wysylki([
    Offer("d", "SUNLU PLA 1KG", "u", 40.0, kraj_wysylki="PL",
          darmowa_wysylka=True, masa_g=1000)])
sprawdz("roznica nieokreslona", tylko_darmowe["roznica_za_kg"], None)
sprawdz("najlepsza platna pusta", tylko_darmowe["najlepsza_platna"], None)

print("\n  oferty bez masy sa liczone osobno, nie psuja srednich:")
z_bez_masy = porownanie_wysylki(do_porownania + [
    Offer("x", "SUNLU PLA bez masy", "u", 50.0, kraj_wysylki="PL", darmowa_wysylka=True)])
sprawdz("zgloszone jako bez masy", z_bez_masy["bez_masy"], 1)
sprawdz("nie weszly do grupy darmowych", z_bez_masy["ile_darmowych"], 2)

print("\n" + "=" * 60)
if bledy:
    print(f"NIEPOWODZENIE: {len(bledy)} testow nie przeszlo")
    for b in bledy:
        print(f"  - {b}")
    sys.exit(1)
print("WSZYSTKIE TESTY PRZESZLY")
