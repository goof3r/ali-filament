"""
Konfiguracja w dwóch warstwach — tak jak w bocie RPi5.

Sekrety (token, chat ID) siedzą w pliku .env ładowanym przez systemd, a reszta
w YAML-u, żeby zmiana marek, progów czy godzin nie wymagała dotykania kodu.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

KATALOG_PROJEKTU = Path(__file__).resolve().parent.parent

SCIEZKI_ENV = [
    os.environ.get("ALIFILAMENT_ENV", ""),
    "/etc/alifilament.env",
    str(KATALOG_PROJEKTU / ".env"),
]
SCIEZKI_YAML = [
    os.environ.get("ALIFILAMENT_CONFIG", ""),
    "/etc/alifilament/config.yaml",
    str(KATALOG_PROJEKTU / "config.yaml"),
    str(KATALOG_PROJEKTU / "config.example.yaml"),
]

# Materiały, na które faktycznie wysyłamy zapytanie do wyszukiwarki.
# "PLA+" nie jest osobnym zapytaniem — zapytanie "pla" i tak je zwraca,
# a rozróżnieniem zajmuje się filters.rozpoznaj_material().
ZAPYTANIA_BAZOWE = ["pla", "petg", "abs", "asa"]


@dataclass
class Config:
    # ── sekrety ──
    token: str = ""
    chat_id: str = ""
    allowed_ids: list[int] = field(default_factory=list)

    # ── co szukamy ──
    marki: list[str] = field(default_factory=lambda: ["jayo", "sunlu", "kingroon"])
    materialy: list[str] = field(default_factory=lambda: ["PLA", "PLA+", "PETG", "ABS", "ASA"])
    zapytania: list[str] = field(default_factory=list)      # puste = wygeneruj z marek
    blacklist: list[str] = field(default_factory=lambda: [
        "suszarka", "dryer", "nozzle", "dysza", "uchwyt", "holder", "hotend",
        "próbka", "sample", "100g", "50g", "czyszcząc", "cleaning", "ekstruder",
        "extruder", "stół", "naklejka", "sticker", "pen", "długopis",
        "żywic", "resin",   # żywica do drukarek SLA, nie filament
    ])

    # ── skąd ──
    magazyny_eu: list[str] = field(default_factory=lambda: [
        "PL", "ES", "CZ", "DE", "FR", "IT", "NL", "BE"])
    wysylka_do: str = "PL"
    waluta: str = "PLN"
    # Potwierdzone rekonesansem: AliExpress przyjmuje listę krajów w jednym URL-u.
    lista_krajow_w_url: bool = True
    # Który tryb wysyłki trafia do raportów z harmonogramu:
    # "darmowa" | "platna" | "wszystkie". Skan zbiera zawsze jedno i drugie,
    # więc komenda /szukaj pokaże każdy tryb bez ponownego skanowania.
    tryb_wysylki: str = "darmowa"
    stron_na_zapytanie: int = 1

    # ── raport ──
    top_n: int = 15
    alert_zl_za_kg: float | None = 60.0
    # Ponizej tego progu cena na pewno nie dotyczy masy z tytulu (patrz filters.py).
    min_zl_za_kg: float = 25.0
    godziny: list[str] = field(default_factory=lambda: ["08:00", "13:00", "20:00"])

    # ── kupony ──
    # Tylko pepper — pozostałe agregatory sprawdzone i odrzucone, powody
    # opisane w nagłówku coupons.py.
    zrodla_kuponow: list[str] = field(default_factory=lambda: ["pepper"])
    max_kuponow: int = 12

    # ── środowisko ──
    katalog_danych: Path = Path("/var/lib/ali-filament")
    chromium_path: str = ""             # puste = Chromium od Playwrighta
    opoznienie_min_s: float = 3.0
    opoznienie_max_s: float = 8.0
    timeout_strony_s: int = 60

    @property
    def baza(self) -> Path:
        return self.katalog_danych / "scanner.db"

    @property
    def profil_przegladarki(self) -> Path:
        return self.katalog_danych / "browser-profile"

    def lista_zapytan(self) -> list[str]:
        """3 marki × 4 materiały = 12 zapytań, chyba że podano własne."""
        if self.zapytania:
            return self.zapytania
        return [f"{marka} {mat}" for marka in self.marki for mat in ZAPYTANIA_BAZOWE]

    def kraje_do_przeszukania(self) -> list[str]:
        """
        Jeśli AliExpress przyjmuje listę krajów w jednym URL-u, robimy jeden
        przelot. Jeśli nie — pętla po magazynach, co mnoży liczbę zapytań.
        """
        if self.lista_krajow_w_url:
            return [",".join(self.magazyny_eu)]
        return list(self.magazyny_eu)


def _wczytaj_env(sciezka: Path) -> dict[str, str]:
    """Prosty parser KEY=VALUE — taki sam format czyta systemd EnvironmentFile."""
    dane = {}
    for linia in sciezka.read_text(encoding="utf-8").splitlines():
        linia = linia.strip()
        if not linia or linia.startswith("#") or "=" not in linia:
            continue
        klucz, _, wartosc = linia.partition("=")
        dane[klucz.strip()] = wartosc.strip().strip('"').strip("'")
    return dane


def _pierwszy_istniejacy(sciezki: list[str]) -> Path | None:
    for s in sciezki:
        if s and Path(s).is_file():
            return Path(s)
    return None


def wczytaj() -> Config:
    cfg = Config()

    plik_yaml = _pierwszy_istniejacy(SCIEZKI_YAML)
    if plik_yaml and yaml:
        dane = yaml.safe_load(plik_yaml.read_text(encoding="utf-8")) or {}

        # Starsza nazwa z pierwszej wersji — mogła zostać w czyimś config.yaml.
        if "tylko_darmowa_wysylka" in dane and "tryb_wysylki" not in dane:
            dane["tryb_wysylki"] = ("darmowa" if dane.pop("tylko_darmowa_wysylka")
                                    else "wszystkie")

        for klucz, wartosc in dane.items():
            if not hasattr(cfg, klucz):
                continue
            if klucz == "katalog_danych":
                wartosc = Path(wartosc)
            setattr(cfg, klucz, wartosc)
        cfg.zrodlo_yaml = str(plik_yaml)  # type: ignore[attr-defined]

    # ENV ma pierwszeństwo — tam siedzą sekrety i nadpisania z systemd.
    srodowisko = dict(os.environ)
    plik_env = _pierwszy_istniejacy(SCIEZKI_ENV)
    if plik_env:
        srodowisko = {**_wczytaj_env(plik_env), **srodowisko}

    cfg.token = srodowisko.get("TELEGRAM_BOT_TOKEN", cfg.token)
    cfg.chat_id = srodowisko.get("TELEGRAM_CHAT_ID", cfg.chat_id)
    if srodowisko.get("ALIFILAMENT_DATA_DIR"):
        cfg.katalog_danych = Path(srodowisko["ALIFILAMENT_DATA_DIR"])
    if srodowisko.get("CHROMIUM_PATH"):
        cfg.chromium_path = srodowisko["CHROMIUM_PATH"]

    dozwoleni = srodowisko.get("TELEGRAM_ALLOWED_IDS", "")
    if dozwoleni:
        cfg.allowed_ids = [int(x) for x in dozwoleni.replace(",", " ").split() if x.strip("-").isdigit()]
    elif cfg.chat_id and cfg.chat_id.strip("-").isdigit():
        cfg.allowed_ids = [int(cfg.chat_id)]

    return cfg
