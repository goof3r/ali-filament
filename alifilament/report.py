"""
Składanie raportu — nagłówek, karty ofert, sekcja kodów.

Format jest pod Telegram z parse_mode="HTML": kod rabatowy idzie w <code>,
bo wtedy w aplikacji kopiuje się jednym dotknięciem.
"""

from __future__ import annotations

from datetime import datetime

from .models import Coupon, Offer, ScanResult
from .notifier import esc

FLAGI = {
    "PL": "🇵🇱", "ES": "🇪🇸", "CZ": "🇨🇿", "DE": "🇩🇪", "FR": "🇫🇷",
    "IT": "🇮🇹", "NL": "🇳🇱", "BE": "🇧🇪", "PT": "🇵🇹", "AT": "🇦🇹",
    "SK": "🇸🇰", "HU": "🇭🇺", "SE": "🇸🇪", "CN": "🇨🇳", "TR": "🇹🇷",
    "US": "🇺🇸", "RU": "🇷🇺", "GB": "🇬🇧",
    # Znacznik z parsera: wiadomo, że magazyn jest w UE, ale nie który kraj.
    "EU": "🇪🇺",
}

NAZWY_KRAJOW = {
    "PL": "Polski", "ES": "Hiszpanii", "CZ": "Czech", "DE": "Niemiec",
    "FR": "Francji", "IT": "Włoch", "NL": "Holandii", "BE": "Belgii",
    "PT": "Portugalii", "AT": "Austrii", "SK": "Słowacji", "HU": "Węgier",
    "CN": "Chin", "TR": "Turcji", "US": "USA", "GB": "Wielkiej Brytanii",
    "EU": "magazynu w UE",
}


def pora_dnia(teraz: datetime | None = None) -> tuple[str, str]:
    """Emoji i nazwa pory — raport poranny wygląda inaczej niż wieczorny."""
    godzina = (teraz or datetime.now()).hour
    if godzina < 11:
        return "🌅", "poranny"
    if godzina < 17:
        return "☀️", "południowy"
    return "🌙", "wieczorny"


def zl(kwota: float | None, waluta: str = "zł") -> str:
    """Polski zapis kwoty: 1 234,56 zł"""
    if kwota is None:
        return "—"
    calosc = f"{kwota:,.2f}".replace(",", " ").replace(".", ",")
    return f"{calosc} {waluta}"


def liczba(n: int) -> str:
    """2130 -> "2 130" """
    return f"{n:,}".replace(",", " ")


def odmien(n: int, jeden: str, kilka: str, wiele: str) -> str:
    """
    Polska odmiana liczebnika: 1 nowa, 2-4 nowe, 5+ nowych
    (z wyjątkiem nastek: 12 nowych, nie "12 nowe").
    """
    if n == 1:
        return f"{liczba(n)} {jeden}"
    ostatnia, dwie_ostatnie = n % 10, n % 100
    if 2 <= ostatnia <= 4 and not 12 <= dwie_ostatnie <= 14:
        return f"{liczba(n)} {kilka}"
    return f"{liczba(n)} {wiele}"


# ── Nagłówek ─────────────────────────────────────────────────────────────────

