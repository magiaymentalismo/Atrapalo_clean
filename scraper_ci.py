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

EVENTS = {
    "Disfruta": ["https://www.dinaticket.com/es/provider/20864/event/4947155"],
    "Escondi2": ["https://www.dinaticket.com/es/provider/20864/event/4943466"],
    "CluedoMental": ["https://www.dinaticket.com/es/provider/10402/event/4948503"],
}

ONEBOX_EVENTS = {
    "Miedo": "https://entradas.laescaleradejacob.es/laescaleradejacob/events/56108",
}

ABONO_URLS = {
    "Disfruta": "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=57914",
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


def write_html(payload: dict) -> None:
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

    mes_map = {
        "Ene": "01", "Feb": "02", "Mar": "03", "Abr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Ago": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dic": "12",
    }

    for session in soup.find_all("div", class_="js-session-row"):
        parent = session.find_parent("div", class_="js-session-group")
        if not parent:
            continue

        dia = parent.find("span", class_="num_dia")
        mes = parent.find("span", class_="mes")
        if not dia or not mes:
            continue

        mes_txt = mes.text.strip().replace(".", "")
        mes_num = mes_map.get(mes_txt)
        if not mes_num:
            continue

        now = datetime.now(TZ)
        anio = now.year

        fecha_tmp = datetime.strptime(
            f"{anio}-{mes_num}-{dia.text.strip().zfill(2)}",
            "%Y-%m-%d",
        )

        if fecha_tmp.date() < now.date():
            fecha_tmp = fecha_tmp.replace(year=anio + 1)

        fecha_iso = fecha_tmp.strftime("%Y-%m-%d")
        fecha_label = fecha_tmp.strftime("%d %b %Y")

        hora_span = session.find("span", class_="session-card__time-session")
        hora = normalize_hhmm(hora_span.text if hora_span else "")

        quotas = session.find_all("div", class_="js-quota-row")

        if not quotas:
            cap, stock, vendidas = None, None, None
        else:
            cap = sum(int(q.get("data-quota-total", 0)) for q in quotas)
            stock = sum(int(q.get("data-stock", 0)) for q in quotas)
            vendidas = max(0, cap - stock)

        out.append({
            "fecha_label": fecha_label,
            "fecha_iso": fecha_iso,
            "hora": hora,
            "vendidas_dt": vendidas,
            "capacidad": cap,
            "stock": stock,
        })

    return sorted(out, key=lambda f: (f["fecha_iso"], f["hora"]))


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
        print("DEBUG mes Onebox no reconocido:", repr(mes_txt))
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
        "[data-status='available']",
        "[data-state='available']",
        "[data-seat-status='available']",
        "[data-availability='available']",
        ".available",
        ".is-available",
        ".seat.available",
        "button:not([disabled])[aria-label*='Asiento']",
        "button:not([disabled])[aria-label*='Butaca']",
        "button:not([disabled])[aria-label*='Seat']",
        "svg [role='button']:not([aria-disabled='true'])",
    ]

    total_selectors = [
        "[data-seat-id]",
        "[data-place-id]",
        "[data-seat]",
        ".seat",
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
            print(f"DEBUG AVAILABLE {selector} -> {n}")
            if n:
                stock = n
                break
        except Exception:
            pass

    for selector in total_selectors:
        try:
            n = page.locator(selector).count()
            print(f"DEBUG TOTAL {selector} -> {n}")
            if n:
                capacidad = n
                break
        except Exception:
            pass

    return stock, capacidad


def get_onebox_select_urls(page, parent_url: str) -> list[str]:
    if "/select/" in parent_url:
        return [parent_url]

    hrefs = page.eval_on_selector_all(
        "a[href]",
        """els => els.map(a => a.href).filter(h => h.includes('/select/'))"""
    )

    return sorted(set(hrefs))


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
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"ERROR Onebox página padre {url}: {e}")
            browser.close()
            return []

        select_urls = get_onebox_select_urls(page, url)
        print("DEBUG Onebox select URLs:", select_urls)

        for select_url in select_urls:
            try:
                page.goto(select_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)

                body_text = page.locator("body").inner_text(timeout=15000)
                date_texts = extract_onebox_dates_from_text(body_text)

                print("DEBUG Onebox fechas en", select_url, ":", date_texts)

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
                    })

            except Exception as e:
                print(f"ERROR Onebox select {select_url}: {e}")

        browser.close()

    return sorted(out, key=lambda f: (f["fecha_iso"], f["hora"]))


