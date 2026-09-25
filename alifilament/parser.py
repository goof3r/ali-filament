"""
Zamiana bloba JSON ze strony wyszukiwania na listę ofert.

AliExpress przenosi dane między wersjami frontendu i zmienia nazwy pól, więc
nic nie jest tu zaszyte na jedną ścieżkę. Zamiast tego:
  1. lokalizator sam znajduje w blobie tablicę wyglądającą na listę produktów,
  2. każde pole wyciągamy po liście kandydatów, biorąc pierwszy sensowny wynik.

Dzięki temu drobna zmiana u AliExpressu nie kładzie skanera, a tools/probe_search.py
używa dokładnie tego samego lokalizatora, co produkcja — czyli rekonesans
sprawdza realny kod, nie swoją kopię.
"""

from __future__ import annotations

import re

from .models import Offer

ITEM_KEY_RE = re.compile(r"(productId|product_id|itemId|item_id|productid)", re.I)

# Kolejność ma znaczenie — pierwszy niepusty wynik wygrywa.
KANDYDACI = {
    "product_id": ["productId", "product_id", "itemId", "item_id", "id"],
    "tytul": [
        "title.displayTitle", "title.seoTitle", "productTitle", "displayTitle",
        "subject", "title.title", "name", "title",
    ],
    "url": ["productDetailUrl", "detailUrl", "productUrl", "itemUrl", "url", "link"],
    "obrazek": [
        "image.imgUrl", "image.url", "imgUrl", "productImage", "mainImage",
        "image", "picUrl", "imagePath",
    ],
    "cena": [
        "prices.salePrice.minPrice", "prices.salePrice.value", "prices.salePrice",
        "salePrice.minPrice", "salePrice.value", "minPrice.value",
        "price.value", "salePrice", "minPrice", "price",
        "prices.salePrice.formattedPrice", "formattedPrice",
    ],
    "waluta": ["prices.salePrice.currencyCode", "prices.salePrice.currency",
               "salePrice.currency", "currency", "currencyCode"],
    "sklep": ["store.storeName", "storeName", "sellerName", "shopName", "store.name"],
    "ocena": ["evaluation.starRating", "starRating", "averageStar", "rating", "evaluateRate"],
    "liczba_ocen": ["evaluation.evaluateNum", "evaluateNum", "reviewCount", "totalValidNum"],
    "sprzedanych": ["trade.tradeDesc", "tradeDesc", "sales", "soldCount", "orders"],
    "wysylka_kraj": [
        "shipFromCountry", "sendFromCountry", "shipFrom", "sendFrom",
        "logistics.shipFrom", "trade.shipFrom", "warehouse", "shipToCountry",
        "logisticsDesc.shipFrom", "sellerCountry", "countryCode",
    ],
    "dostawa": [
        "logisticsDesc", "shippingDesc", "logistics.desc", "deliveryDesc",
        "trade.logisticsDesc", "sellingPoints.logistics", "freeShipping",
    ],
    "kupon": [
        "promotion.text", "coupon.text", "couponDesc", "promoText",
        "discountDesc", "sellingPoints.promotion", "promotion",
    ],
}

# Nazwy krajów spotykane w danych -> kod ISO.
NAZWA_NA_KOD = {
    "poland": "PL", "polska": "PL", "polski": "PL",
    "spain": "ES", "hiszpania": "ES", "espana": "ES", "españa": "ES",
    "czech republic": "CZ", "czechia": "CZ", "czechy": "CZ",
    "germany": "DE", "niemcy": "DE", "deutschland": "DE",
    "france": "FR", "francja": "FR",
    "italy": "IT", "wlochy": "IT", "włochy": "IT", "italia": "IT",
    "netherlands": "NL", "holandia": "NL",
    "belgium": "BE", "belgia": "BE",
    "portugal": "PT", "portugalia": "PT",
    "austria": "AT", "slovakia": "SK", "hungary": "HU",
    "china": "CN", "chiny": "CN", "mainland china": "CN",
    "turkey": "TR", "turcja": "TR",
    "united states": "US", "usa": "US",
    "russian federation": "RU", "russia": "RU", "rosja": "RU",
    "united kingdom": "GB",
}

