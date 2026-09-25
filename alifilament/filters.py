"""
Odsiew i normalizacja ofert.

Tu powstaje właściwa wartość raportu: z surowej listy z AliExpress zostają
tylko szpule filamentu wybranych marek, a ceny sprowadzone do zł/kg —
bez tego szpula 250 g wygląda w zestawieniu taniej niż kilogram.
"""

from __future__ import annotations

import re
import unicodedata

from .models import Offer

# ── Masa ─────────────────────────────────────────────────────────────────────

# "2x1kg", "2 x 1 KG", "3*1kg" — zestawy wielopakowe
RE_WIELOPAK = re.compile(r"(\d{1,2})\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(kg|g)\b", re.I)
# pojedyncza masa: "1kg", "1.75kg", "250 g", "1000G"
RE_MASA = re.compile(r"(?<![.\d])(\d+(?:[.,]\d+)?)\s*(kg|g)\b", re.I)

# Poza tym zakresem to nie jest szpula filamentu (próbki, wagi paczki, bzdury).
MASA_MIN_G = 100
MASA_MAX_G = 12000


def _do_gramow(wartosc: str, jednostka: str) -> float:
    liczba = float(wartosc.replace(",", "."))
    return liczba * 1000.0 if jednostka.lower() == "kg" else liczba


def parsuj_mase(tytul: str) -> int | None:
    """
    Wyciąga masę szpuli z tytułu oferty.

    Przy kilku różnych masach w tytule bierzemy najmniejszą — zaniżenie masy
    zawyża zł/kg, więc błąd idzie w stronę ostrożności. Sam fakt kilku mas
    oznacza jednak listing wielowariantowy, którym zajmuje się masa_i_uwaga().
    """
    wielopak = RE_WIELOPAK.search(tytul)
    if wielopak:
        sztuk, wartosc, jednostka = wielopak.groups()
        razem = int(sztuk) * _do_gramow(wartosc, jednostka)
        if MASA_MIN_G <= razem <= MASA_MAX_G:
            return int(round(razem))

    znalezione = _wszystkie_masy(tytul)
    return int(round(min(znalezione))) if znalezione else None


def _wszystkie_masy(tytul: str) -> list[float]:
    return [g for g in (_do_gramow(w, j) for w, j in RE_MASA.findall(tytul))
            if MASA_MIN_G <= g <= MASA_MAX_G]


# Tokeny materiałów używane do wykrycia listingu z wieloma wariantami.
RE_TOKENY_MATERIALOW = re.compile(
    r"\b(PLA\s*PLUS|PLA\+|PLA|PETG(?:-CF)?|ABS|ASA|TPU|PVA|HIPS|NYLON|PC|PA|"
    r"SILK|WOOD|MARBLE|META|MATTE|CF)\b", re.I)


# "1/2/3/4/5/10KG" — lista mas z jedną jednostką dopiero na końcu.
# Sam RE_MASA widzi tu wyłącznie "10KG", więc bez tego wzorca listing
# z sześcioma wariantami wyglądałby na zwykłą dziesięciokilogramową szpulę.
RE_LISTA_LICZB = re.compile(r"\d\s*/\s*\d")


def wariantowy_listing(tytul: str) -> bool:
    """
    Czy to oferta z wieloma wariantami ("PETG/PLA/PLA PLUS", "1/2/3/5/10KG").

    Ma to znaczenie, bo AliExpress podaje przy takiej ofercie cenę NAJTAŃSZEGO
    wariantu, a masa w tytule opisuje zwykle największy. Zestawienie jednego
    z drugim daje fikcyjne zł/kg — i to akurat w stronę "super okazji", więc
    takie pozycje wypychałyby z czołówki oferty uczciwe.
    """
    if RE_LISTA_LICZB.search(tytul):
        return True

    # Zwykły tytuł ma najwyżej jeden ukośnik ("PETG/PLA"); wyliczanka opcji
    # ma ich kilka.
    if tytul.count("/") >= 2:
        return True

    materialy = {m.upper().replace(" ", "").replace("PLAPLUS", "PLA+")
                 for m in RE_TOKENY_MATERIALOW.findall(tytul)}
    if len(materialy) >= 3:
        return True

    return len(set(_wszystkie_masy(tytul))) >= 2


