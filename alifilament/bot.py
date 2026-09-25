#!/usr/bin/env python3
"""
Bot interaktywny — lekka usługa działająca ciągle.

Świadomie nie skanuje we własnym procesie: sam skan odpala jako osobny proces
(to samo, co robi timer), więc zawieszony albo ubity Chromium nie kładzie bota.

    python -m alifilament.bot
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from telegram import BotCommand, Update
from telegram.error import Conflict
from telegram.ext import Application, CommandHandler, ContextTypes

from . import config as konfiguracja
from . import harmonogram
from . import report
from .filters import (OPISY_TRYBU, filtruj_wysylke, porownanie_wysylki,
                      posortuj_i_utnij, rozpoznaj_tryb)
from .notifier import esc
from .store import Store

logger = logging.getLogger("alifilament.bot")

WERSJA = "1.0.0"
KATALOG_PROJEKTU = Path(__file__).resolve().parent.parent

cfg = konfiguracja.wczytaj()

# Potwierdzenia ręcznego skanu — ten sam wzorzec dwukrotnej komendy w 30 s,
# co /rpi5_reboot w bocie RPi5.
_oczekuje_skan: dict[int, datetime] = {}


def uprawniony(update: Update) -> bool:
    if not cfg.allowed_ids:
        return True
    uzytkownik = update.effective_user.id if update.effective_user else None
    czat = update.effective_chat.id if update.effective_chat else None
    return uzytkownik in cfg.allowed_ids or czat in cfg.allowed_ids


async def wyslij_stronicowane(wiadomosc, tekst: str) -> None:
    """Dzieli długi tekst na wiadomości mieszczące się w limicie Telegrama."""
    limit = 3800
    while len(tekst) > limit:
        ciecie = tekst.rfind("\n", 0, limit)
        if ciecie == -1:
            ciecie = limit
        await wiadomosc.reply_text(tekst[:ciecie], parse_mode="HTML",
                                   disable_web_page_preview=True)
        tekst = tekst[ciecie:].lstrip("\n")
    if tekst:
        await wiadomosc.reply_text(tekst, parse_mode="HTML",
                                   disable_web_page_preview=True)


def otworz_baze() -> Store:
    return Store(cfg.baza)


# ── Komendy ──────────────────────────────────────────────────────────────────

def _tekst_pomocy(godziny: list[str], wlaczone: bool) -> str:
    stan = "✅ włączone" if wlaczone else "⏸️ wstrzymane komendą /stop"
    return (
        "🧵 <b>Skaner filamentu AliExpress</b>\n"
        f"<i>wersja {WERSJA}</i>\n\n"
        f"Powiadomienia: <b>{stan}</b>\n"
        f"Godziny raportów: <b>{', '.join(godziny) or 'brak'}</b>\n\n"
        "<b>── Powiadomienia ──</b>\n"
        "  /start           — wznów wysyłanie raportów\n"
        "  /stop            — wstrzymaj wysyłanie\n"
        "  /godziny         — pokaż ustawione pory\n"
        "  /godziny 8 13 20 — ustaw własne (także 7:30, 21:45)\n"
        "  /ile 20          — ile ofert ma być w raporcie\n\n"
        "<b>── Oferty ──</b>\n"
        "  /top [n]         — najlepsze oferty z ostatniego skanu\n"
        "  /kody            — aktualne kody rabatowe\n"
        "  /skanuj          — wymuś skan teraz (działa też przy /stop)\n"
        "  /historia &lt;id&gt;   — historia ceny produktu\n\n"
        "<b>── Wysyłka ──</b>\n"
        "  /szukaj bezplatne — tylko z darmową dostawą\n"
        "  /szukaj platne    — tylko z płatną dostawą\n"
        "  /szukaj wszystkie — jedno i drugie\n"
        "  /porownaj        — co wychodzi taniej: płatna czy darmowa\n"
        "  <i>zawsze wyłącznie magazyny w UE</i>\n\n"
        "<b>── Informacje ──</b>\n"
        "  /filtry          — czego szukam i skąd\n"
        "  /status          — stan skanera i harmonogramu\n"
        "  /help            — ta wiadomość\n\n"
        "<i>Zamienniki nazw: /pomoc = /help, /pauza = /stop, "
        "/liczba = /ile, /harmonogram = /godziny, /kupony = /kody.</i>"
    )


# Menu podpowiadane przez Telegram po wpisaniu "/" w oknie czatu.
KOMENDY_MENU = [
    ("start", "Wznów wysyłanie raportów"),
    ("stop", "Wstrzymaj wysyłanie raportów"),
    ("godziny", "Pokaż lub ustaw pory raportów"),
    ("ile", "Ile ofert ma zawierać raport"),
    ("top", "Najlepsze oferty z ostatniego skanu"),
    ("szukaj", "Filtruj po wysyłce: platne / bezplatne / wszystkie"),
    ("porownaj", "Co wychodzi taniej: płatna czy darmowa wysyłka"),
    ("kody", "Aktualne kody rabatowe"),
    ("skanuj", "Wymuś skan teraz"),
    ("historia", "Historia ceny produktu"),
    ("filtry", "Czego szukam i skąd"),
    ("status", "Stan skanera i harmonogramu"),
    ("help", "Lista wszystkich komend"),
]


async def po_starcie(app: Application) -> None:
    """
    Rejestruje menu komend w Telegramie.

    Dzięki temu po wpisaniu "/" czat sam podpowiada listę — nie trzeba
    pamiętać nazw ani wywoływać /help.
    """
    try:
        await app.bot.set_my_commands(
            [BotCommand(nazwa, opis) for nazwa, opis in KOMENDY_MENU])
        logger.info("Menu komend zarejestrowane (%d pozycji)", len(KOMENDY_MENU))
    except Exception as blad:
        # Menu to wygoda, nie warunek działania bota.
        logger.warning("Nie udało się ustawić menu komend: %s", blad)


async def obsluz_blad(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Zamienia stos wywołań w zdanie, które coś mówi.

    Bez zarejestrowanego handlera biblioteka wypisuje do logu 25 linii
    tracebacku — a w praktyce niemal zawsze chodzi o jedną z dwóch rzeczy,
    i obie da się opisać jednym zdaniem.
    """
    blad = ctx.error
    if isinstance(blad, Conflict):
        logger.error(
            "Inna instancja bota odbiera wiadomości z tym samym tokenem — "
            "ta się wyłącza. Telegram pozwala na tylko jedną naraz. "
            "Sprawdź: systemctl status alifilament-bot  oraz  pgrep -af alifilament.bot"
        )
        return
    logger.error("Błąd bota: %s: %s", type(blad).__name__, blad)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/start wznawia wysyłkę — to odwrotność /stop, nie tylko powitanie."""
    magazyn = otworz_baze()
    try:
        bylo_wlaczone = magazyn.powiadomienia_wlaczone()
        magazyn.ustaw_powiadomienia(True)
        godziny = magazyn.godziny(cfg.godziny)
    finally:
        magazyn.zamknij()

    naglowek = ("▶️ <b>Wznowiono wysyłanie raportów.</b>\n\n" if not bylo_wlaczone else "")
    await update.message.reply_text(naglowek + _tekst_pomocy(godziny, True),
                                    parse_mode="HTML")


async def cmd_pomoc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    magazyn = otworz_baze()
    try:
        await update.message.reply_text(
            _tekst_pomocy(magazyn.godziny(cfg.godziny), magazyn.powiadomienia_wlaczone()),
            parse_mode="HTML")
    finally:
        magazyn.zamknij()


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Wstrzymuje raporty z harmonogramu. Skaner nawet nie ruszy przeglądarki."""
    if not uprawniony(update):
        await update.message.reply_text("🚫 Brak uprawnień.")
        return

    magazyn = otworz_baze()
    try:
        magazyn.ustaw_powiadomienia(False)
    finally:
        magazyn.zamknij()

    await update.message.reply_text(
        "⏸️ <b>Wysyłanie wstrzymane.</b>\n\n"
        "Zaplanowane skany nie będą się odbywać ani nic wysyłać.\n"
        "Wznowisz komendą <code>/start</code>, a jednorazowy raport "
        "zamówisz przez <code>/skanuj</code> — ten działa mimo wstrzymania.",
        parse_mode="HTML")