KOD_ISO_RE = re.compile(r"^[A-Z]{2}$")


# ── Lokalizator listy produktów ──────────────────────────────────────────────

def znajdz_listy_produktow(node, sciezka="$", znalezione=None, glebokosc=0) -> list[tuple]:
    """
    Szuka w blobie tablic, które wyglądają na listę produktów.

    Kryterium: co najmniej 3 elementy, w większości słowniki, a wśród ich
    kluczy jest coś w rodzaju productId. Zwraca [(ścieżka, długość, klucze)].
    """
    if znalezione is None:
        znalezione = []
    if glebokosc > 16:
        return znalezione

    if isinstance(node, list):
        slowniki = [x for x in node[:5] if isinstance(x, dict)]
        if len(node) >= 3 and len(slowniki) >= 2:
            klucze: set[str] = set()
            for d in slowniki:
                klucze |= set(d.keys())
            if any(ITEM_KEY_RE.search(k) for k in klucze):
                znalezione.append((sciezka, len(node), sorted(klucze)))
        for i, element in enumerate(node[:3]):
            znajdz_listy_produktow(element, f"{sciezka}[{i}]", znalezione, glebokosc + 1)

    elif isinstance(node, dict):
        for klucz, wartosc in node.items():
            znajdz_listy_produktow(wartosc, f"{sciezka}.{klucz}", znalezione, glebokosc + 1)

    return znalezione


def najlepsza_lista(blob) -> tuple[str, list]:
    """Zwraca (ścieżka, lista) dla najdłuższej znalezionej listy produktów."""
    kandydaci = znajdz_listy_produktow(blob)
    if not kandydaci:
        return "", []
    sciezka, _dlugosc, _klucze = max(kandydaci, key=lambda k: k[1])
    return sciezka, po_sciezce(blob, sciezka) or []


def po_sciezce(dane, sciezka: str):
    """Wyciąga wartość po ścieżce w formacie $.a.b[0].c"""
    wezel = dane
    try:
        for klucz, indeks in re.findall(r"\.([^.\[\]]+)|\[(\d+)\]", sciezka):
            wezel = wezel[klucz] if klucz else wezel[int(indeks)]
        return wezel
    except (KeyError, IndexError, TypeError):
        return None


# ── Wyciąganie pojedynczych pól ──────────────────────────────────────────────

def wydobadz(item: dict, sciezki: list[str]):
    """Pierwsza niepusta wartość spośród ścieżek-kandydatów."""
    for sciezka in sciezki:
        wezel = item
        for czesc in sciezka.split("."):
            if not isinstance(wezel, dict) or czesc not in wezel:
                wezel = None
                break
            wezel = wezel[czesc]
        if wezel not in (None, "", [], {}):
            return wezel
    return None


def do_liczby(wartosc) -> float | None:
    """
    Cena bywa liczbą, słownikiem albo tekstem typu "62,90 zł" / "PLN 1 234.56".

    Przy obu separatorach ostatni z nich jest dziesiętny — tak odróżniamy
    "1.234,56" od "1,234.56".
    """
    if wartosc is None:
        return None
    if isinstance(wartosc, (int, float)):
        return float(wartosc) or None
    if isinstance(wartosc, dict):
        for klucz in ("minPrice", "value", "amount", "formattedPrice", "price"):
            if klucz in wartosc:
                wynik = do_liczby(wartosc[klucz])
                if wynik:
                    return wynik
        return None

    tekst = str(wartosc)
    liczby = re.sub(r"[^\d.,]", "", tekst)
    if not liczby:
        return None

    if "," in liczby and "." in liczby:
        if liczby.rfind(",") > liczby.rfind("."):
            liczby = liczby.replace(".", "").replace(",", ".")
        else:
            liczby = liczby.replace(",", "")
    elif "," in liczby:
        # przecinek jako separator tysięcy tylko gdy po nim są dokładnie 3 cyfry
        liczby = liczby.replace(",", "" if re.search(r",\d{3}$", liczby) else ".")

    try:
        wynik = float(liczby)
    except ValueError:
        return None
    return wynik or None


