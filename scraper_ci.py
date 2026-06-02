#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DINATICKET_EVENTS = {
    "Disfruta": ["https://www.dinaticket.com/es/provider/20864/event/4947155"],
    "Escondi2": ["https://www.dinaticket.com/es/provider/20864/event/4943466"],
}

ONEBOX_EVENTS = {
    "Miedo": "https://entradas.laescaleradejacob.es/laescaleradejacob/events/56108",
    "CluedoMental": "https://entradas.laescaleradejacob.es/laescaleradejacob/events/56921",
}

ONEBOX_FALLBACK_SELECTS = {
    "https://entradas.laescaleradejacob.es/laescaleradejacob/events/56108": [
        {"url": "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2904525", "fecha_iso": "2026-06-05", "hora": "23:00"},
        {"url": "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2904526", "fecha_iso": "2026-06-12", "hora": "23:00"},
        {"url": "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2904527", "fecha_iso": "2026-06-19", "hora": "23:00"},
        {"url": "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2904528", "fecha_iso": "2026-06-26", "hora": "23:00"},
    ],

    "https://entradas.laescaleradejacob.es/laescaleradejacob/events/56921": [
        {"url": "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2905048", "fecha_iso": "2026-06-05", "hora": "19:30"},
        {"url": "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2905049", "fecha_iso": "2026-06-19", "hora": "19:30"},
        {"url": "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2905050", "fecha_iso": "2026-06-26", "hora": "19:30"},
    ],
}

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123 Safari/537.36"
    )
}

TZ = ZoneInfo("Europe/Madrid")

TEMPLATE_PATH = Path("template.html")
MANIFEST_PATH = Path("manifest.json")
SW_PATH = Path("sw.js")
DOCS_DIR = Path("docs")
ONEBOX_CACHE_PATH = DOCS_DIR / "onebox_cache.json"

MESES_CORTOS = {
    "Ene": "01", "Feb": "02", "Mar": "03", "Abr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Ago": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dic": "12",
}

MESES_ES = {
    "ene": "01", "enero": "01",
    "feb": "02", "febrero": "02",
    "mar": "03", "marzo": "03",
    "abr": "04", "abril": "04",
    "may": "05", "mayo": "05",
    "jun": "06", "junio": "06",
    "jul": "07", "julio": "07",
    "ago": "08", "agosto": "08",
    "sep": "09", "sept": "09", "septiembre": "09",
    "oct": "10", "octubre": "10",
    "nov": "11", "noviembre": "11",
    "dic": "12", "diciembre": "12",
}


def normalize_hhmm(h: str | None) -> str:
    if not h:
        return "00:00"
    s = str(h).strip().lower()
    s = s.replace(" ", "").replace("h", "")
    s = re.sub(r"[^0-9:]", "", s)
    s = s.rstrip(":")
    m = re.match(r"^(\d{1,2})(?::?(\d{2}))?$", s)
    if not m:
        return s
    return f"{int(m.group(1)):02d}:{int(m.group(2) or '00'):02d}"


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def slugify(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_")


def load_onebox_cache() -> dict:
    if not ONEBOX_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(ONEBOX_CACHE_PATH.read_text("utf-8"))
    except Exception:
        return {}


def save_onebox_cache(cache: dict) -> None:
    DOCS_DIR.mkdir(exist_ok=True)
    ONEBOX_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        "utf-8",
    )
    print("✔ Actualizado docs/onebox_cache.json")


def write_html(payload: dict) -> None:
    if not TEMPLATE_PATH.exists():
        print("⚠️ No existe template.html; no genero docs/index.html")
        return

    html_template = TEMPLATE_PATH.read_text("utf-8")
    html = html_template.replace(
        "{{PAYLOAD_JSON}}",
        json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>"),
    )

    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(html, "utf-8")

    if MANIFEST_PATH.exists():
        shutil.copy(MANIFEST_PATH, DOCS_DIR / "manifest.json")
    if SW_PATH.exists():
        shutil.copy(SW_PATH, DOCS_DIR / "sw.js")

    print("✔ Generado docs/index.html")


def write_schedule_json(payload: dict) -> None:
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "schedule.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        "utf-8",
    )
    print("✔ Generado docs/schedule.json")