def masa_i_uwaga(tytul: str) -> tuple[int | None, str]:
    """Masa szpuli plus ewentualne zastrzeżenie do pokazania w raporcie."""
    # Jawny wielopak ("2x1kg") jest precyzyjny — tu nie ma czego podważać.
    if RE_WIELOPAK.search(tytul):
        return parsuj_mase(tytul), ""

    if wariantowy_listing(tytul):
        return None, "listing wielowariantowy — podana cena dotyczy najtańszej opcji"

    return parsuj_mase(tytul), ""


# ── Marka i materiał ─────────────────────────────────────────────────────────

def rozpoznaj_marke(tytul: str, marki: list[str]) -> str:
    """Zwraca markę z listy, jeśli występuje w tytule jako samodzielne słowo."""
    for marka in marki:
        if re.search(rf"\b{re.escape(marka)}\b", tytul, re.I):
            return marka.upper()
    return ""


def _wzorzec_materialu(material: str) -> re.Pattern:
    """
    "PLA+" musi złapać też "PLA PLUS" i "PLA-PLUS", a samo "PLA" nie może
    złapać "PLAstic" ani "PLA+" (od tego jest osobna pozycja na liście).
    """
    rdzen = material.rstrip("+")
    if material.endswith("+"):
        return re.compile(rf"\b{re.escape(rdzen)}\s*(?:\+|plus\b|-plus\b)", re.I)
    return re.compile(rf"\b{re.escape(rdzen)}\b(?!\s*(?:\+|plus\b))", re.I)


def rozpoznaj_material(tytul: str, materialy: list[str]) -> str:
    """
    Zwraca materiał z listy. Warianty z "+" sprawdzamy najpierw, żeby
    "SUNLU PLA+ 1kg" nie zostało zaklasyfikowane jako zwykłe PLA.
    """
    kolejnosc = sorted(materialy, key=lambda m: (not m.endswith("+"), -len(m)))
    for material in kolejnosc:
        if _wzorzec_materialu(material).search(tytul):
            return material.upper()
    return ""


# ── Odsiew akcesoriów ────────────────────────────────────────────────────────

def _bez_ogonkow(tekst: str) -> str:
    rozlozony = unicodedata.normalize("NFKD", tekst)
    return "".join(z for z in rozlozony if not unicodedata.combining(z)).lower()


def na_czarnej_liscie(tytul: str, blacklist: list[str]) -> str:
    """
    Zwraca dopasowane słowo z czarnej listy albo pusty string.

    Dopasowanie musi zaczynać się na granicy słowa, inaczej wpis "50g" wycina
    legalne szpule 250 g. Końca słowa celowo nie pilnujemy — dzięki temu
    "czyszcząc" łapie też "czyszczące".
    """
    plaski = _bez_ogonkow(tytul)
    for slowo in blacklist:
        wzor = re.escape(_bez_ogonkow(slowo))
        if re.search(rf"(?<![0-9a-z]){wzor}", plaski):
            return slowo
    return ""


# ── Główne sito ──────────────────────────────────────────────────────────────