async def cmd_godziny(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/godziny — pokaż; /godziny 8 13 20 — ustaw."""
    if ctx.args and not uprawniony(update):
        await update.message.reply_text("🚫 Brak uprawnień do zmiany harmonogramu.")
        return

    magazyn = otworz_baze()
    try:
        if not ctx.args:
            godziny = magazyn.godziny(cfg.godziny)
            nastepny = harmonogram.nastepny_przebieg(godziny)
            await update.message.reply_text(
                "🕑 <b>Godziny raportów</b>\n\n"
                f"Ustawione: <b>{', '.join(godziny) or 'brak'}</b>\n"
                + (f"Najbliższy: <b>{nastepny.strftime('%d.%m o %H:%M')}</b>\n"
                   if nastepny else "")
                + "\nZmiana: <code>/godziny 8 13 20</code>\n"
                "Minuty też można: <code>/godziny 7:30 12:00 21:45</code>",
                parse_mode="HTML")
            return

        godziny, odrzucone = harmonogram.parsuj_godziny(ctx.args)
        if odrzucone:
            await update.message.reply_text(
                f"❌ Nie rozumiem: <code>{esc(', '.join(odrzucone))}</code>\n\n"
                "Godzinę podaje się jako <code>8</code>, <code>08:00</code> "
                "albo <code>21:45</code>.",
                parse_mode="HTML")
            return
        if not godziny:
            await update.message.reply_text(
                "❌ Podaj co najmniej jedną godzinę, np. <code>/godziny 8 13 20</code>",
                parse_mode="HTML")
            return

        magazyn.ustaw_godziny(godziny)
        nastepny = harmonogram.nastepny_przebieg(godziny)
    finally:
        magazyn.zamknij()

    await update.message.reply_text(
        "✅ <b>Nowy harmonogram zapisany</b>\n\n"
        f"Raporty o: <b>{', '.join(godziny)}</b>\n"
        + (f"Najbliższy: <b>{nastepny.strftime('%d.%m o %H:%M')}</b>\n" if nastepny else "")
        + "\n<i>Zmiana działa od razu — nie trzeba niczego restartować.</i>",
        parse_mode="HTML")


MAX_OFERT_W_RAPORCIE = 30


async def cmd_ile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/ile — pokaż; /ile 20 — ustaw liczbę ofert w raporcie."""
    if ctx.args and not uprawniony(update):
        await update.message.reply_text("🚫 Brak uprawnień do zmiany ustawień.")
        return

    magazyn = otworz_baze()
    try:
        obecnie = magazyn.ile_ofert_w_raporcie(cfg.top_n)

        if not ctx.args:
            await update.message.reply_text(
                "🔢 <b>Liczba ofert w raporcie</b>\n\n"
                f"Teraz pokazuję: <b>{obecnie}</b>\n\n"
                f"Zmiana: <code>/ile 20</code> (od 1 do {MAX_OFERT_W_RAPORCIE})",
                parse_mode="HTML")
            return

        podane = ctx.args[0]
        if not podane.isdigit():
            await update.message.reply_text(
                f"❌ Podaj liczbę, np. <code>/ile 20</code>", parse_mode="HTML")
            return

        ile = int(podane)
        if not 1 <= ile <= MAX_OFERT_W_RAPORCIE:
            # Górny limit nie jest kaprysem: każda oferta to osobna wiadomość
            # ze zdjęciem, a Telegram przepuszcza ich około 20 na minutę.
            await update.message.reply_text(
                f"❌ Liczba musi mieścić się w zakresie 1–{MAX_OFERT_W_RAPORCIE}.\n"
                "<i>Każda oferta to osobna wiadomość ze zdjęciem, a Telegram "
                "ogranicza tempo wysyłki.</i>",
                parse_mode="HTML")
            return

        magazyn.ustaw_ile_ofert(ile)
    finally:
        magazyn.zamknij()

    await update.message.reply_text(
        f"✅ <b>Od teraz w raporcie: {ile} ofert</b>\n\n"
        f"<i>Zmiana obowiązuje od najbliższego raportu — "
        f"wysyłka potrwa około {max(1, round(ile * 1.2 / 60))} min.</i>",
        parse_mode="HTML")


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Zestawienie z ostatniego skanu — bez ponownego scrapowania."""
    ile = 10
    if ctx.args and ctx.args[0].isdigit():
        ile = max(1, min(int(ctx.args[0]), 30))

    magazyn = otworz_baze()
    try:
        oferty = magazyn.oferty_z_ostatniego_skanu()[:ile]
        wiersz_skanu = magazyn.ostatni_skan()
    finally:
        magazyn.zamknij()

    if not oferty:
        await update.message.reply_text(
            "📭 Brak danych z ostatniego skanu.\nUżyj <code>/skanuj</code>.",
            parse_mode="HTML")
        return

    naglowek = (f"🏆 <b>TOP {len(oferty)}</b> "
                f"<i>(wszystkie tryby wysyłki · skan z {_wiek_skanu(wiersz_skanu)})</i>")
    await wyslij_stronicowane(update.message, report.lista_zwiezla(oferty, naglowek))


def _wiek_skanu(wiersz) -> str:
    return wiersz["ts"][:16].replace("T", " ") if wiersz else "?"


async def cmd_szukaj(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /szukaj platne | bezplatne | wszystkie

    Czyta ostatni skan, nie odpytuje AliExpressu — skan zbiera obie grupy
    wysyłki naraz, więc przełączenie widoku jest natychmiastowe.
    """
    magazyn = otworz_baze()
    try:
        wszystkie = magazyn.oferty_z_ostatniego_skanu()
        wiersz = magazyn.ostatni_skan()
        limit = magazyn.ile_ofert_w_raporcie(cfg.top_n)
    finally:
        magazyn.zamknij()

    if not wszystkie:
        await update.message.reply_text(
            "📭 Brak danych z ostatniego skanu.\nUżyj <code>/skanuj</code>.",
            parse_mode="HTML")
        return

    ile_darmowych = sum(1 for o in wszystkie if o.darmowa_wysylka)

    if not ctx.args:
        await update.message.reply_text(
            "🔍 <b>Szukanie w ostatnim skanie</b>\n\n"
            f"<code>/szukaj bezplatne</code> — z darmową wysyłką "
            f"({ile_darmowych})\n"
            f"<code>/szukaj platne</code> — z płatną wysyłką "
            f"({len(wszystkie) - ile_darmowych})\n"
            f"<code>/szukaj wszystkie</code> — jedno i drugie "
            f"({len(wszystkie)})\n\n"
            "Zawsze tylko magazyny w UE.\n"
            "Co wychodzi taniej: <code>/porownaj</code>",
            parse_mode="HTML")
        return

    tryb = rozpoznaj_tryb(ctx.args[0])
    if tryb is None:
        await update.message.reply_text(
            f"❌ Nie znam trybu <code>{esc(ctx.args[0])}</code>.\n\n"
            "Dostępne: <code>platne</code>, <code>bezplatne</code>, "
            "<code>wszystkie</code>",
            parse_mode="HTML")
        return

    wybrane = posortuj_i_utnij(filtruj_wysylke(wszystkie, tryb), limit)
    if not wybrane:
        await update.message.reply_text(
            f"📭 W ostatnim skanie nie ma ofert {OPISY_TRYBU[tryb]}.",
            parse_mode="HTML")
        return

    naglowek = (f"🔍 <b>Filament {OPISY_TRYBU[tryb]}</b>\n"
                f"<i>{len(wybrane)} z {len(filtruj_wysylke(wszystkie, tryb))} "
                f"· magazyny UE · skan z {_wiek_skanu(wiersz)}</i>")
    await wyslij_stronicowane(update.message,
                              report.lista_zwiezla(wybrane, naglowek))


async def cmd_porownaj(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Czy oferta z płatną wysyłką wychodzi taniej od darmowej."""
    magazyn = otworz_baze()
    try:
        wszystkie = magazyn.oferty_z_ostatniego_skanu()
        wiersz = magazyn.ostatni_skan()
    finally:
        magazyn.zamknij()

    if not wszystkie:
        await update.message.reply_text(
            "📭 Brak danych z ostatniego skanu.\nUżyj <code>/skanuj</code>.",
            parse_mode="HTML")
        return

    tekst = report.sekcja_porownania(porownanie_wysylki(wszystkie))
    tekst += f"\n<i>Dane ze skanu z {_wiek_skanu(wiersz)}.</i>"
    await wyslij_stronicowane(update.message, tekst)


async def cmd_kody(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    magazyn = otworz_baze()
    try:
        kupony = magazyn.kupony_z_ostatniej_doby()
    finally:
        magazyn.zamknij()
    await wyslij_stronicowane(update.message, report.sekcja_kuponow(kupony))


async def cmd_filtry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Czytamy plik na świeżo, a nie z pamięci z chwili startu. Skan i tak
    # wczytuje go przy każdym przebiegu, więc bez tego /filtry pokazywałoby
    # nieaktualny stan po każdej ręcznej edycji config.yaml.
    biezaca = konfiguracja.wczytaj()

    prog = (f"{report.zl(biezaca.alert_zl_za_kg)}/kg"
            if biezaca.alert_zl_za_kg else "wyłączony")
    zrodlo = getattr(biezaca, "zrodlo_yaml", "(wbudowana konfiguracja)")

    magazyn = otworz_baze()
    try:
        ile_ofert = magazyn.ile_ofert_w_raporcie(biezaca.top_n)
        godziny = magazyn.godziny(biezaca.godziny)
    finally:
        magazyn.zamknij()

    await update.message.reply_text(
        "🔎 <b>Ustawienia wyszukiwania</b>\n\n"
        f"<b>Marki:</b> {', '.join(m.upper() for m in biezaca.marki)}\n"
        f"<b>Materiały:</b> {', '.join(biezaca.materialy)}\n"
        f"<b>Magazyny:</b> {', '.join(biezaca.magazyny_eu)}\n"
        f"<b>Wysyłka do:</b> {biezaca.wysylka_do} · <b>waluta:</b> {biezaca.waluta}\n"
        f"<b>Zapytań na przebieg:</b> {len(biezaca.lista_zapytan())}"
        f" × {len(biezaca.kraje_do_przeszukania())} magazyn(y)\n"
        f"<b>Pokazuję:</b> TOP {ile_ofert}  <i>(zmiana: /ile)</i>\n"
        f"<b>Wysyłka w raportach:</b> {OPISY_TRYBU.get(biezaca.tryb_wysylki, biezaca.tryb_wysylki)}"
        f"  <i>(inne tryby: /szukaj)</i>\n"
        f"<b>Próg 🔥:</b> {prog}\n"
        f"<b>Godziny:</b> {', '.join(godziny)}  <i>(zmiana: /godziny)</i>\n\n"
        f"<i>Konfiguracja: {esc(str(zrodlo))}</i>\n"
        f"<i>Odczytana przed chwilą — zmiany w tym pliku widać bez restartu.</i>",
        parse_mode="HTML",
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    magazyn = otworz_baze()
    try:
        wiersz = magazyn.ostatni_skan()
        w_bazie = magazyn.ile_ofert()
        wlaczone = magazyn.powiadomienia_wlaczone()
        godziny = magazyn.godziny(cfg.godziny)
    finally:
        magazyn.zamknij()

    linie = ["📊 <b>Status skanera</b>", ""]
    if wlaczone:
        nastepny = harmonogram.nastepny_przebieg(godziny)
        linie.append("▶️ Powiadomienia: <b>włączone</b>")
        linie.append(f"🕑 Godziny: <b>{', '.join(godziny) or 'brak'}</b>")
        if nastepny:
            linie.append(f"⏭️ Najbliższy raport: <b>{nastepny.strftime('%d.%m o %H:%M')}</b>")
    else:
        linie.append("⏸️ Powiadomienia: <b>wstrzymane</b> (<code>/start</code> wznawia)")
    linie.append("")

    if wiersz:
        linie += [
            f"🕑 Ostatni skan: <b>{wiersz['ts'][:16].replace('T', ' ')}</b>",
            f"🔎 Zapytań: {wiersz['zapytan']} · surowych ofert: {wiersz['surowych']}",
            f"✅ Po filtrach: {wiersz['po_filtrach']} "
            f"(🆕 {wiersz['nowych']} · 🔻 {wiersz['tanszych']})",
        ]
        if wiersz["zablokowany"]:
            linie.append("🚫 <b>Ostatni skan przerwany przez blokadę AliExpress</b>")
    else:
        linie.append("<i>Nie wykonano jeszcze żadnego skanu.</i>")

    linie.append(f"🗄️ Produktów w bazie: <b>{w_bazie}</b>")

    # Harmonogram — gdy bot chodzi poza systemd, po prostu tego nie pokażemy.
    try:
        wynik = subprocess.run(
            ["systemctl", "list-timers", "alifilament-scan.timer", "--no-pager"],
            capture_output=True, text=True, timeout=5)
        for linia in wynik.stdout.splitlines():
            if "alifilament" in linia:
                linie.append(f"\n⏭️ Następny przebieg:\n<code>{esc(linia.strip())}</code>")
                break
    except Exception:
        pass

    await update.message.reply_text("\n".join(linie), parse_mode="HTML")


async def cmd_historia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "❌ Użycie: <code>/historia &lt;id produktu&gt;</code>\n"
            "<i>ID znajdziesz w linku oferty: .../item/<b>1005006…</b>.html</i>",
            parse_mode="HTML")
        return

    magazyn = otworz_baze()
    try:
        wiersz = magazyn.znajdz_oferte(ctx.args[0])
        if not wiersz:
            await update.message.reply_text(
                f"❌ Nie mam w bazie produktu <code>{esc(ctx.args[0])}</code>.",
                parse_mode="HTML")
            return
        punkty = magazyn.historia_cen(wiersz["product_id"])
    finally:
        magazyn.zamknij()

    if len(punkty) < 2:
        await update.message.reply_text(
            f"📈 <b>{esc(wiersz['tytul'][:60])}</b>\n\n"
            f"Tylko jeden pomiar: <b>{report.zl(punkty[0][1]) if punkty else '—'}</b>\n"
            "<i>Historia powstaje z kolejnych przebiegów.</i>",
            parse_mode="HTML")
        return

    ceny = [c for _ts, c in punkty]
    lo, hi = min(ceny), max(ceny)
    rozpietosc = hi - lo or 1.0
    slupki = "▁▂▃▄▅▆▇█"

    wykres = "".join(slupki[min(int((c - lo) / rozpietosc * (len(slupki) - 1)), len(slupki) - 1)]
                     for c in ceny[-40:])

    zmiana = ceny[-1] - ceny[0]
    strzalka = "▲" if zmiana > 0 else ("▼" if zmiana < 0 else "→")

    await update.message.reply_text(
        f"📈 <b>{esc(wiersz['tytul'][:60])}</b>\n\n"
        f"<code>{wykres}</code>\n\n"
        f"Teraz: <b>{report.zl(ceny[-1])}</b>\n"
        f"Min: {report.zl(lo)} · Max: {report.zl(hi)}\n"
        f"Zmiana od pierwszego pomiaru: {strzalka} {report.zl(abs(zmiana))}\n"
        f"<i>Pomiarów: {len(ceny)} · od {punkty[0][0][:10]}</i>",
        parse_mode="HTML",
    )


async def cmd_skanuj(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ręczny przebieg — z potwierdzeniem, bo trwa kilka minut i budzi Chromium."""
    if not uprawniony(update):
        await update.message.reply_text("🚫 Brak uprawnień.")
        return

    uid = update.effective_user.id
    teraz = datetime.now()

    if uid in _oczekuje_skan and (teraz - _oczekuje_skan.pop(uid)).total_seconds() < 30:
        await update.message.reply_text(
            "⏳ <b>Startuję skan…</b>\nRaport przyjdzie za kilka minut.",
            parse_mode="HTML")
        subprocess.Popen(
            [sys.executable, "-m", "alifilament.scan", "--force"],
            cwd=str(KATALOG_PROJEKTU),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("Ręczny skan uruchomiony przez %s", uid)
        return

    _oczekuje_skan[uid] = teraz
    liczba_zapytan = len(cfg.lista_zapytan()) * len(cfg.kraje_do_przeszukania())
    await update.message.reply_text(
        f"🔄 <b>Ręczny skan</b>\n\n"
        f"Do wykonania: <b>{liczba_zapytan}</b> zapytań, to potrwa kilka minut.\n\n"
        "Wyślij <code>/skanuj</code> jeszcze raz w ciągu <b>30 sekund</b>, aby potwierdzić.",
        parse_mode="HTML")


def main() -> int:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
        stream=sys.stdout,
    )
    # Token bota jest częścią adresu Bot API, a httpx loguje adresy na INFO —
    # bez tego każde odpytanie Telegrama zapisywałoby sekret do journala.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    if not cfg.token:
        logger.error("Brak TELEGRAM_BOT_TOKEN — nie mam czym się zalogować.")
        return 1

    app = Application.builder().token(cfg.token).post_init(po_starcie).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["stop", "pauza"], cmd_stop))
    app.add_handler(CommandHandler(["pomoc", "help"], cmd_pomoc))
    app.add_handler(CommandHandler(["godziny", "harmonogram"], cmd_godziny))
    app.add_handler(CommandHandler(["ile", "liczba"], cmd_ile))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler(["kody", "kupony"], cmd_kody))
    app.add_handler(CommandHandler(["szukaj", "search"], cmd_szukaj))
    # Nazwa komendy Telegrama moze zawierac tylko a-z, 0-9 i podkreslnik -
    # dlatego bez "porównaj" z ogonkiem.
    app.add_handler(CommandHandler(["porownaj", "porownanie"], cmd_porownaj))
    app.add_handler(CommandHandler("filtry", cmd_filtry))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("historia", cmd_historia))
    app.add_handler(CommandHandler("skanuj", cmd_skanuj))
    app.add_error_handler(obsluz_blad)

    logger.info("Bot gotowy, czekam na komendy…")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Conflict:
        # Telegram pozwala odbierać wiadomości tylko jednej instancji na token.
        # Bez tego komunikatu do logu leci 25 linii stosu zamiast wyjaśnienia.
        logger.error(
            "Inna instancja bota już odbiera wiadomości z tym tokenem. "
            "Zatrzymuję się, żeby nie odbijać się z nią nawzajem. "
            "Sprawdź: systemctl status alifilament-bot  oraz  pgrep -af alifilament.bot"
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
