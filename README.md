# Skaner filamentu 3D z AliExpress → Telegram

Trzy razy dziennie przeszukuje AliExpress pod kątem filamentu marek **JAYO**, **SUNLU**
i **KINGROON** w materiałach **PLA / PLA+ / PETG / ABS / ASA**, **wyłącznie z magazynów
europejskich**, i wysyła raport na Telegram — ze zdjęciem, ceną za kilogram i przyciskiem
prowadzącym prosto do aukcji. Do tego zbiera aktualne kody rabatowe.

---

## Co dostajesz w raporcie

Nagłówek z podsumowaniem przebiegu, potem karty ofert (osobna wiadomość ze zdjęciem
i przyciskiem zakupu), na końcu sekcja kodów rabatowych:

```
🌅 Filament 3D — raport poranny
24.09.2026, 08:00

🔎 Zapytań: 12 · magazyny: PL, ES, CZ, DE
📦 Znaleziono 187 ofert → po odsiewie 23 → pokazuję 15
🆕 3 nowe · 🔻 5 tańszych · 🔥 2 poniżej 60,00 zł/kg
```

```
🔻 #1 SUNLU PLA+ Filament 1.75mm 1KG Czarny

💰 62,90 zł  (najtaniej od 7 dni — było 70,90 zł, -8,00 zł)
⚖️ 62,90 zł/kg  (1,00 kg)  🔥 poniżej progu
🇪🇺 Wysyłka z magazynu w UE · Dostawa: Wrz 27 - Paź 01
🚚 Darmowa dostawa
⭐ 4,8 (2 130 ocen) · 📈 5000+ sprzedanych
🎟️ Kody na tę kwotę (nie łączą się):
   AFCEESE9 −34,56 zł → 307,63 zł  ⭐
   AFCEESE6 −23,04 zł → 319,15 zł
   AFCEESE3 −11,52 zł → 330,67 zł
   najtaniej 31,07 zł/kg po rabacie

        [ 🛒 Otwórz na AliExpress ]
```

Przy każdej ofercie trafiają **wyłącznie te kody, które przy tej konkretnej kwocie
faktycznie wejdą** — do trzech, od największego rabatu, z ceną wynikową przy każdym.
⭐ oznacza najlepszy; zł/kg liczone jest właśnie po nim. Kupony AliExpressu **nie
sumują się**, więc kilka pozycji to nie zachęta do łączenia, a możliwość dobrania kodu
do tego, co ostatecznie znajdzie się w koszyku.

Progi podawane są w dolarach, więc przeliczamy je po kursie NBP. Gdy oferta nie dobija
do żadnego progu, karta mówi od jakiej kwoty kody zaczynają działać, zamiast obiecywać
rabat nie do wykorzystania. Liczone ceny zakładają, że kupujesz samą tę pozycję —
kupon działa na wartość całego zamówienia.

Pełnej listy kodów **nie ma na końcu raportu**: większość z nich ma progi (do 2 700 zł),
których żadna szpula filamentu nie osiąga, więc byłaby to wiadomość bez treści.
Cały spis jest na żądanie pod `/kody`.

**Dlaczego zł/kg, a nie cena?** Bo szpula 250 g za 30 zł wygląda taniej niż kilogram za
62 zł, a w rzeczywistości jest dwukrotnie droższa. Sortowanie idzie po cenie za kilogram —
masa jest wyciągana z tytułu oferty (`1KG`, `250g`, `3x1kg`). Oferta, w której masy nie da
się rozpoznać, trafia na koniec listy z wyraźną adnotacją, ale nie znika.

### Czemu część ofert nie dostaje zł/kg

To nie jest niedoróbka, tylko świadoma odmowa zgadywania. AliExpress podaje przy ofercie
**cenę najtańszego wariantu**, a tytuł opisuje zwykle największy. Przy listingu
`SUNLU 1/2/3/4/5/10KG PETG — 142,19 zł` naiwne dzielenie daje 14 zł/kg, czyli „okazję",
która nie istnieje — i taka pozycja wypycha z czołówki oferty uczciwe.

