#!/bin/bash
# ============================================================
#  ali.sh — sterowanie skanerem na serwerze TESTOWYM (bez roota)
#
#  Na RPi5 tę rolę pełni systemd. Tutaj roota nie ma, więc bot chodzi
#  jako proces odpięty od sesji SSH, a harmonogram obsługuje cron
#  użytkownika. Zachowanie jest takie samo: cron budzi skaner co 15 minut,
#  a o porze decyduje alifilament/harmonogram.py.
#
#      ./ali.sh zainstaluj | start | stop | restart | status | skan | logi | odinstaluj
# ============================================================

BAZA="$HOME/ali-filament"
LOGI="$BAZA/logi"
PY="$BAZA/venv/bin/python"

mkdir -p "$LOGI"

# Chromium leży rozpakowany lokalnie (apt-get download + dpkg -x, bez roota).
export LD_LIBRARY_PATH="$BAZA/syslibs/usr/lib/x86_64-linux-gnu"
export ALIFILAMENT_DATA_DIR="$BAZA/dane"

cd "$BAZA" || { echo "Brak katalogu $BAZA"; exit 1; }

pid_bota() { pgrep -f "alifilament\.bot" | head -1; }

start_bota() {
    if [ -n "$(pid_bota)" ]; then
        echo "Bot już działa (PID $(pid_bota))"
        return 0
    fi
    # setsid odpina proces od sesji SSH, żeby przeżył rozłączenie.
    setsid nohup "$PY" -m alifilament.bot >> "$LOGI/bot.log" 2>&1 < /dev/null &
    sleep 3
    if [ -n "$(pid_bota)" ]; then
        echo "Bot wystartował (PID $(pid_bota))"
    else
        echo "Bot NIE wystartował — zajrzyj do $LOGI/bot.log"
        return 1
    fi
}

stop_bota() {
    local p
    p="$(pid_bota)"
    if [ -z "$p" ]; then
        echo "Bot nie działa"
        return 0
    fi

    kill "$p" 2>/dev/null
    # Czekamy, aż proces NAPRAWDĘ zniknie. Bez tego "restart" tylko udaje:
    # start widzi jeszcze żywy proces, melduje "już działa" i bot zostaje
    # na starym kodzie.
    local i
    for i in $(seq 1 20); do
        [ -z "$(pid_bota)" ] && break
        sleep 0.5
    done

    if [ -n "$(pid_bota)" ]; then
        echo "Bot nie zareagował na SIGTERM — ubijam na twardo"
        kill -9 "$(pid_bota)" 2>/dev/null
        sleep 1
    fi
    echo "Zatrzymano bota (PID $p)"
}

case "${1:-status}" in
    start)   start_bota ;;
    stop)    stop_bota ;;
    restart) stop_bota; start_bota ;;

    # Wywoływane z crona co 5 minut — podnosi bota, gdyby padł.
    pilnuj)
        [ -z "$(pid_bota)" ] && start_bota >> "$LOGI/bot.log" 2>&1
        ;;

    # Wywoływane z crona co 15 minut. Bez --force, więc harmonogram decyduje.
    cron-skan)
        "$PY" -m alifilament.scan >> "$LOGI/skan.log" 2>&1
        ;;

    # Ręczny skan na żądanie — omija harmonogram.
    skan)
        echo "Skanuję (2–3 minuty)…"
        "$PY" -m alifilament.scan --force 2>&1 | tail -6
        ;;

    status)
        p="$(pid_bota)"
        if [ -n "$p" ]; then echo "Bot        : działa (PID $p)"; else echo "Bot        : NIE działa"; fi
        echo "Cron       : $(crontab -l 2>/dev/null | grep -c alifilament) wpisów"
        "$PY" - <<'PYEOF'
from datetime import datetime
from alifilament import config as k, harmonogram
from alifilament.store import Store
cfg = k.wczytaj()
s = Store(cfg.baza)
godziny = s.godziny(cfg.godziny)
r = s.ostatni_skan()
print("Powiadomienia:", "włączone" if s.powiadomienia_wlaczone() else "WSTRZYMANE (/start wznawia)")
print("Godziny     :", ", ".join(godziny))
print("Ofert w raporcie:", s.ile_ofert_w_raporcie(cfg.top_n))
print("Ostatni skan:", r["ts"][:19].replace("T", " ") if r else "brak")
n = harmonogram.nastepny_przebieg(godziny)
print("Następny    :", n.strftime("%d.%m %H:%M") if n else "brak")
print("Produktów w bazie:", s.ile_ofert())
s.zamknij()
PYEOF
        ;;

    logi)
        echo "── bot.log (20 ostatnich) ──"
        tail -20 "$LOGI/bot.log" 2>/dev/null || echo "(pusto)"
        echo ""
        echo "── skan.log (25 ostatnich) ──"
        tail -25 "$LOGI/skan.log" 2>/dev/null || echo "(pusto)"
        ;;

    zainstaluj)
        # Dopisujemy zachowując cudze wpisy (qlds-ctl serwera Quake Live).
        ( crontab -l 2>/dev/null | grep -v "alifilament"
          echo "*/15 * * * * $BAZA/ali.sh cron-skan # alifilament-skan"
          echo "*/5 * * * * $BAZA/ali.sh pilnuj # alifilament-bot-watchdog"
          echo "@reboot $BAZA/ali.sh start # alifilament-bot-reboot"
        ) | crontab -
        echo "Wpisy crona dodane:"
        crontab -l | grep alifilament | sed 's/^/  /'
        start_bota
        ;;

    odinstaluj)
        stop_bota
        crontab -l 2>/dev/null | grep -v "alifilament" | crontab -
        echo "Usunięto wpisy crona skanera (wpisy qlds nietknięte)."
        echo "Przywrócisz je przez: ./ali.sh zainstaluj"
        echo "Pliki i baza zostają w $BAZA — skasuj ręcznie, jeśli chcesz."
        ;;

    *)
        echo "Użycie: ./ali.sh {zainstaluj|start|stop|restart|status|skan|logi|odinstaluj}"
        exit 1
        ;;
esac