def fetch_abonoteatro_shows(url: str) -> set[tuple[str, str]]:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out: set[tuple[str, str]] = set()

    mes_map = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }

    for ses in soup.find_all("div", class_="bsesion"):
        if not ses.find("a", class_="buyBtn"):
            continue

        mes_tag = ses.find("p", class_="psess")
        dia_tag = ses.find("p", class_="psesb")
        hora_tag = ses.find("h3", class_="horasesion")

        if not (mes_tag and dia_tag and hora_tag):
            continue

        parts = mes_tag.text.strip().lower().split()
        if len(parts) < 2:
            continue

        mes_nombre, anio = parts[0], parts[1]
        mes_num = mes_map.get(mes_nombre)

        if not mes_num:
            continue

        dia = re.sub(r"\D", "", dia_tag.text).zfill(2)

        hora_match = re.search(r"(\d{1,2}):(\d{2})", hora_tag.text)
        if not hora_match:
            continue

        hora = normalize_hhmm(f"{hora_match.group(1)}:{hora_match.group(2)}")
        fecha_iso = f"{anio}-{mes_num}-{dia}"

        out.add((fecha_iso, hora))

    return out


def build_payload(
    eventos: dict[str, list[dict]],
    abono_by_sala: dict[str, set[tuple[str, str]]],
) -> dict:
    now = datetime.now(TZ)
    out: dict[str, dict] = {}

    for sala, funcs in eventos.items():
        abono_shows = abono_by_sala.get(sala, set())
        has_abono = sala in abono_by_sala

        proximas: list[dict] = []

        for f in funcs:
            f["hora"] = normalize_hhmm(f.get("hora"))

            f["abono_estado"] = (
                "venta" if (f["fecha_iso"], f["hora"]) in abono_shows else "agotado"
            ) if has_abono else None

            ses_dt = datetime.strptime(
                f"{f['fecha_iso']} {f['hora']}",
                "%Y-%m-%d %H:%M",
            ).replace(tzinfo=TZ)

            if ses_dt >= now:
                proximas.append(f)

        proximas.sort(key=lambda f: (f["fecha_iso"], f["hora"]))

        rows = [
            [
                f["fecha_label"],
                f["hora"],
                f["vendidas_dt"],
                f["fecha_iso"],
                f["capacidad"],
                f["stock"],
                f["abono_estado"],
            ]
            for f in proximas
        ]

        headers = [
            "Fecha",
            "Hora",
            "Vendidas",
            "FechaISO",
            "Capacidad",
            "Stock",
            "Abono",
        ]

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

    for sala, urls in EVENTS.items():
        funcs: list[dict] = []

        for url in urls:
            try:
                funcs.extend(fetch_functions_dinaticket(url))
            except Exception as e:
                print(f"ERROR Dinaticket {sala}: {e}")

        current[sala] = funcs
        print(f"Dina {sala}: {len(funcs)} funciones")

    for sala, url in ONEBOX_EVENTS.items():
        try:
            funcs = fetch_functions_onebox(url)
        except Exception as e:
            print(f"ERROR Onebox {sala}: {e}")
            funcs = []

        current[sala] = funcs
        print(f"Onebox {sala}: {len(funcs)} funciones")
        print(f"DEBUG Onebox {sala} funcs:", funcs)

    abono_by_sala: dict[str, set[tuple[str, str]]] = {}

    for sala, url in ABONO_URLS.items():
        try:
            shows = fetch_abonoteatro_shows(url)
        except Exception as e:
            print(f"ERROR Abono {sala}: {e}")
            shows = set()

        abono_by_sala[sala] = shows
        print(f"Abono {sala}: {len(shows)}")

    payload = build_payload(current, abono_by_sala)
    write_html(payload)
    write_schedule_json(payload)