def na_kod_kraju(wartosc) -> str:
    """Normalizuje "Poland" / "polska" / "PL" / {"country":"PL"} do kodu ISO."""
    if wartosc is None:
        return ""
    if isinstance(wartosc, dict):
        for klucz in ("countryCode", "country", "code", "shipFrom", "value", "text"):
            if klucz in wartosc:
                kod = na_kod_kraju(wartosc[klucz])
                if kod:
                    return kod
        return ""
    if isinstance(wartosc, list):
        for element in wartosc:
            kod = na_kod_kraju(element)
            if kod:
                return kod
        return ""

    tekst = str(wartosc).strip()
    if KOD_ISO_RE.match(tekst):
        return tekst
    return NAZWA_NA_KOD.get(tekst.lower(), "")


def na_tekst(wartosc) -> str:
    """Pola opisowe bywają słownikiem z kluczem text/value albo listą fragmentów."""
    if wartosc is None:
        return ""
    if isinstance(wartosc, str):
        return wartosc.strip()
    if isinstance(wartosc, bool):
        return "Darmowa wysyłka" if wartosc else ""
    if isinstance(wartosc, (int, float)):
        return str(wartosc)
    if isinstance(wartosc, dict):
        for klucz in ("text", "displayText", "value", "desc", "content", "title"):
            if klucz in wartosc:
                return na_tekst(wartosc[klucz])
        return ""
    if isinstance(wartosc, list):
        czesci = [na_tekst(x) for x in wartosc[:3]]
        return " · ".join(c for c in czesci if c)
    return ""


# Termin dostawy i promocje AliExpress trzyma w "sellingPoints" — liście
# znaczników, gdzie o przeznaczeniu wpisu mówi pole "source", a nie kolejność.
RE_ZRODLO_DOSTAWY = re.compile(r"ETA|delivery|logistic|shipping", re.I)
RE_ZRODLO_PROMOCJI = re.compile(r"coupon|promo|discount|bonus|bigsave|deal", re.I)


def wszystkie_selling_points(item: dict, wzorzec: re.Pattern) -> list[str]:
    """Wszystkie tekstowe znaczniki, których źródło pasuje do wzorca."""
    punkty = item.get("sellingPoints")
    if not isinstance(punkty, list):
        return []
    znalezione = []
    for punkt in punkty:
        if not isinstance(punkt, dict):
            continue
        if not wzorzec.search(str(punkt.get("source", ""))):
            continue
        tresc = punkt.get("tagContent")
        tekst = (tresc or {}).get("tagText") if isinstance(tresc, dict) else None
        if tekst:
            znalezione.append(str(tekst).strip())
    return znalezione


def z_selling_points(item: dict, wzorzec: re.Pattern) -> str:
    """Pierwszy tekstowy znacznik, którego źródło pasuje do wzorca."""
    znalezione = wszystkie_selling_points(item, wzorzec)
    return znalezione[0] if znalezione else ""


# Darmowa wysyłka nie da się wymusić parametrem w adresie — sprawdzone,
# AliExpress ignoruje isFreeShip/shipFree/freeShipping. Jedynym śladem jest
# znacznik przy ofercie, i to w dwóch odmianach:
#   Free_Shipping_atm         -> "Darmowa dostawa"              (bezwarunkowo)
#   platformFreeShipping_atm  -> "Darmowa dostawa powyżej 40zł" (od progu)
RE_ZRODLO_DARMOWEJ = re.compile(r"free_?shipping", re.I)
RE_PROG_DARMOWEJ = re.compile(r"powy[żz]ej\s*([\d]+(?:[.,]\d+)?)\s*z[łl]", re.I)


def znacznik_darmowej_wysylki(item: dict) -> str:
    """
    Surowy tekst znacznika darmowej wysyłki, bez rozstrzygania czy się należy.

    Rozstrzygnięcie zapada dopiero w filters.czy_darmowa_wysylka(), już po
    deduplikacji — wariant progowy zależy od ceny, a ta może się zmienić, gdy
    scalimy kilka wystąpień tej samej oferty z różnych zapytań.
    """
    teksty = wszystkie_selling_points(item, RE_ZRODLO_DARMOWEJ)
    if not teksty:
        return ""
    # Bezwarunkowa ma pierwszeństwo przed progową.
    for tekst in teksty:
        if not RE_PROG_DARMOWEJ.search(tekst):
            return tekst
    return teksty[0]