def naglowek(wynik: ScanResult, top: list[Offer], prog: float | None,
             teraz: datetime | None = None) -> str:
    teraz = teraz or datetime.now()
    emoji, nazwa = pora_dnia(teraz)

    ponizej_progu = sum(1 for o in top if prog and (o.zl_za_kg or 1e9) < prog)

    linie = [
        f"{emoji} <b>Filament 3D — raport {nazwa}</b>",
        f"<i>{teraz.strftime('%d.%m.%Y, %H:%M')}</i>",
        "",
        f"🔎 Zapytań: <b>{wynik.zapytan}</b> · magazyny: {', '.join(wynik.magazyny) or '—'}",
        f"📦 Znaleziono <b>{wynik.surowych_ofert}</b> ofert → "
        f"po odsiewie <b>{len(wynik.oferty)}</b> → pokazuję <b>{len(top)}</b>",
    ]

    znaczniki = []
    if wynik.nowych:
        znaczniki.append(f"🆕 {odmien(wynik.nowych, 'nowa', 'nowe', 'nowych')}")
    if wynik.tanszych:
        znaczniki.append(f"🔻 {odmien(wynik.tanszych, 'tańsza', 'tańsze', 'tańszych')}")
    if ponizej_progu:
        znaczniki.append(f"🔥 {ponizej_progu} poniżej {zl(prog)}/kg")
    if znaczniki:
        linie.append(" · ".join(znaczniki))

    # Kody pasujące do kwoty są na kartach ofert; tu tylko wskazówka, gdzie
    # obejrzeć pełny spis, w tym te z progami wyższymi niż nasze oferty.
    linie.append("🎟️ <i>Kody przy ofertach poniżej · pełna lista: /kody</i>")

    if not top:
        linie += ["", "⚠️ <b>Żadna oferta nie przeszła filtrów.</b>",
                  "<i>Jeśli powtórzy się przy kolejnym przebiegu — sprawdź parser "
                  "(<code>journalctl -u alifilament-scan</code>).</i>"]

    if wynik.bledy:
        linie += ["", "⚠️ <i>Drobne problemy w trakcie skanu:</i>"]
        linie += [f"<i>• {esc(b)}</i>" for b in wynik.bledy[:4]]

    return "\n".join(linie)


# ── Kupony przy ofercie ──────────────────────────────────────────────────────

MAKS_KUPONOW_NA_KARCIE = 3


def pasujace_kupony(cena_pln: float, kupony: list[Coupon], kurs: float | None,
                    maksymalnie: int = MAKS_KUPONOW_NA_KARCIE) -> list[Coupon]:
    """
    Kody, które przy TEJ kwocie faktycznie wejdą — od najlepszego rabatu.

    Zwracamy kilka, a nie jeden, bo progi są różne i kupujący może chcieć
    dobrać kod do tego, co ostatecznie wrzuci do koszyka. Nie sumują się:
    kuponów AliExpressu nie da się łączyć ze sobą.
    """
    dzialajace = [k for k in kupony if k.dziala_dla(cena_pln, kurs)]
    dzialajace.sort(key=lambda k: k.rabat_pln(kurs) or 0, reverse=True)
    return dzialajace[:maksymalnie]


def najlepszy_kupon(cena_pln: float, kupony: list[Coupon],
                    kurs: float | None) -> Coupon | None:
    """Kod dający największy rabat spośród tych, które przy tej kwocie wejdą."""
    znalezione = pasujace_kupony(cena_pln, kupony, kurs, maksymalnie=1)
    return znalezione[0] if znalezione else None


def _linie_kuponu(oferta: Offer, kupony: list[Coupon], kurs: float | None) -> list[str]:
    if not kupony or not kurs:
        return []

    dobrane = pasujace_kupony(oferta.cena, kupony, kurs)
    if not dobrane:
        progi = [k.prog_pln(kurs) for k in kupony if k.prog_pln(kurs)]
        if not progi:
            return []
        return [f"🎟️ <i>Kody wchodzą dopiero od {zl(min(progi))} wartości zamówienia</i>"]

    naglowek = ("🎟️ <b>Kod rabatowy:</b>" if len(dobrane) == 1
                else f"🎟️ <b>Kody na tę kwotę</b> <i>(nie łączą się)</i>:")
    linie = [naglowek]

    for i, kupon in enumerate(dobrane):
        rabat = kupon.rabat_pln(kurs) or 0
        po_rabacie = round(oferta.cena - rabat, 2)
        gwiazdka = "  ⭐" if i == 0 and len(dobrane) > 1 else ""
        linie.append(f"   <code>{esc(kupon.kod)}</code> −{zl(rabat)} "
                     f"→ <b>{zl(po_rabacie)}</b>{gwiazdka}")

    # zł/kg liczymy po najlepszym rabacie — to jest realna cena do porównań.
    najlepszy = dobrane[0]
    if oferta.masa_g:
        po_najlepszym = oferta.cena - (najlepszy.rabat_pln(kurs) or 0)
        za_kg = round(po_najlepszym / (oferta.masa_g / 1000.0), 2)
        linie.append(f"   <i>najtaniej {zl(za_kg)}/kg po rabacie</i>")

    return linie