def fetch_functions_dinaticket(url: str) -> list[dict]:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    out: list[dict] = []

    for session in soup.find_all("div", class_="js-session-row"):
        parent = session.find_parent("div", class_="js-session-group")
        if not parent:
            continue

        dia = parent.find("span", class_="num_dia")
        mes = parent.find("span", class_="mes")
        if not dia or not mes:
            continue

        mes_txt = mes.get_text(strip=True).replace(".", "")
        mes_num = MESES_CORTOS.get(mes_txt)
        if not mes_num:
            print("DEBUG Dinaticket mes no reconocido:", repr(mes_txt))
            continue

        now = datetime.now(TZ)
        anio = now.year

        fecha_tmp = datetime.strptime(
            f"{anio}-{mes_num}-{dia.get_text(strip=True).zfill(2)}",
            "%Y-%m-%d",
        )

        if fecha_tmp.date() < now.date():
            fecha_tmp = fecha_tmp.replace(year=anio + 1)

        fecha_iso = fecha_tmp.strftime("%Y-%m-%d")
        fecha_label = fecha_tmp.strftime("%d %b %Y")

        hora_span = session.find("span", class_="session-card__time-session")
        hora = normalize_hhmm(hora_span.get_text(strip=True) if hora_span else "")

        quotas = session.find_all("div", class_="js-quota-row")

        if not quotas:
            cap = None
            stock = None
            vendidas = None
        else:
            cap = sum(safe_int(q.get("data-quota-total", 0)) for q in quotas)
            stock = sum(safe_int(q.get("data-stock", 0)) for q in quotas)
            vendidas = max(0, cap - stock)

        out.append({
            "fecha_label": fecha_label,
            "fecha_iso": fecha_iso,
            "hora": hora,
            "vendidas_dt": vendidas,
            "capacidad": cap,
            "stock": stock,
            "buy_url": None,
            "source": "dinaticket",
        })

    return sorted(out, key=lambda f: (f["fecha_iso"], f["hora"]))


def parse_onebox_date(raw: str) -> tuple[str, str] | None:
    raw = raw.replace("\xa0", " ")
    raw = " ".join(raw.split()).lower()

    patterns = [
        r"(?:lun|mar|mi[eé]|jue|vie|s[aá]b|dom)\.?,?\s+(\d{1,2})\s+([a-záéíóúñ]+)\s+(\d{4})\s*-\s*(\d{1,2}):(\d{2})",
        r"(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\.?,?\s+(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4}).*?(\d{1,2}):(\d{2})",
        r"(\d{1,2})[/-](\d{1,2})[/-](\d{4}).*?(\d{1,2}):(\d{2})",
    ]

    for i, pat in enumerate(patterns):
        m = re.search(pat, raw, re.IGNORECASE)
        if not m:
            continue

        if i == 2:
            dia, mes_num_raw, anio, hh, mm = m.groups()
            mes_num = str(int(mes_num_raw)).zfill(2)
        else:
            dia, mes_txt, anio, hh, mm = m.groups()
            mes_key = mes_txt.lower().replace(".", "")
            mes_num = MESES_ES.get(mes_key)
            if not mes_num:
                print("DEBUG Onebox mes no reconocido:", repr(mes_txt))
                return None

        return f"{anio}-{mes_num}-{dia.zfill(2)}", f"{int(hh):02d}:{mm}"

    return None


def extract_onebox_dates_from_text(text: str) -> list[str]:
    text = text.replace("\xa0", " ")
    text = " ".join(text.split())

    patterns = [
        r"(?:lun|mar|mi[eé]|jue|vie|s[aá]b|dom)\.?,?\s+\d{1,2}\s+(?:ene|feb|mar|abr|may|jun|jul|ago|sep|sept|oct|nov|dic|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+\d{4}\s*-\s*\d{1,2}:\d{2}",
        r"(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\.?,?\s+\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+\d{4}.*?\d{1,2}:\d{2}",
        r"\d{1,2}[/-]\d{1,2}[/-]\d{4}.*?\d{1,2}:\d{2}",
    ]

    out: list[str] = []
    for pat in patterns:
        out.extend(re.findall(pat, text, re.IGNORECASE))

    return out


def count_onebox_stock_playwright(page) -> tuple[int | None, int | None]:
    available_selectors = [
        ".seat.available",
        ".available",
        ".is-available",
        "[data-status='available']",
        "[data-state='available']",
        "[data-seat-status='available']",
        "[data-availability='available']",
        "button:not([disabled])[aria-label*='Asiento']",
        "button:not([disabled])[aria-label*='Butaca']",
        "button:not([disabled])[aria-label*='Seat']",
        "svg [role='button']:not([aria-disabled='true'])",
    ]

    total_selectors = [
        ".seat",
        "[data-seat-id]",
        "[data-place-id]",
        "[data-seat]",
        "button[aria-label*='Asiento']",
        "button[aria-label*='Butaca']",
        "button[aria-label*='Seat']",
        "svg [role='button']",
    ]

    stock = None
    capacidad = None

    for selector in available_selectors:
        try:
            n = page.locator(selector).count()
            if n:
                stock = n
                break
        except Exception:
            pass

    for selector in total_selectors:
        try:
            n = page.locator(selector).count()
            if n:
                capacidad = n
                break
        except Exception:
            pass

    return stock, capacidad


