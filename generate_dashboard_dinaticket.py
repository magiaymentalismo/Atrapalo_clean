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

# ===================== CONFIG ===================== #

EVENTS = {
    "Disfruta": "https://www.dinaticket.com/es/provider/10402/event/4905281",
    "Miedo": "https://www.dinaticket.com/es/provider/10402/event/4915778",
    "Escondido": "https://www.dinaticket.com/es/provider/20073/event/4930233",
}

FEVER_URLS = {
    "Miedo": "https://feverup.com/m/290561",
    "Disfruta": "https://feverup.com/m/159767",
}

ABONO_URL = "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=90857"

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
}

TZ = ZoneInfo("Europe/Madrid")

TEMPLATE_PATH = Path("template.html")
MANIFEST_PATH = Path("manifest.json")
SW_PATH = Path("sw.js")

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

def _walk_json(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_json(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _walk_json(x)

# ===================== HTML OUTPUT ===================== #

def write_html(payload: dict) -> None:
    html_template = TEMPLATE_PATH.read_text("utf-8")
    html = html_template.replace(
        "{{PAYLOAD_JSON}}",
        json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")
    )

    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)

    (docs_dir / "index.html").write_text(html, "utf-8")

    if MANIFEST_PATH.exists():
        shutil.copy(MANIFEST_PATH, docs_dir / "manifest.json")

    if SW_PATH.exists():
        shutil.copy(SW_PATH, docs_dir / "sw.js")

    print("✔ Generado docs/index.html")

def write_schedule_json(payload: dict) -> None:
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "schedule.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        "utf-8",
    )
    print("✔ Generado docs/schedule.json")

# ===================== DINATICKET ===================== #

def fetch_functions_dinaticket(url: str) -> list[dict]:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = []

    for session in soup.find_all("div", class_="js-session-row"):
        parent = session.find_parent("div", class_="js-session-group")
        if not parent:
            continue

        dia = parent.find("span", class_="num_dia")
        mes = parent.find("span", class_="mes")
        if not dia or not mes:
            continue

        mes_map = {
            "Ene": "01","Feb": "02","Mar": "03","Abr": "04","May": "05",
            "Jun": "06","Jul": "07","Ago": "08","Sep": "09","Oct": "10",
            "Nov": "11","Dic": "12"
        }

        mes_txt = mes.text.strip().replace(".", "")
        mes_num = mes_map.get(mes_txt)
        if not mes_num:
            continue

        now = datetime.now(TZ)
        anio = now.year

        fecha_iso = f"{anio}-{mes_num}-{dia.text.strip().zfill(2)}"
        fecha_label = datetime.strptime(fecha_iso,"%Y-%m-%d").strftime("%d %b %Y")

        hora_span = session.find("span", class_="session-card__time-session")
        hora = normalize_hhmm(hora_span.text if hora_span else "")

        quota = session.find("div", class_="js-quota-row")
        if not quota:
            continue

        cap = int(quota.get("data-quota-total", 0))
        stock = int(quota.get("data-stock", 0))
        vendidas = max(0, cap - stock)

        out.append({
            "fecha_label": fecha_label,
            "fecha_iso": fecha_iso,
            "hora": hora,
            "vendidas_dt": vendidas,
            "capacidad": cap,
            "stock": stock,
        })

    return out

# ===================== ABONO ===================== #

def fetch_abonoteatro_shows(url: str) -> set[tuple[str,str]]:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = set()

    for ses in soup.find_all("div", class_="bsesion"):
        if not ses.find("a", class_="buyBtn"):
            continue

        mes_tag = ses.find("p", class_="psess")
        dia_tag = ses.find("p", class_="psesb")
        hora_tag = ses.find("h3", class_="horasesion")

        if not (mes_tag and dia_tag and hora_tag):
            continue

        mes_nombre, anio = mes_tag.text.strip().lower().split()
        mes_map = {
            "enero":"01","febrero":"02","marzo":"03","abril":"04",
            "mayo":"05","junio":"06","julio":"07","agosto":"08",
            "septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"
        }

        mes_num = mes_map.get(mes_nombre)
        if not mes_num:
            continue

        dia = re.sub(r"\D","",dia_tag.text).zfill(2)
        hora_match = re.search(r"(\d{1,2}):(\d{2})", hora_tag.text)
        if not hora_match:
            continue

        hora = normalize_hhmm(f"{hora_match.group(1)}:{hora_match.group(2)}")
        fecha_iso = f"{anio}-{mes_num}-{dia}"

        out.add((fecha_iso, hora))

    return out

# ===================== FEVER (PLAYWRIGHT REAL) ===================== #

def fetch_fever_dates(url: str) -> set[str]:
    from playwright.sync_api import sync_playwright

    def extract(text: str):
        dates = set()
        dates |= set(re.findall(r'"(\d{4}-\d{2}-\d{2})"', text))
        dates |= set(re.findall(r'(20\d{2}-\d{2}-\d{2})T\d{2}:\d{2}', text))
        return dates

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        html = page.content()
        dates = extract(html)

        try:
            data = page.evaluate("() => window.__NEXT_DATA__ || window.__NUXT__ || null")
            if data:
                blob = json.dumps(data)
                dates |= extract(blob)
        except:
            pass

        browser.close()
        return dates

# ===================== BUILD PAYLOAD ===================== #

def build_payload(eventos, abono_shows):
    now = datetime.now(TZ)
    out = {}

    for sala, funcs in eventos.items():

        if sala in FEVER_URLS:
            fever_dates = fetch_fever_dates(FEVER_URLS[sala])
        else:
            fever_dates = set()

        proximas = []

        for f in funcs:
            f["hora"] = normalize_hhmm(f["hora"])

            if sala == "Escondido":
                f["abono_estado"] = (
                    "venta" if (f["fecha_iso"],f["hora"]) in abono_shows else "agotado"
                )
            else:
                f["abono_estado"] = None

            f["fever_estado"] = (
                "venta" if f["fecha_iso"] in fever_dates else "agotado"
            )

            ses_dt = datetime.strptime(
                f"{f['fecha_iso']} {f['hora']}",
                "%Y-%m-%d %H:%M"
            ).replace(tzinfo=TZ)

            if ses_dt >= now:
                proximas.append(f)

        rows = [
            [
                f["fecha_label"],f["hora"],f["vendidas_dt"],f["fecha_iso"],
                f["capacidad"],f["stock"],f["abono_estado"],f["fever_estado"]
            ]
            for f in proximas
        ]

        headers = ["Fecha","Hora","Vendidas","FechaISO","Capacidad","Stock","Abono","Fever"]

        out[sala] = {
            "table":{"headers":headers,"rows":rows},
            "proximas":{"table":{"headers":headers,"rows":rows}}
        }

    return {
        "generated_at": datetime.now(TZ).isoformat(),
        "eventos": out,
    }

# ===================== MAIN ===================== #

if __name__ == "__main__":
    current = {}

    for sala, url in EVENTS.items():
        funcs = fetch_functions_dinaticket(url)
        current[sala] = funcs
        print(f"{sala}: {len(funcs)} funciones")

    abono_shows = fetch_abonoteatro_shows(ABONO_URL)
    print("AbonoTeatro:", len(abono_shows))

    payload = build_payload(current, abono_shows)
    write_html(payload)
    write_schedule_json(payload)