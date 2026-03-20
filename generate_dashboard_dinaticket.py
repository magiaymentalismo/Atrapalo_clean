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
    "Escondi2": "https://www.dinaticket.com/es/provider/20864/event/4943466",
}

# AbonoTeatro por sala
ABONO_URLS = {
    "Escondido": "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=90857",
    "Disfruta": "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=57914",
}

# Kultur: solo para las que tengan link (por ahora Miedo + Escondido)
KULTUR_URLS = {
    "Miedo": "https://appkultur.com/madrid/miedo-mentalismo-y-espiritismo-con-ariel-hamui",
    "Escondido": "https://appkultur.com/madrid/el-juego-de-la-mente-magia-mental-con-ariel-hamui",
    # "Disfruta": (no tiene por ahora)
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


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _walk(x)


def _try_get(d: dict, keys: list[str]):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _iso_date_from_any(x) -> str | None:
    if not x:
        return None
    s = str(x)
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", s)
    return m.group(1) if m else None


def _hhmm_from_any(x) -> str | None:
    if not x:
        return None
    s = str(x)
    m = re.search(r"\b([0-2]?\d):([0-5]\d)\b", s)
    if not m:
        return None
    return normalize_hhmm(f"{m.group(1)}:{m.group(2)}")


# ===================== HTML OUTPUT ===================== #

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

        mes_map = {
            "Ene": "01", "Feb": "02", "Mar": "03", "Abr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Ago": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dic": "12",
        }

        mes_txt = mes.text.strip().replace(".", "")
        mes_num = mes_map.get(mes_txt)
        if not mes_num:
            continue

        now = datetime.now(TZ)
        anio = now.year

        fecha_iso = f"{anio}-{mes_num}-{dia.text.strip().zfill(2)}"
        fecha_label = datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d %b %Y")

        hora_span = session.find("span", class_="session-card__time-session")
        hora = normalize_hhmm(hora_span.text if hora_span else "")

        quota = session.find("div", class_="js-quota-row")
        if not quota:
            continue

        cap = int(quota.get("data-quota-total", 0))
        stock = int(quota.get("data-stock", 0))
        vendidas = max(0, cap - stock)

        out.append(
            {
                "fecha_label": fecha_label,
                "fecha_iso": fecha_iso,
                "hora": hora,
                "vendidas_dt": vendidas,
                "capacidad": cap,
                "stock": stock,
            }
        )

    return out


# ===================== ABONO ===================== #

def fetch_abonoteatro_shows(url: str) -> set[tuple[str, str]]:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out: set[tuple[str, str]] = set()

    # ---------- 1) Formato antiguo ----------
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

        mes_map = {
            "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
            "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
            "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
        }

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

    if out:
        return out

    # ---------- 2) Formato nuevo ----------
    mes_map = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }
    dow = r"(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"

    comprar_links = soup.find_all(
        "a", string=lambda s: s and s.strip().lower() == "comprar"
    )

    for a in comprar_links:
        block = a.find_parent(["article", "section", "div"])
        if not block:
            block = a.parent

        t = block.get_text(" ", strip=True).lower()

        m_my = re.search(
            r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(20\d{2})\b",
            t,
        )
        if not m_my:
            continue
        mes_nombre, anio = m_my.group(1), m_my.group(2)
        mes_num = mes_map.get(mes_nombre)
        if not mes_num:
            continue

        m_day = re.search(r"\b([0-3]?\d)\b\s+" + dow + r"\b", t)
        if not m_day:
            continue
        dia = str(int(m_day.group(1))).zfill(2)

        m_time = re.search(r"\b([0-2]?\d):([0-5]\d)\b", t)
        if not m_time:
            continue
        hora = normalize_hhmm(f"{m_time.group(1)}:{m_time.group(2)}")

        fecha_iso = f"{anio}-{mes_num}-{dia}"
        out.add((fecha_iso, hora))

    return out


# ===================== KULTUR (PLAYWRIGHT -> CACHE) ===================== #

def extract_kultur_idx_from_json(blob) -> dict[str, dict]:
    """
    Intenta armar idx:
      'YYYY-MM-DD|HH:MM' -> {capacidad, stock, vendidas}
    desde cualquier JSON capturado en red.
    """
    idx: dict[str, dict] = {}

    for d in _walk(blob):
        if not isinstance(d, dict):
            continue

        date_raw = _try_get(d, ["date", "day", "startDate", "start_date", "sessionDate", "session_date", "datetime", "start", "startsAt", "start_at"])
        time_raw = _try_get(d, ["time", "hour", "startTime", "start_time", "sessionTime", "session_time", "startsAt", "start_at"])

        fecha_iso = _iso_date_from_any(date_raw)
        hora = _hhmm_from_any(time_raw)

        if (not fecha_iso or not hora) and date_raw:
            fecha_iso2 = _iso_date_from_any(date_raw)
            hora2 = _hhmm_from_any(date_raw)
            fecha_iso = fecha_iso or fecha_iso2
            hora = hora or hora2

        if not fecha_iso or not hora:
            continue

        cap = _try_get(d, ["capacidad", "capacity", "totalCapacity", "total_capacity", "total", "max", "maxCapacity", "max_capacity"])
        stock = _try_get(d, ["stock", "available", "availability", "remaining", "left", "spotsLeft", "spots_left"])
        sold = _try_get(d, ["vendidas", "sold", "booked", "reserved", "ticketsSold", "tickets_sold"])

        try:
            cap_i = int(cap) if cap is not None else None
        except Exception:
            cap_i = None

        try:
            stock_i = int(stock) if stock is not None else None
        except Exception:
            stock_i = None

        try:
            sold_i = int(sold) if sold is not None else None
        except Exception:
            sold_i = None

        if sold_i is None and cap_i is not None and stock_i is not None:
            sold_i = max(0, cap_i - stock_i)

        if stock_i is None and cap_i is not None and sold_i is not None:
            stock_i = max(0, cap_i - sold_i)

        if cap_i is None or sold_i is None:
            continue

        key = f"{fecha_iso}|{hora}"
        idx[key] = {"capacidad": cap_i, "stock": stock_i, "vendidas": sold_i}

    return idx


