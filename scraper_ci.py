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

# ===================== CONFIG ===================== #

DINATICKET_EVENTS = {
    "Disfruta": ["https://www.dinaticket.com/es/provider/20864/event/4947155"],
    "Escondi2": ["https://www.dinaticket.com/es/provider/20864/event/4943466"],
    "CluedoMental": ["https://www.dinaticket.com/es/provider/10402/event/4948503"],
}

ONEBOX_EVENTS = {
    "Miedo": "https://entradas.laescaleradejacob.es/laescaleradejacob/events/56108",
}

# Respaldo por si Onebox no pinta los enlaces /select/ en GitHub Actions.
ONEBOX_FALLBACK_SELECTS = {
    "https://entradas.laescaleradejacob.es/laescaleradejacob/events/56108": [
        "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2904525",
        "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2904526",
        "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2904527",
        "https://entradas.laescaleradejacob.es/laescaleradejacob/select/2904528",
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


# ===================== HELPERS ===================== #

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


# ===================== OUTPUT ===================== #

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


# ===================== DINATICKET ===================== #

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


# ===================== ONEBOX ===================== #

def parse_onebox_date(raw: str) -> tuple[str, str] | None:
    raw = raw.replace("\xa0", " ")
    raw = " ".join(raw.split()).lower()

    m = re.search(
        r"(?:lun|mar|mi[eé]|jue|vie|s[aá]b|dom)\.?,?\s+"
        r"(\d{1,2})\s+([a-záéíóúñ]+)\s+(\d{4})\s*-\s*(\d{1,2}):(\d{2})",
        raw,
        re.IGNORECASE,
    )

    if not m:
        return None

    dia, mes_txt, anio, hh, mm = m.groups()
    mes_key = mes_txt.lower().replace(".", "")
    mes_num = MESES_ES.get(mes_key)

    if not mes_num:
        print("DEBUG Onebox mes no reconocido:", repr(mes_txt))
        return None

    fecha_iso = f"{anio}-{mes_num}-{dia.zfill(2)}"
    hora = f"{int(hh):02d}:{mm}"

    return fecha_iso, hora


def extract_onebox_dates_from_text(text: str) -> list[str]:
    text = text.replace("\xa0", " ")
    text = " ".join(text.split())

    pattern = re.compile(
        r"(?:lun|mar|mi[eé]|jue|vie|s[aá]b|dom)\.?,?\s+"
        r"\d{1,2}\s+"
        r"(?:ene|feb|mar|abr|may|jun|jul|ago|sep|sept|oct|nov|dic|"
        r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|octubre|noviembre|diciembre)"
        r"\s+\d{4}\s*-\s*\d{1,2}:\d{2}",
        re.IGNORECASE,
    )

    return pattern.findall(text)


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


def get_onebox_select_urls(page, parent_url: str) -> list[str]:
    if "/select/" in parent_url:
        return [parent_url]

    hrefs = []

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    for delay in [2000, 4000, 6000]:
        page.wait_for_timeout(delay)

        try:
            hrefs = page.eval_on_selector_all(
                "a[href]",
                """els => els.map(a => a.href).filter(h => h.includes('/select/'))"""
            )
        except Exception:
            hrefs = []

        hrefs = sorted(set(hrefs))

        if hrefs:
            return hrefs

    fallback = ONEBOX_FALLBACK_SELECTS.get(parent_url, [])
    if fallback:
        print(f"⚠️ Onebox sin enlaces dinámicos; usando fallback: {len(fallback)} URLs")
        return fallback

    return []


def fetch_functions_onebox(url: str) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

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

        select_urls = get_onebox_select_urls(page, url)
        print(f"Onebox URLs detectadas: {len(select_urls)}")

        for select_url in select_urls:
            try:
                page.goto(select_url, wait_until="domcontentloaded", timeout=45000)

                try:
                    page.wait_for_selector(".seat, .available", timeout=15000)
                except Exception:
                    page.wait_for_timeout(5000)

                body_text = page.locator("body").inner_text(timeout=15000)
                date_texts = extract_onebox_dates_from_text(body_text)

                if not date_texts:
                    print(f"DEBUG Onebox sin fecha visible: {select_url}")
                    continue

                for raw_date in date_texts:
                    parsed = parse_onebox_date(raw_date)
                    if not parsed:
                        continue

                    fecha_iso, hora = parsed
                    key = (fecha_iso, hora)

                    if key in seen:
                        continue

                    seen.add(key)

                    stock, capacidad = count_onebox_stock_playwright(page)

                    vendidas = (
                        max(0, capacidad - stock)
                        if stock is not None and capacidad is not None
                        else None
                    )

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

    return sorted(out, key=lambda f: (f["fecha_iso"], f["hora"]))


# ===================== PAYLOAD ===================== #

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


# ===================== MAIN ===================== #

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
            funcs = fetch_functions_onebox(url)
        except Exception as e:
            print(f"ERROR Onebox {sala}: {e}")
            funcs = []

        current[sala] = funcs
        print(f"Onebox {sala}: {len(funcs)} funciones")

    payload = build_payload(current)

    write_html(payload)
    write_schedule_json(payload)
