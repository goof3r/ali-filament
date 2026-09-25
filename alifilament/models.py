"""Struktury danych krążące między modułami."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Offer:
    """Pojedyncza oferta filamentu z AliExpress."""

    product_id: str
    tytul: str
    url: str
    cena: float                      # w walucie z konfiguracji (domyślnie PLN)
    img_url: str = ""
    waluta: str = "PLN"

    # Rozpoznane przez filters.py
    marka: str = ""
    material: str = ""
    masa_g: int | None = None

    # Z oferty
    kraj_wysylki: str = ""           # kod ISO, np. "PL"
    kraj_wysylki_nazwa: str = ""     # "Polska"
    dostawa: str = ""                # "Dostawa: Wrz 27 - Paź 01"
    darmowa_wysylka: bool = False
    opis_wysylki: str = ""           # "Darmowa dostawa" / "... powyżej 40zł"
    ocena: float | None = None
    liczba_ocen: int | None = None
    sprzedanych: str = ""
    kupon: str = ""                  # rabat/kupon widoczny przy ofercie
    uwaga: str = ""                  # zastrzeżenie do pokazania w raporcie
    sklep: str = ""

    # Nadawane przez store.py przy porównaniu z historią
    nowa: bool = False
    poprzednia_cena: float | None = None

    @property
    def zl_za_kg(self) -> float | None:
        """Cena znormalizowana do kilograma — jedyny uczciwy sposób porównania szpul."""
        if not self.masa_g:
            return None
        return round(self.cena / (self.masa_g / 1000.0), 2)

    @property
    def stanialo_o(self) -> float | None:
        if self.poprzednia_cena is None:
            return None
        roznica = self.poprzednia_cena - self.cena
        return round(roznica, 2) if roznica > 0 else None

    def sort_key(self) -> tuple:
        """Oferty bez rozpoznanej masy lądują na końcu, ale nie wypadają z listy."""
        zkg = self.zl_za_kg
        return (0, zkg) if zkg is not None else (1, self.cena)


@dataclass
class Coupon:
    """Kod rabatowy — ogólny (z agregatora) albo przypisany do oferty."""

    zrodlo: str
    kod: str
    opis: str = ""
    wazny_do: str = ""
    nowy: bool = False

    # Kupony AliExpressu działają na wartość całego zamówienia i są podawane
    # w dolarach — stąd przeliczenie na złotówki przy zestawianiu z ofertą.
    rabat_usd: float | None = None
    prog_usd: float | None = None

    def rabat_pln(self, kurs: float | None) -> float | None:
        return round(self.rabat_usd * kurs, 2) if (self.rabat_usd and kurs) else None

    def prog_pln(self, kurs: float | None) -> float | None:
        return round(self.prog_usd * kurs, 2) if (self.prog_usd and kurs) else None

    def dziala_dla(self, cena_pln: float, kurs: float | None) -> bool:
        """Czy przy tej kwocie zamówienia kod w ogóle wejdzie."""
        prog = self.prog_pln(kurs)
        return bool(self.rabat_pln(kurs)) and prog is not None and cena_pln >= prog


@dataclass
class ScanResult:
    """Wynik jednego przebiegu skanera."""

    oferty: list[Offer] = field(default_factory=list)
    kupony: list[Coupon] = field(default_factory=list)
    zapytan: int = 0
    surowych_ofert: int = 0          # ile pozycji AliExpress zwrócił przed filtrami
    magazyny: list[str] = field(default_factory=list)
    bledy: list[str] = field(default_factory=list)
    zablokowany: bool = False        # captcha / blokada anty-bot

    @property
    def nowych(self) -> int:
        return sum(1 for o in self.oferty if o.nowa)

    @property
    def tanszych(self) -> int:
        return sum(1 for o in self.oferty if o.stanialo_o)