def fetch_and_write_kultur_cache(sala: str, url: str) -> dict:
    """
    Abre Kultur con Playwright, captura respuestas JSON,
    extrae sesiones y escribe docs/kultur_cache_{Sala}.json
    """
    from playwright.sync_api import sync_playwright

    DOCS_DIR.mkdir(exist_ok=True)

    all_json = []
    idx: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        def on_response(resp):
            try:
                ct = (resp.headers.get("content-type") or "").lower()
                if "application/json" in ct:
                    all_json.append(resp.json())
            except Exception:
                pass

        page.on("response", on_response)

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        browser.close()

    for blob in all_json:
        part = extract_kultur_idx_from_json(blob)
        if part:
            idx.update(part)

    data = {"idx": idx}
    out_path = DOCS_DIR / f"kultur_cache_{sala}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    print(f"✔ Generado {out_path} (keys: {len(idx)})")

    return data


def load_kultur_cache(sala: str) -> dict:
    p = DOCS_DIR / f"kultur_cache_{sala}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}


# ===================== BUILD PAYLOAD ===================== #

def build_payload(eventos: dict[str, list[dict]], abono_by_sala: dict[str, set[tuple[str, str]]]) -> dict:
    now = datetime.now(TZ)
    out: dict[str, dict] = {}

    for sala, funcs in eventos.items():
        # ABONO
        abono_shows = abono_by_sala.get(sala, set())
        has_abono = sala in abono_by_sala

        # KULTUR
        kultur_cache = load_kultur_cache(sala) if sala in KULTUR_URLS else {}
        kultur_idx = (kultur_cache.get("idx") or {}) if isinstance(kultur_cache, dict) else {}

        proximas: list[dict] = []

        for f in funcs:
            f["hora"] = normalize_hhmm(f.get("hora"))

            # abono
            f["abono_estado"] = (
                "venta" if (f["fecha_iso"], f["hora"]) in abono_shows else "agotado"
            ) if has_abono else None

            # kultur: vendidas/capacidad
            k_key = f"{f['fecha_iso']}|{f['hora']}"
            k = kultur_idx.get(k_key) or {}
            f["kultur_vendidas"] = k.get("vendidas")
            f["kultur_capacidad"] = k.get("capacidad")

            ses_dt = datetime.strptime(
                f"{f['fecha_iso']} {f['hora']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=TZ)

            if ses_dt >= now:
                proximas.append(f)

        # 9 columnas: Dina + Abono + Kultur vend/cap
        rows = [
            [
                f["fecha_label"],
                f["hora"],
                f["vendidas_dt"],
                f["fecha_iso"],
                f["capacidad"],
                f["stock"],
                f["abono_estado"],
                f.get("kultur_vendidas"),
                f.get("kultur_capacidad"),
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
            "KulturVendidas",
            "KulturCapacidad",
        ]

        out[sala] = {
            "table": {"headers": headers, "rows": rows},
            "proximas": {"table": {"headers": headers, "rows": rows}},
        }

    return {"generated_at": datetime.now(TZ).isoformat(), "eventos": out}


# ===================== MAIN ===================== #

if __name__ == "__main__":
    current: dict[str, list[dict]] = {}

    for sala, url in EVENTS.items():
        funcs = fetch_functions_dinaticket(url)
        current[sala] = funcs
        print(f"{sala}: {len(funcs)} funciones")

    abono_by_sala: dict[str, set[tuple[str, str]]] = {}
    for sala, url in ABONO_URLS.items():
        shows = fetch_abonoteatro_shows(url)
        abono_by_sala[sala] = shows
        print(f"AbonoTeatro {sala}: {len(shows)}")

    # KULTUR: generar caches automáticamente
    for sala, url in KULTUR_URLS.items():
        try:
            fetch_and_write_kultur_cache(sala, url)
        except Exception as e:
            print(f"⚠️ Kultur {sala}: fallo al generar cache ({e})")

    payload = build_payload(current, abono_by_sala)
    write_html(payload)
    write_schedule_json(payload)