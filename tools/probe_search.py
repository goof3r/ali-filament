#!/usr/bin/env python3
"""
Etap 0 — rekonesans struktury danych AliExpress.

Nic tu nie jest zaszyte na sztywno. Skrypt otwiera stronę wyszukiwania, zrzuca
wszystkie bloby JSON osadzone w stronie oraz odpowiedzi XHR, a potem
heurystycznie wskazuje, gdzie siedzi lista produktów i jak nazywają się pola.
Dopiero na podstawie tego wyniku powstaje docelowy parser.

Uruchomienie:
    python tools/probe_search.py --query "sunlu pla" --ship-from PL
    python tools/probe_search.py --test-multi     # czy shipFromCountry przyjmuje listę krajów
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Brak Playwright. Zainstaluj: pip install playwright && playwright install chromium")
    sys.exit(1)

# Rekonesans korzysta z produkcyjnego lokalizatora i parsera — dzięki temu
# sprawdza realny kod skanera, a nie własną kopię heurystyki.
from alifilament.parser import (  # noqa: E402
    parsuj, po_sciezce as deep_get, znajdz_listy_produktow as find_product_arrays,
)

PROBE_DIR = Path(__file__).resolve().parent.parent / "probe"

# Wymusza polską lokalizację i ceny w PLN — bez tego ceny przyjdą w USD.
COOKIE_USUC = "site=glo&c_tp=PLN&region=PL&b_locale=pl_PL"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")

# Sygnatury strony blokady / captchy.
BLOCK_MARKERS = ("x5sec", "punish", "_____tmd_____", "captcha", "slide to verify")

# ── Zrzut blobów z okna przeglądarki ─────────────────────────────────────────
# Serializacja własna, bo runParams potrafi mieć cykle i węzły DOM.
JS_DUMP_WINDOW = """
() => {
  const seen = new WeakSet();
  const strip = (v, depth) => {
    if (depth > 14) return 'OBCIETE';
    if (v === null || v === undefined) return v;
    const t = typeof v;
    if (t === 'function') return 'FUNKCJA';
    if (t !== 'object') return v;
    if (typeof Node !== 'undefined' && v instanceof Node) return 'DOM';
    if (seen.has(v)) return 'CYKL';
    seen.add(v);
    if (Array.isArray(v)) return v.slice(0, 80).map(x => strip(x, depth + 1));
    const o = {};
    for (const k of Object.keys(v)) {
      try { o[k] = strip(v[k], depth + 1); } catch (e) { o[k] = 'BLAD_ODCZYTU'; }
    }
    return o;
  };
  const out = {};
  for (const k of Object.getOwnPropertyNames(window)) {
    if (!/^(runParams|_dida_config_|__AER|_init_data_|__INITIAL|__NEXT_DATA__|__APOLLO)/i.test(k)) continue;
    try { out[k] = strip(window[k], 0); } catch (e) { out[k] = 'BLAD'; }
  }
  return out;
}
"""


def build_url(query: str, ship_from: str | None, page: int = 1) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    url = f"https://pl.aliexpress.com/w/wholesale-{slug}.html?page={page}"
    if ship_from:
        url += f"&shipFromCountry={ship_from}"
    return url


def describe_item(item: dict, indent="    ") -> str:
    """Czytelny opis jednego produktu — klucze, typy, skrócone wartości."""
    lines = []
    for k in sorted(item.keys()):
        v = item[k]
        if isinstance(v, dict):
            sub = ", ".join(list(v.keys())[:12])
            lines.append(f"{indent}{k}: <dict> {{{sub}}}")
        elif isinstance(v, list):
            head = json.dumps(v[:2], ensure_ascii=False)[:120]
            lines.append(f"{indent}{k}: <list[{len(v)}]> {head}")
        else:
            lines.append(f"{indent}{k}: {str(v)[:160]}")
    return "\n".join(lines)


def hunt_fields(item: dict) -> dict:
    """Wskazuje kandydatów na pola, które nas interesują."""
    wanted = {
        "id":       r"(productId|product_id|itemId|item_id)",
        "tytul":    r"(title|subject|name|displayTitle)",
        "cena":     r"(price|salePrice|minPrice|formatedAmount|value)",
        "obrazek":  r"(image|imgUrl|imagePath|picUrl|mainImage)",
        "wysylka":  r"(ship|logistic|delivery|warehouse|sendFrom|shipFrom)",
        "ocena":    r"(star|rating|evaluat|score|review)",
        "sprzedaz": r"(trade|sold|orders|sale)",
        "kupon":    r"(coupon|promo|discount|deal|bonus)",
        "sklep":    r"(store|seller|shop)",
        "url":      r"(url|link|href|detailUrl)",
    }
    flat = {}

    def walk(n, path=""):
        if isinstance(n, dict):
            for k, v in n.items():
                p = f"{path}.{k}" if path else k
                if isinstance(v, (dict, list)):
                    walk(v, p)
                else:
                    flat[p] = v
        elif isinstance(n, list):
            for i, v in enumerate(n[:3]):
                walk(v, f"{path}[{i}]")

    walk(item)
    out = {}
    for label, pattern in wanted.items():
        rx = re.compile(pattern, re.I)
        out[label] = [(p, v) for p, v in flat.items() if rx.search(p)][:8]
    return out


# ── Pobranie strony ──────────────────────────────────────────────────────────

async def probe_once(url: str, tag: str, headful: bool = False) -> dict:
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    xhr_log: list[dict] = []
    bodies: dict[str, str] = {}

    async with async_playwright() as pw:
        launch_kwargs = {"headless": not headful,
                         "args": ["--disable-dev-shm-usage", "--no-sandbox"]}
        exe = os.environ.get("CHROMIUM_PATH")
        if exe:
            launch_kwargs["executable_path"] = exe

        browser = await pw.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=UA,
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            viewport={"width": 1440, "height": 900},
        )
        await context.add_cookies([{
            "name": "aep_usuc_f", "value": COOKIE_USUC,
            "domain": ".aliexpress.com", "path": "/",
        }])
        page = await context.new_page()

        async def on_response(resp):
            try:
                ct = (resp.headers or {}).get("content-type", "")
                u = resp.url
                if "json" not in ct.lower() and "/fn/" not in u and "mtop" not in u:
                    return
                if resp.status != 200:
                    return
                body = await resp.text()
                xhr_log.append({"url": u, "status": resp.status,
                                "content_type": ct, "rozmiar": len(body)})
                if len(body) > 2000:
                    bodies[u] = body
            except Exception:
                pass

        page.on("response", on_response)

        print(f"-> otwieram: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"   UWAGA goto: {e}")

        # Przewinięcie wymusza doładowanie leniwych kafelków.
        for _ in range(4):
            await page.mouse.wheel(0, 2000)
            await page.wait_for_timeout(900)
        await page.wait_for_timeout(2500)

        html = await page.content()
        title = await page.title()
        final_url = page.url

        low_html, low_url = html.lower(), final_url.lower()
        blocked = [m for m in BLOCK_MARKERS if m in low_html or m in low_url]

        try:
            window_data = await page.evaluate(JS_DUMP_WINDOW)
        except Exception as e:
            print(f"   UWAGA zrzut window: {e}")
            window_data = {}

        await page.screenshot(path=str(PROBE_DIR / f"{tag}.png"), full_page=False)
        (PROBE_DIR / f"{tag}.html").write_text(html, encoding="utf-8")
        (PROBE_DIR / f"{tag}-window.json").write_text(
            json.dumps(window_data, ensure_ascii=False, indent=2), encoding="utf-8")
        (PROBE_DIR / f"{tag}-xhr.json").write_text(
            json.dumps(sorted(xhr_log, key=lambda r: -r["rozmiar"]), ensure_ascii=False, indent=2),
            encoding="utf-8")

        # Największe odpowiedzi JSON — tam bywa prawdziwe API wyszukiwania.
        for i, (u, body) in enumerate(sorted(bodies.items(), key=lambda kv: -len(kv[1]))[:5]):
            (PROBE_DIR / f"{tag}-xhr{i}.json").write_text(f"// {u}\n{body}", encoding="utf-8")

        await browser.close()

    return {"tytul_strony": title, "final_url": final_url, "html_len": len(html),
            "blokada": blocked, "window": window_data, "xhr": xhr_log}


def report(res: dict, tag: str) -> list:
    print(f"\n{'=' * 78}")
    print(f"WYNIK: {tag}")
    print("=" * 78)
    print(f"Tytul strony : {res['tytul_strony']}")
    print(f"URL koncowy  : {res['final_url']}")
    print(f"Rozmiar HTML : {res['html_len']:,} znakow")
    if res["blokada"]:
        print(f"BLOKADA/CAPTCHA — wykryte sygnatury: {res['blokada']}")

    print(f"\nKlucze window: {list(res['window'].keys()) or 'BRAK'}")
    print(f"Odpowiedzi JSON/XHR: {len(res['xhr'])}")
    for r in sorted(res["xhr"], key=lambda r: -r["rozmiar"])[:6]:
        print(f"   {r['rozmiar']:>9,} B  {r['url'][:110]}")

    cands = find_product_arrays(res["window"])
    cands.sort(key=lambda c: -c[1])
    print(f"\n-- Kandydaci na liste produktow ({len(cands)}) --")
    for path, n, keys in cands[:6]:
        print(f"   [{n:>3} elem.] {path}")
        print(f"              klucze: {', '.join(keys[:18])}")
    return cands


async def main():
    ap = argparse.ArgumentParser(description="Rekonesans struktury AliExpress")
    ap.add_argument("--query", default="sunlu pla", help="fraza wyszukiwania")
    ap.add_argument("--ship-from", default="PL", help="kod kraju magazynu, np. PL")
    ap.add_argument("--test-multi", action="store_true",
                    help="sprawdz, czy shipFromCountry przyjmuje liste krajow")
    ap.add_argument("--headful", action="store_true", help="widoczna przegladarka")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    url = build_url(args.query, args.ship_from)
    res = await probe_once(url, f"{stamp}-single", args.headful)
    cands = report(res, f"pojedynczy kraj: {args.ship_from}")

    if cands:
        best_path, _n, _keys = max(cands, key=lambda c: c[1])
        try:
            sample = deep_get(res["window"], best_path)[0]
            print(f"\n-- Przykladowy produkt ({best_path}[0]) --")
            print(describe_item(sample))
            print("\n-- Kandydaci na potrzebne nam pola --")
            for label, hits in hunt_fields(sample).items():
                if hits:
                    print(f"   {label:9}: " + " | ".join(f"{p}={str(v)[:44]}" for p, v in hits[:4]))
                else:
                    print(f"   {label:9}: (nie znaleziono)")
        except Exception as e:
            print(f"   UWAGA: nie udalo sie wyciagnac przykladu: {e}")

    # Najważniejszy test: co z tego zrobi produkcyjny parser skanera.
    oferty, sciezka = parsuj(res["window"], args.ship_from)
    print(f"\n-- PRODUKCYJNY PARSER: {len(oferty)} ofert, sciezka: {sciezka or '(brak)'} --")
    for o in oferty[:8]:
        print(f"   {o.cena:>9.2f} {o.waluta:<4} {o.kraj_wysylki or '--':>3} "
              f"| {o.tytul[:56]}")
        print(f"       zdjecie={'jest' if o.img_url else 'BRAK':<4} "
              f"ocena={o.ocena or '-'} sprzedaz={o.sprzedanych or '-'} "
              f"dostawa={o.dostawa or '-'}")
    if oferty:
        braki = {
            "zdjecie": sum(1 for o in oferty if not o.img_url),
            "kraj": sum(1 for o in oferty if not o.kraj_wysylki),
            "ocena": sum(1 for o in oferty if o.ocena is None),
            "sklep": sum(1 for o in oferty if not o.sklep),
        }
        print(f"   braki w polach (z {len(oferty)}): {braki}")

    if args.test_multi:
        multi = "PL,ES,CZ"
        res2 = await probe_once(build_url(args.query, multi), f"{stamp}-multi", args.headful)
        cands2 = report(res2, f"lista krajow: {multi}")
        n1 = max((c[1] for c in cands), default=0)
        n2 = max((c[1] for c in cands2), default=0)
        print(f"\n{'=' * 78}")
        print(f"WERDYKT shipFromCountry={multi}")
        print(f"   pojedynczy kraj ({args.ship_from}): {n1} produktow")
        print(f"   lista krajow     ({multi}): {n2} produktow")
        if n2 > n1:
            print("   TAK — lista krajow dziala, jeden przebieg zamiast petli po magazynach.")
        elif n2 == 0:
            print("   NIE — lista krajow zwraca pustke, potrzebna petla po krajach.")
        else:
            print("   NIEPEWNE — wyniki porownywalne, sprawdz pola wysylki w zrzucie.")

    print(f"\nZrzuty w: {PROBE_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