Dlatego skaner odrzuca powiązanie ceny z masą, gdy tytuł zdradza wiele wariantów
(lista liczb `1/2/3KG`, co najmniej dwa ukośniki, trzy różne materiały, dwie różne masy)
**albo** gdy wynikowe zł/kg wypada poniżej progu `min_zl_za_kg` (domyślnie 25 zł/kg —
filament z magazynu w UE po prostu tyle nie kosztuje). Taka oferta zostaje w bazie,
ale ląduje na końcu listy z wyjaśnieniem, zamiast udawać najlepszy zakup dnia.

Efekt na żywych danych: przed poprawką czołówkę zajmowały pozycje po 14–22 zł/kg
(wszystkie fikcyjne), po poprawce raport pokazuje 34–45 zł/kg, gdzie ceny hurtowe
i ceny pojedynczych szpul wreszcie się ze sobą zgadzają.

---

## Wymagania

- Debian 12 / Ubuntu / OpenMediaVault (x86_64 lub arm64 — RPi5 obsłużony)
- Python 3.11+
- ~400 MB miejsca (Chromium) i ~800 MB RAM na czas przebiegu
- Token bota Telegram od [@BotFather](https://t.me/BotFather)
- Chat ID grupy lub rozmowy docelowej

---

## Instalacja na RPi5

Bot jest już utworzony, a jego token i chat ID są wpisane
w `install-rpi5.sh` — nie musisz niczego zakładać ani przepisywać.

### 1. Wgraj pliki na RPi5

Z tej maszyny (PowerShell), z katalogu projektu:

```powershell
cd C:\Users\root\claude-projekty\ali-filament

# <uzytkownik> = konto na RPi5 z prawem sudo (root przez SSH jest zablokowany)
ssh <uzytkownik>@<adres-rpi5> "mkdir -p /tmp/ali-filament"

scp -r alifilament tools systemd install.sh install-rpi5.sh requirements.txt `
       config.example.yaml README.md `
    <uzytkownik>@<adres-rpi5>:/tmp/ali-filament/
```

### 2. Uruchom instalator na RPi5

```bash
ssh <uzytkownik>@<adres-rpi5>
cd /tmp/ali-filament
sudo bash install-rpi5.sh
```

`install-rpi5.sh` to nakładka na `install.sh` — podstawia gotowe dane bota i wyłącza
pytania, więc instalacja idzie bez jednego kliknięcia. **Ten plik zawiera token, więc
traktuj go jak hasło**; po instalacji sekret siedzi już w `/etc/alifilament.env`
i skrypt można skasować (`shred -u install-rpi5.sh`). Jest wpisany do `.gitignore`.

Gdybyś kiedyś chciał postawić to z własnym botem, `sudo bash install.sh` zapyta
o token i chat ID interaktywnie.

Instalator sam:

- doinstaluje Chromium (na ARM systemowy, bo Playwright nie ma buildów dla Debiana na ARM)
- utworzy konto systemowe `alifilament` — przeglądarka chodząca po internecie nie ma czego
  szukać na koncie root
- zbuduje środowisko Python w `/opt/ali-filament/venv/`
- zapisze sekrety w `/etc/alifilament.env` (tryb 600) i ustawienia w `/etc/alifilament/config.yaml`
- ustawi strefę `Europe/Warsaw` — **to istotne**, bo godziny liczą się wg strefy systemowej
- włączy usługi i wyśle wiadomość testową

### 3. Pierwszy skan

Napisz do bota `/skanuj` (i drugi raz w ciągu 30 s, żeby potwierdzić). Albo z konsoli:

```bash
sudo -u alifilament /opt/ali-filament/venv/bin/python -m alifilament.scan --force
journalctl -u alifilament-scan -f
```

Przebieg trwa 2–3 minuty. Raport przyjdzie na Telegram sam.

> Samo `systemctl start alifilament-scan.service` **uszanuje harmonogram** i poza
> wyznaczoną porą nic nie zrobi — do wymuszenia służy `/skanuj` albo `--force`.

---

## Rozkład plików po instalacji

| Ścieżka | Zawartość |
|---|---|
| `/opt/ali-filament/` | kod i środowisko Python |
| `/etc/alifilament.env` | token, chat ID (tryb 600) |
| `/etc/alifilament/config.yaml` | marki, materiały, magazyny, progi |
| `/var/lib/ali-filament/scanner.db` | historia cen i kuponów (SQLite) |
| `/var/lib/ali-filament/browser-profile/` | trwały profil przeglądarki |

## Uprawnienia — kiedy potrzebujesz sudo

**Sudo jest potrzebne dokładnie raz: przy instalacji.** Potem do codziennego zarządzania
nie trzeba nawet konta na RPi5 — wszystko dzieje się w czacie z botem.

Usługi chodzą na osobnym koncie systemowym `alifilament` (`nologin`, bez hasła), a `/skanuj`
uruchamia skan jako ten sam użytkownik, bez podnoszenia uprawnień. Przeglądarka chodząca
po internecie nie powinna działać jako root.

| Czynność | Sudo |
|---|---|
| Godziny, liczba ofert, wstrzymanie powiadomień | **nie** — komendy `/godziny`, `/ile`, `/stop` |
| Wymuszenie skanu | **nie** — `/skanuj` w czacie |
| Marki, materiały, magazyny, progi (`config.yaml`) | **nie**, jeśli należysz do grupy `alifilament-admin` |
| Aktualizacja kodu w `/opt/ali-filament` | tak |
| `systemctl restart`, `journalctl -u …` | tak (do samych logów wystarczy grupa `adm`) |
| Podejrzenie tokenu w `/etc/alifilament.env` | tak — ten plik celowo zostaje tylko dla roota |

Instalator sam proponuje dopisanie Twojego konta do grupy `alifilament-admin`, która ma
prawo zapisu do `/etc/alifilament/config.yaml`. Prawo zapisu obejmuje też katalog, bo
edytory zapisują przez plik tymczasowy i podmianę nazwy, a nie w miejscu.

**Członkostwo w grupie działa dopiero po ponownym zalogowaniu** — albo od razu, jeśli
w bieżącej sesji wywołasz `newgrp alifilament-admin`.

Zmiany w `config.yaml` łapią się bez restartu usług: skan czyta plik przy każdym przebiegu,
a `/filtry` odczytuje go na świeżo przy każdym wywołaniu.

Gdybyś instalował prosto z konta root (bez `sudo`), instalator nie ma skąd wziąć nazwy
Twojego konta i ten krok pominie. Nadasz je później:

```bash
sudo usermod -aG alifilament-admin <uzytkownik>
```

---

## Komendy bota

| Komenda | Działanie |
|---|---|
| `/start` | wznawia wysyłanie raportów |
| `/stop` | wstrzymuje wysyłanie — skaner nawet nie uruchomi przeglądarki |
| `/godziny` | pokazuje ustawione pory |
| `/godziny 8 13 20` | ustawia własne pory (można z minutami: `7:30 12:00 21:45`) |
| `/ile 20` | ile ofert ma zawierać raport (1–30, domyślnie 15) |
| `/top [n]` | najlepsze oferty z ostatniego skanu (bez ponownego scrapowania) |
| `/szukaj bezplatne` | tylko oferty z darmową dostawą |
| `/szukaj platne` | tylko oferty z płatną dostawą |
| `/szukaj wszystkie` | jedno i drugie |
| `/porownaj` | co wychodzi taniej: płatna czy darmowa wysyłka |
| `/kody` | aktualne kody rabatowe |
| `/skanuj` | wymuś skan teraz — działa też przy wstrzymanych powiadomieniach |
| `/historia <id>` | wykres ceny produktu w czasie |
| `/filtry` | czego szukam i skąd |
| `/status` | stan powiadomień, godziny, ostatni skan, następny przebieg |
| `/help` | lista wszystkich komend |

Zamienniki nazw, gdyby któraś nie przyszła do głowy: `/pomoc` = `/help`,
`/pauza` = `/stop`, `/liczba` = `/ile`, `/harmonogram` = `/godziny`, `/kupony` = `/kody`.

Komendy są też zarejestrowane w menu Telegrama — po wpisaniu `/` w oknie czatu
aplikacja sama podpowiada listę z opisami, więc nie trzeba ich pamiętać.

Ustawienia zmieniane komendami trafiają do bazy i **działają od razu** — bez restartu
usług i bez logowania się na RPi5.

### Jak działa harmonogram

Zmiana jednostki systemd wymaga roota, więc godziny nie mogą siedzieć w timerze, skoro
mają być zmienialne z czatu. Zamiast tego timer budzi skaner **co 15 minut**, a program
sam sprawdza, czy minęła pora, dla której nie poszedł jeszcze raport. Jeśli nie — kończy
pracę po ułamku sekundy, nie dotykając przeglądarki. Przy trzech porach dziennie oznacza
to 3 realne skany i kilkadziesiąt natychmiastowych wyjść.

Ubocznym zyskiem jest odporność na przerwy: gdy RPi5 był wyłączony o 8:00 i wstaje o 9:30,
raport zostanie **nadrobiony**. Limit nadrabiania to 3 godziny, więc maszyna wybudzona
w środku nocy nie zasypie czatu zaległościami z całej doby.

---

## Konfiguracja

Godziny, liczbę ofert i wstrzymanie powiadomień ustawia się **komendami w czacie**
(`/godziny`, `/ile`, `/stop`) — te wartości trafiają do bazy i mają pierwszeństwo
przed plikiem konfiguracyjnym.

Reszta siedzi w `/etc/alifilament/config.yaml` — plik czytany jest przy każdym
przebiegu, więc zmiana **nie wymaga restartu usługi**.

```yaml
marki:     [jayo, sunlu, kingroon]
materialy: [PLA, "PLA+", PETG, ABS, ASA]
magazyny_eu: [PL, ES, CZ, DE, FR, IT, NL, BE]
top_n:          15
alert_zl_za_kg: 60.0      # poniżej tej ceny oferta dostaje znacznik 🔥
```

Domyślne godziny (obowiązujące, dopóki nie użyjesz `/godziny`) też są w tym pliku:

```yaml
godziny: ["08:00", "13:00", "20:00"]
top_n:   15
```

Timera systemd nie trzeba ruszać — budzi skaner co 15 minut, a o porze decyduje
harmonogram z bazy.

---

## Uruchamianie ręczne i diagnostyka

```bash
cd /opt/ali-filament
sudo -u alifilament ./venv/bin/python -m alifilament.scan --test-telegram   # token + chat ID
sudo -u alifilament ./venv/bin/python -m alifilament.scan --limit 1 --dry-run
sudo -u alifilament ./venv/bin/python -m alifilament.scan --dry-run         # raport na konsolę
sudo -u alifilament ./venv/bin/python -m alifilament.scan --force           # pełny + wysyłka
```

Flagi: `--force` (pomiń harmonogram i wstrzymanie), `--limit N` (tylko N pierwszych
zapytań), `--kraj PL` (jeden magazyn), `--bez-kuponow`, `--verbose`.
`--dry-run` też pomija harmonogram, bo służy do diagnostyki.

```bash
journalctl -u alifilament-scan -n 80 --no-pager    # logi skanu
journalctl -u alifilament-bot -f                   # logi bota
systemctl list-timers alifilament-scan.timer       # budzik (co 15 min)
```

W logach zobaczysz zarówno `Wykonuję raport dla pory 08:00`, jak i częste
`Pomijam przebieg — nie ta pora` — to drugie jest normalne i oznacza, że budzik
zadziałał, a program uznał, że nie jego kolej.

Testy logiki (nie wymagają sieci ani przeglądarki):

```bash
./venv/bin/python tools/selftest_filters.py       # odsiew, masa, zł/kg
./venv/bin/python tools/selftest_harmonogram.py   # decyzja o porze wysyłki
```

Rekonesans struktury danych AliExpressu — gdy parser przestanie cokolwiek znajdować:

```bash
./venv/bin/python tools/probe_search.py --query "sunlu pla" --ship-from PL
```

Zrzuca blob JSON, zrzut HTML i screenshot do `probe/`, po czym pokazuje,
ile ofert wyciągnął z tego **produkcyjny parser**.

### Środowisko testowe (serwer bez roota)

Projekt był budowany i testowany na osobnym serwerze (zwykłe konto), bez instalowania czegokolwiek
w systemie — konto nie ma sudo, więc biblioteki Chromium leżą rozpakowane lokalnie
w `~/ali-filament/syslibs` (`apt-get download` + `dpkg -x`), bot chodzi jako proces
odpięty od sesji SSH, a harmonogram obsługuje cron użytkownika zamiast systemd.
Zachowanie jest takie samo jak docelowe: cron budzi skaner co 15 minut, a o porze
decyduje `harmonogram.py`.

Steruje się tym skryptem `~/ali-filament/ali.sh`:

```bash
./ali.sh status        # bot, cron, harmonogram, ostatni skan
./ali.sh start|stop|restart
./ali.sh skan          # wymuś skan teraz (omija harmonogram)
./ali.sh logi          # ogon bot.log i skan.log
./ali.sh odinstaluj    # zatrzymuje bota i kasuje wpisy crona
```

Wpisy crona mają znacznik `# alifilament`, więc `odinstaluj` nie tyka wpisów `qlds-ctl`
serwera Quake Live.

Surowe uruchomienie, gdyby trzeba było ominąć skrypt:

```bash
export LD_LIBRARY_PATH=$HOME/ali-filament/syslibs/usr/lib/x86_64-linux-gnu
export ALIFILAMENT_DATA_DIR=$HOME/ali-filament/dane
cd ~/ali-filament && ./venv/bin/python -m alifilament.scan --dry-run
```

Na RPi5 nic z tego nie jest potrzebne — tam instalator stawia systemowego Chromium,
konto systemowe i usługi systemd.

---

## Jak to działa i gdzie są granice

**Źródło danych.** Zwykłe strony wyszukiwania AliExpress z parametrem
`&shipFromCountry=PL`. Oficjalne Affiliate API zostało rozważone i odrzucone: wymaga
wniosku z akceptacją, a przede wszystkim **nie ma filtra magazynu wysyłkowego** — ma
tylko kraj dostawy, czyli nie potrafi spełnić głównego wymagania.

**Odporność parsera.** AliExpress zmienia nazwy pól między wersjami frontendu, więc nic
nie jest zaszyte na jedną ścieżkę: lokalizator sam znajduje w blobie tablicę wyglądającą
na listę produktów, a pola wyciągane są po liście kandydatów. `tools/probe_search.py`
używa dokładnie tego samego kodu co produkcja, więc rekonesans sprawdza realny parser,
a nie swoją kopię.

**Darmowa wysyłka.** Skan zbiera **obie grupy naraz** i zapisuje całą pulę, a filtr
wysyłki nakłada się dopiero przy składaniu raportu. Dzięki temu `/szukaj platne`,
`/szukaj bezplatne` i `/szukaj wszystkie` odpowiadają natychmiast, bez ponownego
odpytywania AliExpressu — jeden skan obsługuje trzy widoki i porównanie. Raporty
z harmonogramu idą w trybie z `tryb_wysylki` (domyślnie `darmowa`).

Sprawdzone: AliExpress nie ma filtra wysyłki w adresie —
`isFreeShip=y`, `shipFree=y` i `freeShipping=true` są po cichu ignorowane, wszystkie
zwracają ten sam zestaw wyników. Jedynym śladem jest znacznik przy ofercie, i to
w dwóch odmianach: bezwarunkowej („Darmowa dostawa") oraz progowej („Darmowa dostawa
powyżej 40zł"). Progową uznajemy tylko wtedy, gdy oferta ten próg przekracza — inaczej
obiecywalibyśmy dostawę, której kupujący nie dostanie. Realnie przechodzi około 20–25%
ofert, więc filtr mocno przerzedza wyniki; wyłącza się go jedną linią w `config.yaml`.

**Porównanie płatnej z darmową (`/porownaj`).** Nie podaje ceny z dostawą, bo **koszt
wysyłki nie występuje w danych wyszukiwania** — sprawdziłem siedem możliwych nazw pól
(`shippingFee`, `freight`, `deliveryFee`, `postage`…), nie ma ani jednego. Zamiast udawać,
że wiemy, komenda liczy **próg opłacalności**: o ile tańsza jest najlepsza oferta płatna
w samej cenie i ile złotych może pochłonąć dostawa, żeby wciąż wygrała. Przykład z żywych
danych: płatna była tańsza o 6,46 zł/kg, co przy szpuli 9,9 kg dawało 63,95 zł zapasu na
przesyłkę. Do tego mediany obu grup — bo tam widać, że oferty z darmową dostawą są
systematycznie droższe za kilogram.

Uwaga na pułapkę, na którą się nadziałem: AliExpress dorysowuje te znaczniki dopiero
przy przewijaniu strony, więc w każdym zapytaniu kilkanaście kafelków przychodzi bez
nich. Deduplikacja **scala** opisy między wystąpieniami tej samej oferty zamiast wybierać
jedno — bez tego znikało z raportu kilkadziesiąt ofert, które darmową wysyłkę mają,
tylko akurat nie w tym zapytaniu (6 ofert zamiast 84).

**Kraj magazynu.** Sprawdzone na żywych danych: wyniki wyszukiwania **nie zawierają kraju
magazynu przy pojedynczej ofercie** — ani nazwy sklepu. Jedyną gwarancją europejskiej
wysyłki jest filtr `shipFromCountry` w adresie, i AliExpress przyjmuje w nim listę krajów
naraz (`PL,ES,CZ,DE,…`). Stąd domyślne `lista_krajow_w_url: true`: jeden przelot na
zapytanie zamiast ośmiu, za cenę tego, że oferta jest opisana jako 🇪🇺 „magazyn w UE",
bez wskazania konkretnego kraju. Kto woli dokładne flagi, ustawia `false` — kosztuje to
ośmiokrotnie więcej zapytań przy każdym przebiegu.

**Blokady.** Przy captchy skan przerywa się i mówi o tym wprost na Telegramie, zamiast
w kółko ponawiać — ponawianie tylko pogłębia blokadę i zamienia chwilową awarię w trwałą.
Ryzyko jest ograniczone przez domowe IP, 3 przebiegi dziennie, losowe przerwy 3–8 s
i trwały profil przeglądarki, ale **nie jest zerowe**.

**Kody rabatowe.** Ogólne kody pochodzą z pepper.pl, który wystawia je w ustrukturyzowanym
JSON-ie z datą ważności i flagą weryfikacji. Sprawdziłem też inne źródła i świadomie je
odrzuciłem: lowcychin.pl trzyma kody wyłącznie w komentarzach użytkowników (bez dat
i weryfikacji), a picodi.pl i kodyrabatowe.pl w ogóle nie mają kodów w HTML — odsłaniają
je dopiero po kliknięciu. Dokładanie ich dałoby raportowi szum, nie wartość.
Kupony przypisane do konkretnej oferty pochodzą wprost z danych AliExpressu.

**Regulamin AliExpress.** Scraping jest formalnie niezgodny z ich ToS. Przy użytku
prywatnym i tym wolumenie ryzyko praktyczne jest znikome, ale należy Ci się ta informacja
przed startem, nie po.

---

## Aktualizacja

Z tej maszyny (PowerShell):

```powershell
cd C:\Users\root\claude-projekty\ali-filament
scp -r alifilament tools config.example.yaml <uzytkownik>@<adres-rpi5>:/tmp/ali-filament/
```

Na RPi5:

```bash
ssh <uzytkownik>@<adres-rpi5>
sudo cp -r /tmp/ali-filament/alifilament /opt/ali-filament/
sudo cp -r /tmp/ali-filament/tools       /opt/ali-filament/
sudo systemctl restart alifilament-bot
```

Restartu wymaga tylko bot, bo działa ciągle. Skaner jest procesem jednorazowym —
przy najbliższym przebiegu sam podniesie nowy kod.

Konfiguracja, baza i ustawienia z czatu (godziny, liczba ofert, wstrzymanie) zostają
nietknięte. Nowe opcje z `config.example.yaml` mają wartości domyślne wpisane w kodzie,
więc działają nawet bez dopisywania ich do `/etc/alifilament/config.yaml`.

Sprawdzenie po aktualizacji:

```bash
cd /opt/ali-filament
sudo -u alifilament ./venv/bin/python tools/selftest_filters.py
sudo -u alifilament ./venv/bin/python -m alifilament.scan --limit 2 --dry-run
systemctl status alifilament-bot
```
