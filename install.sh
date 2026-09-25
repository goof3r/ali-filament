#!/bin/bash
# ============================================================
#  install.sh — Skaner filamentu AliExpress -> Telegram
#  Debian 12 / Ubuntu / OpenMediaVault, x86_64 i arm64 (RPi5)
#  Uruchom jako root: sudo bash install.sh
# ============================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[[ "$EUID" -ne 0 ]] && die "Uruchom skrypt jako root (sudo bash install.sh)"

# Tryb bezobsługowy: install-rpi5.sh ustawia ALIFILAMENT_AUTO=1 i podaje dane
# przez zmienne, więc instalator nie zadaje żadnych pytań.
AUTO="${ALIFILAMENT_AUTO:-0}"

# pytaj "treść pytania" "odpowiedź domyślna"
pytaj() {
    if [[ "$AUTO" == "1" ]]; then
        echo "$2"
    else
        local odp
        read -rp "$1" odp
        echo "${odp:-$2}"
    fi
}

INSTALL_DIR="/opt/ali-filament"
ENV_FILE="/etc/alifilament.env"
CONFIG_DIR="/etc/alifilament"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
DATA_DIR="/var/lib/ali-filament"
SERVICE_USER="alifilament"
ADMIN_GROUP="alifilament-admin"
ZRODLO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   Skaner filamentu 3D z AliExpress -> Telegram   ║"
echo "  ║   JAYO · SUNLU · KINGROON, magazyny UE           ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

# ── Krok 1: Konfiguracja ──────────────────────────────────────
echo -e "${CYAN}Konfiguracja:${NC}"
echo ""

