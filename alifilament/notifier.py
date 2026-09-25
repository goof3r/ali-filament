"""
Klient Bot API Telegrama — cienki, na czystym HTTP.

Skaner jest procesem jednorazowym odpalanym z timera, więc nie ma sensu
budzić dla niego całej biblioteki bota. Bot interaktywny (bot.py) to osobna
sprawa i używa python-telegram-bot.
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{metoda}"

# Telegram przyjmuje ~20 wiadomości na minutę w grupie. Przy 15 kartach ofert
# ta przerwa mieści nas z zapasem i nie wywołuje 429.
PRZERWA_S = 1.2

LIMIT_WIADOMOSCI = 3800   # realny limit to 4096, zostawiamy margines na HTML
LIMIT_PODPISU = 1000      # podpis pod zdjęciem ma limit 1024


def esc(tekst: str) -> str:
    """Escapowanie pod parse_mode=HTML (jak w bocie RPi5)."""
    return (tekst or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Telegram:
    def __init__(self, token: str, chat_id: str, timeout: int = 30):
        if not token:
            raise ValueError("Brak TELEGRAM_BOT_TOKEN")
        if not chat_id:
            raise ValueError("Brak TELEGRAM_CHAT_ID")
        self.token = token
        self.chat_id = chat_id
        self.klient = httpx.Client(timeout=timeout)

    def zamknij(self) -> None:
        self.klient.close()

    # ── Niskopoziomowe ───────────────────────────────────────────────────────

    def _wywolaj(self, metoda: str, dane: dict, prob: int = 3) -> dict | None:
        url = API.format(token=self.token, metoda=metoda)
        for proba in range(prob):
            try:
                odpowiedz = self.klient.post(url, json=dane)
                tresc = odpowiedz.json()
                if tresc.get("ok"):
                    return tresc.get("result")

                # 429 — Telegram sam mówi, ile czekać.
                if odpowiedz.status_code == 429:
                    czekaj = tresc.get("parameters", {}).get("retry_after", 5)
                    logger.warning("Telegram 429, czekam %ss", czekaj)
                    time.sleep(czekaj + 1)
                    continue

                logger.error("Telegram %s: %s", metoda, tresc.get("description"))
                return None
            except Exception as blad:
                logger.warning("Telegram %s, próba %d: %s", metoda, proba + 1, blad)
                time.sleep(2 * (proba + 1))
        return None

    # ── Wiadomości ───────────────────────────────────────────────────────────

    def wyslij(self, tekst: str, podglad_linkow: bool = False) -> bool:
        """Wysyła tekst, dzieląc go na kawałki gdy przekracza limit."""
        wyslano_wszystko = True
        for kawalek in self._podziel(tekst, LIMIT_WIADOMOSCI):
            wynik = self._wywolaj("sendMessage", {
                "chat_id": self.chat_id,
                "text": kawalek,
                "parse_mode": "HTML",
                "disable_web_page_preview": not podglad_linkow,
            })
            wyslano_wszystko &= wynik is not None
            time.sleep(0.4)
        return wyslano_wszystko

    def wyslij_zdjecie(self, foto_url: str, podpis: str,
                       przycisk_url: str = "", przycisk_tekst: str = "🛒 Otwórz na AliExpress") -> bool:
        """
        Karta oferty: zdjęcie + opis + przycisk z linkiem.

        Gdy zdjęcia nie da się pobrać (a AliExpress potrafi podać martwy URL),
        schodzimy na zwykłą wiadomość — lepiej oferta bez obrazka niż dziura
        w raporcie.
        """
        podpis = self._utnij(podpis, LIMIT_PODPISU)
        dane = {
            "chat_id": self.chat_id,
            "photo": foto_url,
            "caption": podpis,
            "parse_mode": "HTML",
        }
        if przycisk_url:
            dane["reply_markup"] = {
                "inline_keyboard": [[{"text": przycisk_tekst, "url": przycisk_url}]]
            }

        if foto_url and self._wywolaj("sendPhoto", dane) is not None:
            return True

        logger.info("Zdjęcie nie przeszło, wysyłam sam tekst")
        zapasowe = {
            "chat_id": self.chat_id,
            "text": podpis,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if przycisk_url:
            zapasowe["reply_markup"] = dane["reply_markup"]
        return self._wywolaj("sendMessage", zapasowe) is not None

    def odczekaj(self) -> None:
        """Przerwa między kartami ofert, żeby nie wpaść w limit Telegrama."""
        time.sleep(PRZERWA_S)

    def test(self) -> bool:
        """Sprawdza token i chat ID bez wysyłania raportu."""
        ja = self._wywolaj("getMe", {})
        if not ja:
            print("❌ Token odrzucony przez Telegram.")
            return False
        print(f"✅ Bot: @{ja.get('username')} ({ja.get('first_name')})")
        if self.wyslij("🧪 <b>Test połączenia</b>\nSkaner filamentu AliExpress melduje się."):
            print(f"✅ Wiadomość testowa dostarczona na chat {self.chat_id}")
            return True
        print(f"❌ Nie udało się wysłać na chat {self.chat_id} — sprawdź ID "
              f"i czy bot został dodany do grupy.")
        return False

    # ── Pomocnicze ───────────────────────────────────────────────────────────

    @staticmethod
    def _podziel(tekst: str, limit: int) -> list[str]:
        """Dzieli po liniach, żeby nie rozciąć znacznika HTML w pół."""
        kawalki = []
        while len(tekst) > limit:
            ciecie = tekst.rfind("\n", 0, limit)
            if ciecie == -1:
                ciecie = limit
            kawalki.append(tekst[:ciecie])
            tekst = tekst[ciecie:].lstrip("\n")
        if tekst:
            kawalki.append(tekst)
        return kawalki

    @staticmethod
    def _utnij(tekst: str, limit: int) -> str:
        if len(tekst) <= limit:
            return tekst
        ciecie = tekst.rfind("\n", 0, limit - 1)
        return tekst[:ciecie if ciecie > 0 else limit - 1] + "…"
