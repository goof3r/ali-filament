"""
Pamięć skanera — SQLite.

Bez niej każdy raport wyglądałby identycznie. Baza odpowiada na dwa pytania:
czy tę ofertę już kiedyś widzieliśmy i czy dziś jest taniej niż zwykle.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .models import Coupon, Offer, ScanResult

SCHEMAT = """
CREATE TABLE IF NOT EXISTS oferty (
    product_id        TEXT PRIMARY KEY,
    tytul             TEXT NOT NULL,
    marka             TEXT,
    material          TEXT,
    masa_g            INTEGER,
    url               TEXT,
    img_url           TEXT,
    kraj_wysylki      TEXT,
    sklep             TEXT,
    pierwsze_widzenie TEXT NOT NULL,
    ostatnie_widzenie TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ceny (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    ts         TEXT NOT NULL,
    cena       REAL NOT NULL,
    zl_za_kg   REAL
);
CREATE INDEX IF NOT EXISTS idx_ceny_produkt_ts ON ceny(product_id, ts);

CREATE TABLE IF NOT EXISTS kupony (
    zrodlo            TEXT NOT NULL,
    kod               TEXT NOT NULL,
    opis              TEXT,
    wazny_do          TEXT,
    pierwsze_widzenie TEXT NOT NULL,
    ostatnie_widzenie TEXT NOT NULL,
    PRIMARY KEY (zrodlo, kod)
);

-- Ustawienia zmieniane z czatu. Bot zapisuje, skaner czyta przy każdym
-- przebiegu — dzięki temu /stop i /godziny działają bez restartu usług.
CREATE TABLE IF NOT EXISTS ustawienia (
    klucz     TEXT PRIMARY KEY,
    wartosc   TEXT NOT NULL,
    zmieniono TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skany (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    zapytan      INTEGER,
    surowych     INTEGER,
    po_filtrach  INTEGER,
    nowych       INTEGER,
    tanszych     INTEGER,
    zablokowany  INTEGER DEFAULT 0,
    bledy        TEXT,
    raport_json  TEXT
);
"""


def _teraz() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, sciezka: Path):
        sciezka.parent.mkdir(parents=True, exist_ok=True)
        self.polaczenie = sqlite3.connect(str(sciezka))
        self.polaczenie.row_factory = sqlite3.Row
        self.polaczenie.executescript(SCHEMAT)
        self.polaczenie.commit()

    def zamknij(self) -> None:
        self.polaczenie.close()

    # ── Ustawienia sterowane z czatu ─────────────────────────────────────────

    def ustaw(self, klucz: str, wartosc: str) -> None:
        self.polaczenie.execute(
            """
            INSERT INTO ustawienia (klucz, wartosc, zmieniono) VALUES (?, ?, ?)
            ON CONFLICT(klucz) DO UPDATE SET
                wartosc = excluded.wartosc, zmieniono = excluded.zmieniono
            """,
            (klucz, wartosc, _teraz()),
        )
        self.polaczenie.commit()

    def pobierz(self, klucz: str, domyslna: str | None = None) -> str | None:
        wiersz = self.polaczenie.execute(
            "SELECT wartosc FROM ustawienia WHERE klucz = ?", (klucz,)
        ).fetchone()
        return wiersz["wartosc"] if wiersz else domyslna

    def powiadomienia_wlaczone(self) -> bool:
        """Domyślnie włączone — /stop musi być świadomą decyzją użytkownika."""
        return self.pobierz("powiadomienia", "1") == "1"

    def ustaw_powiadomienia(self, wlaczone: bool) -> None:
        self.ustaw("powiadomienia", "1" if wlaczone else "0")

    def godziny(self, domyslne: list[str]) -> list[str]:
        """Godziny ustawione z czatu, a gdy ich nie ma — te z konfiguracji."""
        zapisane = self.pobierz("godziny")
        if not zapisane:
            return list(domyslne)
        rozbite = [g.strip() for g in zapisane.split(",") if g.strip()]
        return rozbite or list(domyslne)

    def ustaw_godziny(self, godziny: list[str]) -> None:
        self.ustaw("godziny", ",".join(godziny))

    def ile_ofert_w_raporcie(self, domyslna: int) -> int:
        """Ile pozycji pokazywać w raporcie — ustawiane komendą /ile."""
        zapisana = self.pobierz("top_n")
        if not zapisana:
            return domyslna
        try:
            return max(1, int(zapisana))
        except ValueError:
            return domyslna

    def ustaw_ile_ofert(self, ile: int) -> None:
        self.ustaw("top_n", str(ile))

    # ── Oferty ───────────────────────────────────────────────────────────────

    def oznacz_wzgledem_historii(self, oferty: list[Offer], okno_dni: int = 7) -> None:
        """
        Nadaje ofertom znaczniki 🆕 / 🔻 na podstawie tego, co już w bazie.

        Punktem odniesienia jest najniższa cena z ostatnich `okno_dni`, a nie
        ostatnia zanotowana — inaczej drobne wahania w górę i w dół co przebieg
        zgłaszałyby "okazję" przy cenie, która wcale nie jest niska.
        """
        granica = (datetime.now() - timedelta(days=okno_dni)).isoformat(timespec="seconds")
        kursor = self.polaczenie.cursor()

        for oferta in oferty:
            wiersz = kursor.execute(
                "SELECT 1 FROM oferty WHERE product_id = ?", (oferta.product_id,)
            ).fetchone()
            oferta.nowa = wiersz is None

            minimum = kursor.execute(
                "SELECT MIN(cena) AS c FROM ceny WHERE product_id = ? AND ts >= ?",
                (oferta.product_id, granica),
            ).fetchone()["c"]

            if minimum is not None and oferta.cena < minimum:
                oferta.poprzednia_cena = round(minimum, 2)

    def zapisz_oferty(self, oferty: list[Offer]) -> None:
        teraz = _teraz()
        kursor = self.polaczenie.cursor()
        for o in oferty:
            kursor.execute(
                """
                INSERT INTO oferty (product_id, tytul, marka, material, masa_g, url,
                                    img_url, kraj_wysylki, sklep,
                                    pierwsze_widzenie, ostatnie_widzenie)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    tytul = excluded.tytul,
                    marka = excluded.marka,
                    material = excluded.material,
                    masa_g = excluded.masa_g,
                    url = excluded.url,
                    img_url = excluded.img_url,
                    kraj_wysylki = excluded.kraj_wysylki,
                    sklep = excluded.sklep,
                    ostatnie_widzenie = excluded.ostatnie_widzenie
                """,
                (o.product_id, o.tytul, o.marka, o.material, o.masa_g, o.url,
                 o.img_url, o.kraj_wysylki, o.sklep, teraz, teraz),
            )
            kursor.execute(
                "INSERT INTO ceny (product_id, ts, cena, zl_za_kg) VALUES (?, ?, ?, ?)",
                (o.product_id, teraz, o.cena, o.zl_za_kg),
            )
        self.polaczenie.commit()

    def historia_cen(self, product_id: str, limit: int = 40) -> list[tuple[str, float]]:
        wiersze = self.polaczenie.execute(
            "SELECT ts, cena FROM ceny WHERE product_id = ? ORDER BY ts DESC LIMIT ?",
            (product_id, limit),
        ).fetchall()
        return [(w["ts"], w["cena"]) for w in reversed(wiersze)]

    def znajdz_oferte(self, fragment_id: str) -> sqlite3.Row | None:
        return self.polaczenie.execute(
            "SELECT * FROM oferty WHERE product_id = ? OR product_id LIKE ?",
            (fragment_id, f"%{fragment_id}%"),
        ).fetchone()

    def ile_ofert(self) -> int:
        return self.polaczenie.execute("SELECT COUNT(*) AS n FROM oferty").fetchone()["n"]

    # ── Kupony ───────────────────────────────────────────────────────────────

    def oznacz_i_zapisz_kupony(self, kupony: list[Coupon]) -> None:
        teraz = _teraz()
        kursor = self.polaczenie.cursor()
        for k in kupony:
            istnieje = kursor.execute(
                "SELECT 1 FROM kupony WHERE zrodlo = ? AND kod = ?", (k.zrodlo, k.kod)
            ).fetchone()
            k.nowy = istnieje is None
            kursor.execute(
                """
                INSERT INTO kupony (zrodlo, kod, opis, wazny_do,
                                    pierwsze_widzenie, ostatnie_widzenie)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(zrodlo, kod) DO UPDATE SET
                    opis = excluded.opis,
                    wazny_do = excluded.wazny_do,
                    ostatnie_widzenie = excluded.ostatnie_widzenie
                """,
                (k.zrodlo, k.kod, k.opis, k.wazny_do, teraz, teraz),
            )
        self.polaczenie.commit()

    def kupony_z_ostatniej_doby(self) -> list[Coupon]:
        granica = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        wiersze = self.polaczenie.execute(
            "SELECT * FROM kupony WHERE ostatnie_widzenie >= ? ORDER BY pierwsze_widzenie DESC",
            (granica,),
        ).fetchall()
        return [Coupon(zrodlo=w["zrodlo"], kod=w["kod"], opis=w["opis"],
                       wazny_do=w["wazny_do"] or "") for w in wiersze]

    # ── Skany ────────────────────────────────────────────────────────────────

    def zapisz_skan(self, wynik: ScanResult, raport: list[Offer]) -> int:
        serializowane = [
            {"product_id": o.product_id, "tytul": o.tytul, "url": o.url,
             "img_url": o.img_url, "cena": o.cena, "zl_za_kg": o.zl_za_kg,
             "marka": o.marka, "material": o.material, "masa_g": o.masa_g,
             "kraj_wysylki": o.kraj_wysylki, "kraj_wysylki_nazwa": o.kraj_wysylki_nazwa,
             "dostawa": o.dostawa, "ocena": o.ocena, "liczba_ocen": o.liczba_ocen,
             "sprzedanych": o.sprzedanych, "kupon": o.kupon, "sklep": o.sklep,
             "uwaga": o.uwaga, "darmowa_wysylka": o.darmowa_wysylka,
             "opis_wysylki": o.opis_wysylki,
             "nowa": o.nowa, "poprzednia_cena": o.poprzednia_cena}
            for o in raport
        ]
        kursor = self.polaczenie.execute(
            """
            INSERT INTO skany (ts, zapytan, surowych, po_filtrach, nowych, tanszych,
                               zablokowany, bledy, raport_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_teraz(), wynik.zapytan, wynik.surowych_ofert, len(wynik.oferty),
             wynik.nowych, wynik.tanszych, int(wynik.zablokowany),
             json.dumps(wynik.bledy, ensure_ascii=False),
             json.dumps(serializowane, ensure_ascii=False)),
        )
        self.polaczenie.commit()
        return kursor.lastrowid or 0

    def ostatni_skan(self) -> sqlite3.Row | None:
        return self.polaczenie.execute(
            "SELECT * FROM skany ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def oferty_z_ostatniego_skanu(self) -> list[Offer]:
        wiersz = self.ostatni_skan()
        if not wiersz or not wiersz["raport_json"]:
            return []
        oferty = []
        for d in json.loads(wiersz["raport_json"]):
            d.pop("zl_za_kg", None)          # właściwość wyliczana, nie pole
            oferty.append(Offer(**d))
        return oferty