if [[ -f "$ENV_FILE" && -z "${BOT_TOKEN:-}" ]]; then
    warn "Znaleziono istniejącą konfigurację: $ENV_FILE"
    use_existing=$(pytaj "  Użyć istniejącej? [T/n]: " "t")
    if [[ "${use_existing,,}" != "n" ]]; then
        _grep_env() { grep -m1 "^$1=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"'; }
        BOT_TOKEN=$(_grep_env TELEGRAM_BOT_TOKEN)
        CHAT_ID=$(_grep_env TELEGRAM_CHAT_ID)
        ok "Wczytano istniejącą konfigurację"
    fi
fi

if [[ -z "${BOT_TOKEN:-}" ]]; then
    echo "  Token nowego bota weź od @BotFather (/newbot)."
    read -rp "  TOKEN bota Telegram: " BOT_TOKEN
    [[ -z "$BOT_TOKEN" ]] && die "Token nie może być pusty!"
fi
if [[ -z "${CHAT_ID:-}" ]]; then
    echo "  CHAT_ID grupy zaczyna się od minusa, np. -1001234567890."
    read -rp "  CHAT_ID docelowy: " CHAT_ID
    [[ -z "$CHAT_ID" ]] && die "Chat ID nie może być pusty!"
fi

# ── Krok 2: Pakiety systemowe ─────────────────────────────────
echo ""
info "Instaluję pakiety systemowe…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip ca-certificates >/dev/null
ok "Pakiety bazowe gotowe"

ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
info "Architektura: $ARCH"

CHROMIUM_PATH=""
if [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" || "$ARCH" == "armhf" ]]; then
    # Playwright nie ma pewnych buildów Chromium dla Debiana na ARM,
    # więc na RPi5 korzystamy z Chromium z repozytorium systemowego.
    info "ARM — instaluję systemowy Chromium (Playwright nie ma tu własnych buildów)"
    apt-get install -y -qq chromium fonts-liberation >/dev/null 2>&1 \
        || apt-get install -y -qq chromium-browser fonts-liberation >/dev/null 2>&1 \
        || die "Nie udało się zainstalować Chromium. Zainstaluj ręcznie: apt install chromium"
    CHROMIUM_PATH="$(command -v chromium || command -v chromium-browser || true)"
    [[ -z "$CHROMIUM_PATH" ]] && die "Chromium zainstalowany, ale nie znalazłem binarki."
    ok "Chromium systemowy: $CHROMIUM_PATH"
fi

# ── Krok 3: Użytkownik i katalogi ─────────────────────────────
echo ""
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    # Przeglądarka chodząca po internecie nie ma czego szukać na koncie root.
    useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    ok "Utworzono użytkownika systemowego: $SERVICE_USER"
else
    info "Użytkownik $SERVICE_USER już istnieje"
fi

mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$CONFIG_DIR"
ok "Katalogi gotowe"

# ── Krok 4: Kod i środowisko Python ───────────────────────────
echo ""
info "Kopiuję pliki do $INSTALL_DIR…"
cp -r "$ZRODLO/alifilament" "$INSTALL_DIR/"
cp -r "$ZRODLO/tools" "$INSTALL_DIR/"
cp "$ZRODLO/requirements.txt" "$INSTALL_DIR/"
cp "$ZRODLO/config.example.yaml" "$INSTALL_DIR/"
[[ -f "$ZRODLO/README.md" ]] && cp "$ZRODLO/README.md" "$INSTALL_DIR/"
ok "Pliki skopiowane"

info "Tworzę środowisko Python (to potrwa chwilę)…"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
ok "Zależności Python zainstalowane"

if [[ -z "$CHROMIUM_PATH" ]]; then
    info "Pobieram Chromium dla Playwrighta (~150 MB)…"
    "$INSTALL_DIR/venv/bin/playwright" install --with-deps chromium
    # Przeglądarka ląduje w katalogu domowym użytkownika usługi.
    PLAYWRIGHT_CACHE="${DATA_DIR}/.cache/ms-playwright"
    mkdir -p "$PLAYWRIGHT_CACHE"
    if [[ -d /root/.cache/ms-playwright ]]; then
        cp -r /root/.cache/ms-playwright/. "$PLAYWRIGHT_CACHE/"
    fi
    ok "Chromium gotowy"
fi

# ── Krok 5: Pliki konfiguracyjne ──────────────────────────────
echo ""
cat > "$ENV_FILE" <<ENVEOF
# Konfiguracja skanera filamentu AliExpress
# Sekrety - plik czytany przez systemd (EnvironmentFile)
TELEGRAM_BOT_TOKEN=${BOT_TOKEN}
TELEGRAM_CHAT_ID=${CHAT_ID}
ALIFILAMENT_DATA_DIR=${DATA_DIR}
ALIFILAMENT_CONFIG=${CONFIG_FILE}
CHROMIUM_PATH=${CHROMIUM_PATH}
ENVEOF
# 640 z grupą usługi: systemd i tak wczytuje plik jako root, ale dzięki temu
# ręczne uruchomienia (sudo -u alifilament ... --dry-run) też widzą token,
# a reszta świata nadal nie.
chown root:"$SERVICE_USER" "$ENV_FILE" 2>/dev/null || true
chmod 640 "$ENV_FILE"
ok "Zapisano $ENV_FILE (czyta root i usługa, nikt więcej)"

if [[ -f "$CONFIG_FILE" ]]; then
    info "Zachowuję istniejący $CONFIG_FILE"
else
    cp "$ZRODLO/config.example.yaml" "$CONFIG_FILE"
    ok "Utworzono $CONFIG_FILE (marki, materiały, progi — edytuj do woli)"
fi

# Konfiguracja musi być czytelna dla użytkownika usługi.
chmod 644 "$CONFIG_FILE"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"
chown -R root:root "$INSTALL_DIR"
chmod -R a+rX "$INSTALL_DIR"

# ── Krok 6: Edycja konfiguracji bez sudo ──────────────────────
# Godziny, liczbę ofert i wstrzymanie powiadomień ustawia się komendami
# w czacie, ale marki, materiały czy magazyny siedzą w config.yaml.
# Bez tego kroku każda ich zmiana wymagałaby roota.
echo ""
ADMIN_USER="${ALIFILAMENT_ADMIN:-${SUDO_USER:-}}"

if [[ -z "$ADMIN_USER" || "$ADMIN_USER" == "root" ]]; then
    info "Instalacja z konta root — pomijam nadawanie praw do konfiguracji."
    info "Możesz to zrobić później:  sudo usermod -aG $ADMIN_GROUP <użytkownik>"
elif ! id -u "$ADMIN_USER" >/dev/null 2>&1; then
    warn "Nie znajduję użytkownika '$ADMIN_USER' — pomijam prawa do konfiguracji."
else
    echo -e "${CYAN}  Edycja ${CONFIG_FILE} bez sudo${NC}"
    echo "  (marki, materiały, magazyny, progi — reszta ustawień jest w czacie)"
    nadaj=$(pytaj "  Pozwolić użytkownikowi '$ADMIN_USER' edytować ten plik? [T/n]: " "t")

    if [[ "${nadaj,,}" != "n" ]]; then
        groupadd -f "$ADMIN_GROUP"
        usermod -aG "$ADMIN_GROUP" "$ADMIN_USER"

        # Prawo zapisu musi obejmować katalog, bo edytory (vim, nano)
        # zapisują przez plik tymczasowy i podmianę nazwy, a nie w miejscu.
        # Bit setgid pilnuje, żeby nowe pliki dziedziczyły grupę.
        chgrp "$ADMIN_GROUP" "$CONFIG_DIR" "$CONFIG_FILE"
        chmod 2775 "$CONFIG_DIR"
        chmod 664 "$CONFIG_FILE"

        ok "Użytkownik $ADMIN_USER należy do grupy $ADMIN_GROUP"
        warn "Prawo zadziała po ponownym zalogowaniu (albo: newgrp $ADMIN_GROUP)"
        info "Plik z tokenem ($ENV_FILE) celowo zostaje tylko dla roota."
    fi
fi

# ── Krok 7: Strefa czasowa ────────────────────────────────────
echo ""
AKTUALNA_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || echo nieznana)"
if [[ "$AKTUALNA_TZ" != "Europe/Warsaw" ]]; then
    warn "Strefa czasowa systemu: $AKTUALNA_TZ"
    warn "Godziny raportów liczą się wg strefy systemowej!"
    set_tz=$(pytaj "  Ustawić Europe/Warsaw? [T/n]: " "t")
    if [[ "${set_tz,,}" != "n" ]]; then
        timedatectl set-timezone Europe/Warsaw && ok "Strefa ustawiona na Europe/Warsaw"
    fi
else
    ok "Strefa czasowa: $AKTUALNA_TZ"
fi

# ── Krok 8: Usługi systemd ────────────────────────────────────
echo ""
info "Instaluję jednostki systemd…"
cp "$ZRODLO/systemd/alifilament-scan.service" /etc/systemd/system/
cp "$ZRODLO/systemd/alifilament-scan.timer"   /etc/systemd/system/
cp "$ZRODLO/systemd/alifilament-bot.service"  /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now alifilament-scan.timer >/dev/null 2>&1
systemctl enable --now alifilament-bot.service >/dev/null 2>&1
ok "Usługi włączone"

# ── Krok 9: Test ──────────────────────────────────────────────
echo ""
info "Wysyłam wiadomość testową na Telegram…"
if sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" \
     -m alifilament.scan --test-telegram; then
    ok "Telegram odpowiada"
else
    warn "Test nie przeszedł — sprawdź token i czy bot jest w grupie."
fi

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   Instalacja zakończona                          ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""
echo "  Pliki:"
echo "    Kod:           $INSTALL_DIR"
echo "    Sekrety:       $ENV_FILE            (tylko root)"
echo "    Ustawienia:    $CONFIG_FILE"
echo "    Dane i baza:   $DATA_DIR"
echo ""
if getent group "$ADMIN_GROUP" >/dev/null 2>&1 && \
   id -nG "${ADMIN_USER:-}" 2>/dev/null | grep -qw "$ADMIN_GROUP"; then
    echo "  Konfigurację edytujesz BEZ sudo (grupa $ADMIN_GROUP):"
    echo "    nano $CONFIG_FILE"
    echo "    ...ale najpierw wyloguj się i zaloguj ponownie,"
    echo "    albo w bieżącej sesji uruchom: newgrp $ADMIN_GROUP"
    echo ""
fi
echo "  Pierwszy skan od ręki (potrwa kilka minut):"
echo "    napisz /skanuj do bota   albo:"
echo "    sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/python -m alifilament.scan --force"
echo "    journalctl -u alifilament-scan -f"
echo ""
echo "  UWAGA: samo 'systemctl start alifilament-scan.service' uszanuje"
echo "  harmonogram i poza wyznaczoną porą nic nie zrobi. Do wymuszenia"
echo "  służy /skanuj albo flaga --force powyżej."
echo ""
echo "  Bot w Telegramie:"
echo "    /start  /stop            — wznów i wstrzymaj powiadomienia"
echo "    /godziny 8 13 20         — ustaw własne pory raportów"
echo "    /top  /kody  /skanuj  /status  /filtry  /historia"
echo ""