# ── Karta pojedynczej oferty ─────────────────────────────────────────────────

def karta_oferty(oferta: Offer, pozycja: int, prog: float | None,
                 kupony: list[Coupon] | None = None,
                 kurs: float | None = None) -> str:
    zkg = oferta.zl_za_kg
    gorace = prog is not None and zkg is not None and zkg < prog

    znaczniki = []
    if oferta.nowa:
        znaczniki.append("🆕")
    if oferta.stanialo_o:
        znaczniki.append("🔻")
    if gorace:
        znaczniki.append("🔥")
    prefiks = " ".join(znaczniki)

    linie = [f"{prefiks} <b>#{pozycja} {esc(oferta.tytul)}</b>".strip(), ""]

    # Cena + kontekst historyczny
    linia_ceny = f"💰 <b>{zl(oferta.cena)}</b>"
    if oferta.stanialo_o:
        linia_ceny += (f"  <i>(najtaniej od 7 dni — było "
                       f"{zl(oferta.poprzednia_cena)}, -{zl(oferta.stanialo_o)})</i>")
    linie.append(linia_ceny)

    # Cena za kilogram — właściwe kryterium porównawcze
    if zkg is not None:
        masa = f"{oferta.masa_g} g" if oferta.masa_g and oferta.masa_g < 1000 \
            else f"{(oferta.masa_g or 0) / 1000:.2f} kg".replace(".", ",")
        linia_kg = f"⚖️ <b>{zl(zkg)}/kg</b>  <i>({masa})</i>"
        if gorace:
            linia_kg += "  🔥 poniżej progu"
        linie.append(linia_kg)
    else:
        powod = oferta.uwaga or "masa nierozpoznana z tytułu — zweryfikuj w ofercie"
        linie.append(f"⚖️ <i>{esc(powod)}</i>")

    # Skąd jedzie
    kod = (oferta.kraj_wysylki or "").upper()
    if kod:
        flaga = FLAGI.get(kod, "📦")
        nazwa = oferta.kraj_wysylki_nazwa or NAZWY_KRAJOW.get(kod, kod)
        linia_wysylki = f"{flaga} Wysyłka z {esc(nazwa)}"
        if oferta.dostawa:
            linia_wysylki += f" · {esc(oferta.dostawa)}"
        linie.append(linia_wysylki)
    elif oferta.dostawa:
        linie.append(f"📦 {esc(oferta.dostawa)}")

    if oferta.darmowa_wysylka:
        # Pokazujemy oryginalny tekst AliExpressu, bo wariant progowy
        # ("powyżej 40zł") to inna obietnica niż bezwarunkowy.
        linie.append(f"🚚 <b>{esc(oferta.opis_wysylki or 'Darmowa dostawa')}</b>")

    # Wiarygodność
    czesci = []
    if oferta.ocena:
        ocena = f"⭐ {oferta.ocena:.1f}".replace(".", ",")
        if oferta.liczba_ocen:
            ocena += f" ({odmien(oferta.liczba_ocen, 'ocena', 'oceny', 'ocen')})"
        czesci.append(ocena)
    if oferta.sprzedanych:
        czesci.append(f"📈 {esc(oferta.sprzedanych)}")
    if czesci:
        linie.append(" · ".join(czesci))

    if oferta.sklep:
        linie.append(f"🏪 {esc(oferta.sklep)}")
    if oferta.kupon:
        linie.append(f"🏷️ {esc(oferta.kupon)}")

    linie += _linie_kuponu(oferta, kupony or [], kurs)

    return "\n".join(linie)


# ── Kupony ───────────────────────────────────────────────────────────────────