def extract_select_urls_from_html(html: str) -> list[str]:
    urls = set()

    for m in re.findall(r'https?://[^"\']+/select/\d+', html):
        urls.add(m)

    for m in re.findall(r'["\']([^"\']*/select/\d+)["\']', html):
        if m.startswith("http"):
            urls.add(m)
        elif m.startswith("/"):
            urls.add("https://entradas.laescaleradejacob.es" + m)

    for m in re.findall(r'\bselect/(\d+)\b', html):
        urls.add(f"https://entradas.laescaleradejacob.es/laescaleradejacob/select/{m}")

    return sorted(urls)


def save_debug_page(page, sala: str, label: str, select_url: str | None = None) -> None:
    DOCS_DIR.mkdir(exist_ok=True)

    clean_label = slugify(label)
    debug_html = DOCS_DIR / f"debug_onebox_{slugify(sala)}_{clean_label}.html"
    debug_txt = DOCS_DIR / f"debug_onebox_{slugify(sala)}_{clean_label}.txt"

    html = page.content()
    debug_html.write_text(html, "utf-8")

    try:
        body_text = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body_text = ""

    debug_txt.write_text(
        "SALA:\n"
        + sala
        + "\n\nSELECT URL:\n"
        + str(select_url or "")
        + "\n\nPAGE URL:\n"
        + page.url
        + "\n\nBODY:\n"
        + body_text[:15000]
        + "\n\nHTML_HEAD:\n"
        + html[:8000],
        "utf-8",
    )

    print(f"DEBUG guardado {debug_txt} y {debug_html}")


def get_onebox_select_urls(page, parent_url: str, sala: str) -> list[dict]:
    if "/select/" in parent_url:
        return [{"url": parent_url}]

    fallback = ONEBOX_FALLBACK_SELECTS.get(parent_url, [])

    fallback_by_url = {
        item["url"]: item
        for item in fallback
        if isinstance(item, dict) and item.get("url")
    }

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    for delay in [3000, 6000, 9000]:
        page.wait_for_timeout(delay)

        try:
            items = page.eval_on_selector_all(
                "a[href*='/select/']",
                """
                els => els.map(a => {
                    let txt = [];
                    let el = a;

                    for (let i = 0; i < 10 && el; i++, el = el.parentElement) {
                        txt.push(el.innerText || "");
                    }

                    return {
                        url: a.href,
                        text: txt.join("\\n")
                    };
                })
                """
            )
        except Exception:
            items = []

        out = []

        for item in items:
            h = item.get("url")
            txt = item.get("text") or ""

            if not h:
                continue

            data = fallback_by_url.get(h, {"url": h})

            fechas = extract_onebox_dates_from_text(txt)

            if fechas:
                parsed = parse_onebox_date(fechas[0])

                if parsed:
                    fecha_iso, hora = parsed

                    data = {
                        **data,
                        "fecha_iso": fecha_iso,
                        "hora": hora,
                    }

            out.append(data)

        if out:
            return out

    html = page.content()

    html_urls = extract_select_urls_from_html(html)

    if html_urls:
        out = []

        for h in html_urls:
            out.append(
                fallback_by_url.get(h, {"url": h})
            )

        return out

    print(f"⚠️ Onebox sin /select/ para {sala}")

    save_debug_page(
        page,
        sala,
        "parent_no_select",
        parent_url,
    )

    if fallback:
        print(f"⚠️ Usando fallback: {len(fallback)} URLs")
        return fallback

    return []