def _pelny_url(fragment: str, product_id: str) -> str:
    # Obcinamy ogon parametrów (algo_pvid, algo_exp_id, pdp_ext_f…) — to
    # identyfikatory sesji wyszukiwania, do otwarcia oferty niepotrzebne,
    # a link w raporcie ma być czytelny i stabilny między przebiegami.
    czysty = (fragment or "").split("?")[0]
    if czysty:
        if czysty.startswith("//"):
            return "https:" + czysty
        if czysty.startswith("http"):
            return czysty
        if czysty.startswith("/"):
            return "https://pl.aliexpress.com" + czysty
    return f"https://pl.aliexpress.com/item/{product_id}.html" if product_id else ""


def _pelny_obrazek(fragment) -> str:
    tekst = na_tekst(fragment)
    if not tekst:
        return ""
    if tekst.startswith("//"):
        return "https:" + tekst
    if tekst.startswith("http"):
        return tekst
    return ""


# ── Budowa oferty ────────────────────────────────────────────────────────────

def zbuduj_oferte(item: dict, kraj_z_filtra: str = "") -> Offer | None:
    product_id = na_tekst(wydobadz(item, KANDYDACI["product_id"]))
    tytul = na_tekst(wydobadz(item, KANDYDACI["tytul"]))
    cena = do_liczby(wydobadz(item, KANDYDACI["cena"]))

    if not product_id or not tytul or not cena:
        return None

    # Wyniki wyszukiwania NIE zawierają kraju magazynu przy pojedynczej ofercie
    # (sprawdzone na żywych danych — patrz tools/probe_search.py). Jedyną
    # gwarancją europejskiej wysyłki jest filtr shipFromCountry w adresie, więc
    # to z niego bierzemy kraj. Przy liście krajów wiemy tylko tyle, że magazyn
    # jest w UE — i dokładnie to pokazujemy, zamiast zgadywać konkretny.
    kraj = na_kod_kraju(wydobadz(item, KANDYDACI["wysylka_kraj"]))
    if not kraj and kraj_z_filtra:
        kraj = "EU" if "," in kraj_z_filtra else kraj_z_filtra.upper()

    ocena = do_liczby(wydobadz(item, KANDYDACI["ocena"]))
    liczba_ocen = wydobadz(item, KANDYDACI["liczba_ocen"])
    opis_wysylki = znacznik_darmowej_wysylki(item)

    return Offer(
        product_id=product_id,
        tytul=tytul,
        url=_pelny_url(na_tekst(wydobadz(item, KANDYDACI["url"])), product_id),
        cena=round(cena, 2),
        img_url=_pelny_obrazek(wydobadz(item, KANDYDACI["obrazek"])),
        waluta=na_tekst(wydobadz(item, KANDYDACI["waluta"])) or "PLN",
        kraj_wysylki=kraj,
        dostawa=(z_selling_points(item, RE_ZRODLO_DOSTAWY)
                 or na_tekst(wydobadz(item, KANDYDACI["dostawa"])))[:60],
        # darmowa_wysylka ustala filters, bo zalezy od ceny po deduplikacji
        opis_wysylki=opis_wysylki[:60],
        ocena=ocena if ocena and ocena <= 5 else None,
        liczba_ocen=int(do_liczby(liczba_ocen) or 0) or None,
        sprzedanych=na_tekst(wydobadz(item, KANDYDACI["sprzedanych"]))[:40],
        kupon=(z_selling_points(item, RE_ZRODLO_PROMOCJI)
               or na_tekst(wydobadz(item, KANDYDACI["kupon"])))[:80],
        sklep=na_tekst(wydobadz(item, KANDYDACI["sklep"]))[:50],
    )


def parsuj(blob, kraj_z_filtra: str = "") -> tuple[list[Offer], str]:
    """Zwraca (oferty, ścieżka_z_której_wzięto) — ścieżka bywa cenna w logach."""
    sciezka, surowe = najlepsza_lista(blob)
    oferty = []
    for item in surowe:
        if not isinstance(item, dict):
            continue
        oferta = zbuduj_oferte(item, kraj_z_filtra)
        if oferta:
            oferty.append(oferta)
    return oferty, sciezka