def sekcja_kuponow(kupony: list[Coupon], kurs: float | None = None) -> str:
    if not kupony:
        return ("🎟️ <b>Kody rabatowe</b>\n\n"
                "<i>Brak aktualnych kodów ogólnych w tym przebiegu.</i>")

    linie = ["🎟️ <b>Kody rabatowe AliExpress</b>",
             "<i>Dotknij kodu, aby skopiować.</i>", ""]

    for k in kupony:
        nowy = "🆕 " if k.nowy else ""
        wiersz = f"{nowy}<code>{esc(k.kod)}</code> — {esc(k.opis)}"

        szczegoly = []
        rabat, prog = k.rabat_pln(kurs), k.prog_pln(kurs)
        if rabat and prog:
            szczegoly.append(f"≈{zl(rabat)} rabatu od ≈{zl(prog)} zamówienia")
        if k.wazny_do:
            szczegoly.append(f"ważny do {k.wazny_do}")
        if szczegoly:
            wiersz += f"\n     <i>{' · '.join(szczegoly)}</i>"
        linie.append(wiersz)

    zrodla = sorted({k.zrodlo for k in kupony})
    linie += ["", f"📡 <i>Źródło: {', '.join(zrodla)}</i>"]
    if kurs:
        kurs_pl = f"{kurs:.4f}".replace(".", ",")
        linie.append(f"<i>Kwoty przeliczone po kursie NBP {kurs_pl} zł/USD.</i>")
    linie.append("<i>Kupon liczy się od wartości całego zamówienia, a kodów nie "
                 "da się łączyć — ceny na kartach zakładają zakup samej tej pozycji.</i>")
    return "\n".join(linie)


# ── Zwięzła lista (komendy /top, /szukaj) ────────────────────────────────────

def lista_zwiezla(oferty: list[Offer], naglowek_tekstowy: str) -> str:
    """Jedna linia na ofertę, z linkiem w tytule — bez zdjęć, do przeglądania."""
    linie = [naglowek_tekstowy, ""]
    for i, o in enumerate(oferty, 1):
        znaczniki = ("🆕" if o.nowa else "") + ("🔻" if o.stanialo_o else "")
        zkg = f"{zl(o.zl_za_kg)}/kg" if o.zl_za_kg else "masa nieznana"
        wysylka = "🚚 darmowa" if o.darmowa_wysylka else "📦 płatna"
        flaga = FLAGI.get((o.kraj_wysylki or "").upper(), "")
        linie.append(
            f"{i}. {znaczniki} <a href=\"{esc(o.url)}\">{esc(o.tytul[:58])}</a>\n"
            f"    <b>{zl(o.cena)}</b> · {zkg} · {wysylka} {flaga}".rstrip()
        )
    return "\n".join(linie)


# ── Porównanie: darmowa vs płatna wysyłka ────────────────────────────────────

def sekcja_porownania(dane: dict) -> str:
    """
    Zestawienie obu grup plus próg opłacalności.

    Nie podajemy ceny z dostawą, bo koszt wysyłki nie istnieje w danych
    wyszukiwania AliExpressu. Zamiast tego mówimy, ile dostawa może kosztować,
    żeby oferta płatna wciąż wygrała — to informacja, którą da się sprawdzić
    jednym kliknięciem w ofertę.
    """
    darmowa, platna = dane["najlepsza_darmowa"], dane["najlepsza_platna"]

    linie = ["⚖️ <b>Darmowa czy płatna wysyłka — co wychodzi taniej</b>", ""]

    linie.append(f"🚚 <b>Z darmową dostawą</b> — {dane['ile_darmowych']} ofert")
    if darmowa:
        linie += [f"    najtaniej: <b>{zl(darmowa.zl_za_kg)}/kg</b>",
                  f"    <i>{esc(darmowa.tytul[:56])}</i>",
                  f"    mediana: {zl(dane['mediana_darmowa'])}/kg"]
    else:
        linie.append("    <i>brak ofert w tej grupie</i>")

    linie += ["", f"📦 <b>Z płatną dostawą</b> — {dane['ile_platnych']} ofert"]
    if platna:
        linie += [f"    najtaniej: <b>{zl(platna.zl_za_kg)}/kg</b>",
                  f"    <i>{esc(platna.tytul[:56])}</i>",
                  f"    mediana: {zl(dane['mediana_platna'])}/kg"]
    else:
        linie.append("    <i>brak ofert w tej grupie</i>")

    roznica = dane["roznica_za_kg"]
    if roznica is None:
        linie += ["", "<i>Do porównania potrzebne są oferty w obu grupach.</i>"]
        return "\n".join(linie)

    linie.append("")
    if roznica > 0:
        # Oferta płatna jest tańsza w samej cenie — pytanie tylko o ile.
        linie.append(f"💡 <b>Płatna jest tańsza o {zl(roznica)}/kg</b> w samej cenie.")
        if dane["zapas_na_dostawe"]:
            linie.append(
                f"Przy tej szpuli ({platna.masa_g / 1000:.2f} kg".replace(".", ",")
                + f") daje to <b>{zl(dane['zapas_na_dostawe'])}</b> zapasu na dostawę — "
                "jeśli wysyłka wyjdzie taniej, opłaca się ta z płatną."
            )
    elif roznica < 0:
        linie.append(
            f"💡 <b>Darmowa wygrywa</b> — jest tańsza o {zl(abs(roznica))}/kg "
            "już w samej cenie, a dostawy nie dopłacasz."
        )
    else:
        linie.append("💡 Obie grupy mają tę samą najlepszą cenę za kilogram.")

    linie += ["", "ℹ️ <i>Koszt wysyłki nie jest podawany w wynikach wyszukiwania "
              "AliExpressu — trzeba go sprawdzić w samej ofercie. Dlatego podaję "
              "próg opłacalności, a nie cenę z dostawą.</i>"]
    if dane["bez_masy"]:
        linie.append(f"<i>Pominięto {dane['bez_masy']} ofert bez rozpoznanej masy.</i>")

    return "\n".join(linie)