def przefiltruj(
    oferty: list[Offer],
    marki: list[str],
    materialy: list[str],
    blacklist: list[str],
    magazyny_eu: list[str],
    wymagaj_kraju: bool = True,
    min_zl_za_kg: float = 25.0,
) -> tuple[list[Offer], dict[str, int]]:
    """
    Przepuszcza tylko szpule filamentu wybranych marek z magazynów europejskich.

    Zwraca (przefiltrowane, statystyki_odrzuceń) — statystyki są ważne przy
    diagnozie: jeśli nagle wszystko wypada na "brak marki", to znaczy że
    zmienił się parser, a nie że w sklepie zabrakło filamentu.
    """
    # "EU" to znacznik nadawany przez parser, gdy pytaliśmy o kilka magazynów
    # naraz — wtedy wiadomo, że oferta jest z Unii, ale nie z którego kraju.
    kody_eu = {k.upper() for k in magazyny_eu} | {"EU"}
    wynik: list[Offer] = []
    odrzucone = {"brak_marki": 0, "brak_materialu": 0, "czarna_lista": 0,
                 "spoza_eu": 0, "brak_ceny": 0, "cena_niewiarygodna": 0,
                 "platna_wysylka": 0}   # platna_wysylka tylko zlicza, nie odrzuca

    for oferta in oferty:
        if not oferta.cena or oferta.cena <= 0:
            odrzucone["brak_ceny"] += 1
            continue

        slowo = na_czarnej_liscie(oferta.tytul, blacklist)
        if slowo:
            odrzucone["czarna_lista"] += 1
            continue

        marka = rozpoznaj_marke(oferta.tytul, marki)
        if not marka:
            odrzucone["brak_marki"] += 1
            continue

        material = rozpoznaj_material(oferta.tytul, materialy)
        if not material:
            odrzucone["brak_materialu"] += 1
            continue

        # Gwarancją europejskiego magazynu jest filtr shipFromCountry w adresie —
        # wyniki wyszukiwania nie niosą kraju przy pojedynczej ofercie. Ten test
        # zadziała więc dla znacznika "EU" i dla przebiegów per kraj, a wyłapie
        # ewentualne pozycje, którym AliExpress przypisze magazyn spoza listy.
        kraj = (oferta.kraj_wysylki or "").upper()
        if wymagaj_kraju and kraj and kraj not in kody_eu:
            odrzucone["spoza_eu"] += 1
            continue

        # Darmowej wysyłki nie da się wymusić w adresie wyszukiwania —
        # sprawdzone, AliExpress ignoruje isFreeShip i pokrewne parametry.
        # Jedynym śladem jest znacznik przy ofercie, więc rozstrzygamy tutaj.
        #
        # Świadomie tylko ZNACZYMY, nie odsiewamy: dzięki temu jeden skan
        # wystarcza na wszystkie trzy widoki (/szukaj darmowe|platne|wszystkie)
        # i na porównanie jednego z drugim. Wyborem trybu zajmuje się
        # filtruj_wysylke() już przy składaniu raportu.
        oferta.darmowa_wysylka = czy_darmowa_wysylka(oferta.opis_wysylki, oferta.cena)
        if not oferta.darmowa_wysylka:
            odrzucone["platna_wysylka"] += 1

        oferta.marka = marka
        oferta.material = material
        oferta.masa_g, oferta.uwaga = masa_i_uwaga(oferta.tytul)

        # Ostatnia linia obrony przed fikcyjnym zł/kg. Filament z magazynu
        # w UE nie schodzi poniżej ~30 zł/kg, więc wynik grubo pod progiem
        # znaczy, że cena i masa pochodzą z dwóch różnych wariantów oferty.
        # Nie zgadujemy, która z nich jest prawdziwa — odkładamy pozycję
        # na koniec listy z wyjaśnieniem.
        if oferta.masa_g and (oferta.zl_za_kg or 0) < min_zl_za_kg:
            odrzucone["cena_niewiarygodna"] += 1
            oferta.masa_g = None
            oferta.uwaga = ("cena zbyt niska wobec masy z tytułu — najpewniej "
                            "dotyczy tańszego wariantu tej oferty")

        wynik.append(oferta)

    return wynik, odrzucone