def fetch_functions_onebox(url: str, sala: str) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    cache = load_onebox_cache()
    cache_changed = False

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        page = browser.new_page(
            user_agent=UA["User-Agent"],
            viewport={"width": 1440, "height": 1100},
            locale="es-ES",
            timezone_id="Europe/Madrid",
        )

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"ERROR Onebox página padre {url}: {e}")
            browser.close()
            return []

        select_items = get_onebox_select_urls(page, url, sala)
        print(f"Onebox {sala} URLs detectadas: {len(select_items)}")

        for select_item in select_items:
            select_url = select_item["url"]
            select_id = select_url.rstrip("/").split("/")[-1]

            try:
                page.goto(select_url, wait_until="domcontentloaded", timeout=45000)

                try:
                    page.wait_for_selector(".seat, .available", timeout=15000)
                except Exception:
                    page.wait_for_timeout(5000)

                body_text = page.locator("body").inner_text(timeout=15000)
                date_texts = extract_onebox_dates_from_text(body_text)

                if date_texts:
                    parsed = parse_onebox_date(date_texts[0])
                    if not parsed:
                        print(f"DEBUG Onebox fecha no parseable: {date_texts[0]}")
                        save_debug_page(page, sala, f"select_{select_id}_fecha_no_parseable", select_url)
                        continue
                    fecha_iso, hora = parsed
                else:
                    fecha_iso = select_item.get("fecha_iso")
                    hora = select_item.get("hora")

                    if not fecha_iso or not hora:
                        print(f"DEBUG Onebox sin fecha visible y sin fallback: {select_url}")
                        save_debug_page(page, sala, f"select_{select_id}_sin_fecha", select_url)
                        continue

                key = (fecha_iso, hora)
                if key in seen:
                    continue

                seen.add(key)

                stock, capacidad = count_onebox_stock_playwright(page)
                cache_key = f"{fecha_iso}|{hora}|{select_url}"

                if stock is not None and capacidad is not None:
                    vendidas = max(0, capacidad - stock)
                    cache[cache_key] = {
                        "stock": stock,
                        "capacidad": capacidad,
                        "vendidas_dt": vendidas,
                        "updated_at": datetime.now(TZ).isoformat(),
                    }
                    cache_changed = True
                else:
                    old = cache.get(cache_key)
                    if old:
                        stock = old.get("stock")
                        capacidad = old.get("capacidad")
                        vendidas = old.get("vendidas_dt")
                        print(f"↩ Usando cache Onebox para {fecha_iso} {hora}: stock={stock}, cap={capacidad}")
                    else:
                        vendidas = None
                        print(f"⚠️ Sin stock Onebox ni cache para {fecha_iso} {hora}")
                        save_debug_page(page, sala, f"select_{select_id}_sin_stock", select_url)

                fecha_dt = datetime.strptime(fecha_iso, "%Y-%m-%d")
                fecha_label = fecha_dt.strftime("%d %b %Y")

                out.append({
                    "fecha_label": fecha_label,
                    "fecha_iso": fecha_iso,
                    "hora": hora,
                    "vendidas_dt": vendidas,
                    "capacidad": capacidad,
                    "stock": stock,
                    "buy_url": select_url,
                    "source": "onebox",
                })

            except Exception as e:
                print(f"ERROR Onebox select {select_url}: {e}")

        browser.close()

    if cache_changed:
        save_onebox_cache(cache)

    return sorted(out, key=lambda f: (f["fecha_iso"], f["hora"]))


def build_payload(eventos: dict[str, list[dict]]) -> dict:
    now = datetime.now(TZ)
    out: dict[str, dict] = {}

    headers = [
        "Fecha",
        "Hora",
        "Vendidas",
        "FechaISO",
        "Capacidad",
        "Stock",
        "BuyUrl",
        "Source",
    ]

    for sala, funcs in eventos.items():
        proximas: list[dict] = []

        for f in funcs:
            f["hora"] = normalize_hhmm(f.get("hora"))

            try:
                ses_dt = datetime.strptime(
                    f"{f['fecha_iso']} {f['hora']}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=TZ)
            except Exception:
                continue

            if ses_dt >= now:
                proximas.append(f)

        proximas.sort(key=lambda f: (f["fecha_iso"], f["hora"]))

        rows = [
            [
                f.get("fecha_label"),
                f.get("hora"),
                f.get("vendidas_dt"),
                f.get("fecha_iso"),
                f.get("capacidad"),
                f.get("stock"),
                f.get("buy_url"),
                f.get("source"),
            ]
            for f in proximas
        ]

        print(f"[DEBUG] {sala}: total={len(funcs)} próximas={len(proximas)}")

        out[sala] = {
            "table": {"headers": headers, "rows": rows},
            "proximas": {"table": {"headers": headers, "rows": rows}},
        }

    return {
        "generated_at": datetime.now(TZ).isoformat(),
        "eventos": out,
    }


if __name__ == "__main__":
    current: dict[str, list[dict]] = {}

    for sala, urls in DINATICKET_EVENTS.items():
        funcs: list[dict] = []
        for url in urls:
            try:
                funcs.extend(fetch_functions_dinaticket(url))
            except Exception as e:
                print(f"ERROR Dinaticket {sala}: {e}")

        current[sala] = funcs
        print(f"Dinaticket {sala}: {len(funcs)} funciones")

    for sala, url in ONEBOX_EVENTS.items():
        try:
            funcs = fetch_functions_onebox(url, sala)
        except Exception as e:
            print(f"ERROR Onebox {sala}: {e}")
            funcs = []

        current[sala] = funcs
        print(f"Onebox {sala}: {len(funcs)} funciones")

    payload = build_payload(current)

    write_html(payload)
    write_schedule_json(payload)