def komunikat_blokady(wynik: ScanResult) -> str:
    return ("⚠️ <b>AliExpress poprosił o weryfikację</b>\n\n"
            "Skan został przerwany, żeby nie pogłębiać blokady. "
            "Kolejna próba w następnym oknie harmonogramu.\n\n"
            + ("\n".join(f"<i>• {esc(b)}</i>" for b in wynik.bledy[:3])))


# ── Wersja tekstowa (--dry-run, konsola) ─────────────────────────────────────

def raport_tekstowy(wynik: ScanResult, top: list[Offer], kupony: list[Coupon],
                    prog: float | None, kurs: float | None = None) -> str:
    linie = ["=" * 78, naglowek(wynik, top, prog).replace("<b>", "").replace("</b>", "")
             .replace("<i>", "").replace("</i>", ""), "=" * 78, ""]

    naglowki = (f"{'#':<3} {'zł/kg':>8} {'cena':>9} {'masa':>7} {'kraj':>5}  "
                f"{'kod':<10} {'po kodzie':>10}  tytuł")
    linie += [naglowki, "-" * 100]
    for i, o in enumerate(top, 1):
        zkg = f"{o.zl_za_kg:.2f}" if o.zl_za_kg else "—"
        masa = f"{o.masa_g}g" if o.masa_g else "—"
        znaki = ("N" if o.nowa else "") + ("↓" if o.stanialo_o else "")

        kupon = najlepszy_kupon(o.cena, kupony, kurs)
        kod = kupon.kod if kupon else "—"
        po_kodzie = (f"{o.cena - (kupon.rabat_pln(kurs) or 0):.2f}" if kupon else "—")

        linie.append(f"{i:<3} {zkg:>8} {o.cena:>9.2f} {masa:>7} "
                     f"{o.kraj_wysylki or '—':>5}  {kod:<10} {po_kodzie:>10}  "
                     f"{znaki:<2}{o.tytul[:40]}")

    linie += ["", "-" * 100, f"KUPONY (kurs NBP: {kurs or '—'} zł/USD):"]
    for k in kupony:
        rabat, prog_pln = k.rabat_pln(kurs), k.prog_pln(kurs)
        kwoty = (f"-{rabat:.2f} zl od {prog_pln:.2f} zl" if rabat and prog_pln else "—")
        linie.append(f"  {k.kod:<14} {kwoty:<28} {k.wazny_do:<12} {k.opis[:40]}")
    if not kupony:
        linie.append("  (brak)")

    if wynik.bledy:
        linie += ["", "BLEDY:"] + [f"  • {b}" for b in wynik.bledy]

    return "\n".join(linie)