def mediana(wartosci: list[float]) -> float | None:
    if not wartosci:
        return None
    uporzadkowane = sorted(wartosci)
    srodek = len(uporzadkowane) // 2
    if len(uporzadkowane) % 2:
        return round(uporzadkowane[srodek], 2)
    return round((uporzadkowane[srodek - 1] + uporzadkowane[srodek]) / 2, 2)


def porownanie_wysylki(oferty: list[Offer]) -> dict:
    """
    Zestawia grupę z darmową i płatną wysyłką.

    Świadomie NIE liczy ceny z dostawą, bo koszt wysyłki nie występuje
    w wynikach wyszukiwania AliExpressu — sprawdzone, nie ma ani jednego
    takiego pola. Zamiast udawać, że wiemy, podajemy próg opłacalności:
    o ile tańsza jest oferta płatna w samej cenie, czyli ile może kosztować
    dostawa, żeby wciąż wygrała.
    """
    z_masa = [o for o in oferty if o.zl_za_kg]
    darmowe = [o for o in z_masa if o.darmowa_wysylka]
    platne = [o for o in z_masa if not o.darmowa_wysylka]

    najlepsza_darmowa = min(darmowe, key=lambda o: o.zl_za_kg) if darmowe else None
    najlepsza_platna = min(platne, key=lambda o: o.zl_za_kg) if platne else None

    roznica_za_kg = None
    zapas_na_dostawe = None
    if najlepsza_darmowa and najlepsza_platna:
        roznica_za_kg = round(najlepsza_darmowa.zl_za_kg - najlepsza_platna.zl_za_kg, 2)
        if najlepsza_platna.masa_g:
            # Ile złotych może pochłonąć dostawa, żeby oferta płatna wciąż
            # wychodziła taniej od najlepszej darmowej.
            zapas_na_dostawe = round(
                roznica_za_kg * (najlepsza_platna.masa_g / 1000.0), 2)

    return {
        "ile_darmowych": len(darmowe),
        "ile_platnych": len(platne),
        "bez_masy": len(oferty) - len(z_masa),
        "najlepsza_darmowa": najlepsza_darmowa,
        "najlepsza_platna": najlepsza_platna,
        "mediana_darmowa": mediana([o.zl_za_kg for o in darmowe]),
        "mediana_platna": mediana([o.zl_za_kg for o in platne]),
        "roznica_za_kg": roznica_za_kg,
        "zapas_na_dostawe": zapas_na_dostawe,
    }


def posortuj_i_utnij(oferty: list[Offer], top_n: int) -> list[Offer]:
    """Sortowanie po zł/kg; przy równych cenach wyżej ta z lepszą oceną."""
    posortowane = sorted(oferty, key=lambda o: (o.sort_key(), -(o.ocena or 0)))
    return posortowane[:top_n]


# Pola opisowe, które w jednym zapytaniu bywają puste, a w innym wypełnione.
POLA_DO_SCALENIA = ("dostawa", "opis_wysylki", "sprzedanych", "kupon",
                    "sklep", "kraj_wysylki", "img_url", "url")


def _uzupelnij_braki(zrodlo: Offer, cel: Offer) -> Offer:
    """Przenosi do `cel` te pola, których tam brakuje, a w `zrodlo` są."""
    for pole in POLA_DO_SCALENIA:
        if not getattr(cel, pole) and getattr(zrodlo, pole):
            setattr(cel, pole, getattr(zrodlo, pole))
    if cel.ocena is None and zrodlo.ocena is not None:
        cel.ocena = zrodlo.ocena
    if cel.liczba_ocen is None and zrodlo.liczba_ocen is not None:
        cel.liczba_ocen = zrodlo.liczba_ocen
    return cel


def odduplikuj(oferty: list[Offer]) -> list[Offer]:
    """
    Ta sama oferta wraca w kilku zapytaniach — zostawiamy najtańsze wystąpienie,
    ale SCALAMY opisy.

    To nie jest kosmetyka. AliExpress dorysowuje znaczniki (darmowa wysyłka,
    termin dostawy, oceny) dopiero przy przewijaniu, więc w każdym zapytaniu
    kilkanaście kafelków przychodzi bez nich. Samo wybieranie jednego
    wystąpienia gubiło tę informację i kasowało z raportu oferty, które
    darmową wysyłkę mają — po prostu akurat nie w tym zapytaniu.
    """
    najlepsze: dict[str, Offer] = {}
    for oferta in oferty:
        istniejaca = najlepsze.get(oferta.product_id)
        if istniejaca is None:
            najlepsze[oferta.product_id] = oferta
        elif oferta.cena < istniejaca.cena:
            najlepsze[oferta.product_id] = _uzupelnij_braki(istniejaca, oferta)
        else:
            _uzupelnij_braki(oferta, istniejaca)
    return list(najlepsze.values())


# ── Darmowa wysyłka ──────────────────────────────────────────────────────────

TRYB_DARMOWA = "darmowa"
TRYB_PLATNA = "platna"
TRYB_WSZYSTKIE = "wszystkie"

# Nazwy, pod jakimi tryb może przyjść z czatu — z ogonkami i bez.
ALIASY_TRYBU = {
    "darmowa": TRYB_DARMOWA, "darmowe": TRYB_DARMOWA, "darmowej": TRYB_DARMOWA,
    "bezplatne": TRYB_DARMOWA, "bezpłatne": TRYB_DARMOWA,
    "bezplatna": TRYB_DARMOWA, "bezpłatna": TRYB_DARMOWA, "free": TRYB_DARMOWA,
    "platne": TRYB_PLATNA, "płatne": TRYB_PLATNA,
    "platna": TRYB_PLATNA, "płatna": TRYB_PLATNA, "platnej": TRYB_PLATNA,
    "wszystkie": TRYB_WSZYSTKIE, "wszystko": TRYB_WSZYSTKIE,
    "oba": TRYB_WSZYSTKIE, "all": TRYB_WSZYSTKIE,
}

OPISY_TRYBU = {
    TRYB_DARMOWA: "tylko z darmową wysyłką",
    TRYB_PLATNA: "tylko z płatną wysyłką",
    TRYB_WSZYSTKIE: "z darmową i płatną wysyłką",
}


def rozpoznaj_tryb(tekst: str) -> str | None:
    """Zamienia słowo z czatu na tryb. None, gdy nie rozpoznano."""
    return ALIASY_TRYBU.get(_bez_ogonkow(tekst).strip())


def filtruj_wysylke(oferty: list[Offer], tryb: str) -> list[Offer]:
    """Wybiera oferty według trybu wysyłki. Kraj magazynu jest już odsiany wcześniej."""
    if tryb == TRYB_DARMOWA:
        return [o for o in oferty if o.darmowa_wysylka]
    if tryb == TRYB_PLATNA:
        return [o for o in oferty if not o.darmowa_wysylka]
    return list(oferty)


# "Darmowa dostawa powyżej 40zł" — wariant progowy, zależny od kwoty zamówienia.
RE_PROG_DARMOWEJ = re.compile(r"powy[żz]ej\s*(\d+(?:[.,]\d+)?)\s*z[łl]", re.I)


def czy_darmowa_wysylka(opis: str, cena: float) -> bool:
    """
    Czy przy tej cenie wysyłka faktycznie wychodzi za darmo.

    Wariant progowy liczy się tylko wtedy, gdy oferta ten próg przekracza —
    inaczej obiecywalibyśmy darmową dostawę, której kupujący nie dostanie.
    Decyzja zapada po deduplikacji, bo dopiero wtedy znamy ostateczną cenę.
    """
    if not opis:
        return False
    dopasowanie = RE_PROG_DARMOWEJ.search(opis)
    if not dopasowanie:
        return True
    return cena >= float(dopasowanie.group(1).replace(",", "."))
