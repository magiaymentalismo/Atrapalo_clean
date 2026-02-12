#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timedelta
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
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
        "AppleWebKit/537.36 (KHTML, como Gecko) Chrome/123 Safari/537.36"
    )
}

# -------------------- KULTUR -------------------- #
# Página: https://appkultur.com/madrid/el-juego-de-la-mente-magia-mental-con-ariel-hamui
KULTUR_EVENT_ID_ESCONDIDO = "YaWZRG4MCxo1CHvr"

# Usamos getSessions (más directo y suele responder mejor que getCalendar)
KULTUR_SESSIONS_API = "https://europe-west6-kultur-platform.cloudfunctions.net/events_api_v2-getSessions"

# Token AppCheck desde env / GitHub Secrets
KULTUR_APPCHECK = os.getenv("KULTUR_APPCHECK")

# DEBUG: poner a "1" para imprimir un sample del JSON de Kultur (sin token)
DEBUG_KULTUR = os.getenv("DEBUG_KULTUR", "0") == "1"

# Dinaticket suele usar abreviaturas tipo "Ene." pero a veces aparece sin punto.
MESES = {
    "Ene.": "01", "Ene": "01",
    "Feb.": "02", "Feb": "02",
    "Mar.": "03", "Mar": "03",
    "Abr.": "04", "Abr": "04",
    "May.": "05", "May": "05",
    "Jun.": "06", "Jun": "06",
    "Jul.": "07", "Jul": "07",
    "Ago.": "08", "Ago": "08",
    "Sep.": "09", "Sep": "09",
    "Oct.": "10", "Oct": "10",
    "Nov.": "11", "Nov": "11",
    "Dic.": "12", "Dic": "12",
}

# Meses largos que usa AbonoTeatro ("noviembre 2025", etc.)
MESES_LARGO = {
    "enero": "01",
    "febrero": "02",
    "marzo": "03",
    "abril": "04",
    "mayo": "05",
    "junio": "06",
    "julio": "07",
    "agosto": "08",
    "septiembre": "09",
    "octubre": "10",
    "noviembre": "11",
    "diciembre": "12",
}

TZ = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")

# ================== TEMPLATE (HTML) ================== #
TEMPLATE_PATH = Path("template.html")
MANIFEST_PATH = Path("manifest.json")
SW_PATH = Path("sw.js")


# ================== GENERATE HTML ================== #
def write_html(payload: dict) -> None:
    if not TEMPLATE_PATH.exists():
        print("❌ Error: No existe template.html")
        return

    html_template = TEMPLATE_PATH.read_text("utf-8")
    html = html_template.replace(
        "{{PAYLOAD_JSON}}",
        json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")
    )

    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)

    (docs_dir / "index.html").write_text(html, "utf-8")
    print("✔ Generado docs/index.html")

    if MANIFEST_PATH.exists():
        shutil.copy(MANIFEST_PATH, docs_dir / "manifest.json")
        print("✔ Copiado manifest.json")

    if SW_PATH.exists():
        shutil.copy(SW_PATH, docs_dir / "sw.js")
        print("✔ Copiado sw.js")


def write_schedule_json(payload: dict) -> None:
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)

    (docs_dir / "schedule.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        "utf-8",
    )
    print("✔ Generado docs/schedule.json")


# ================== SCRAPER DINATICKET ================== #
def fetch_functions_dinaticket(url: str, timeout: int = 20) -> list[dict]:
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out: list[dict] = []

    for session in soup.find_all("div", class_="js-session-row"):
        parent = session.find_parent("div", class_="js-session-group")
        if not parent:
            continue

        date_div = parent.find("div", class_="session-card__date")
        if not date_div:
            continue

        dia = date_div.find("span", class_="num_dia")
        mes = date_div.find("span", class_="mes")
        if not (dia and mes):
            continue

        mes_txt = mes.text.strip()
        mes_num = MESES.get(mes_txt) or MESES.get(mes_txt.replace(".", ""))
        if not mes_num:
            print("DEBUG mes no reconocido Dinaticket:", repr(mes_txt))
            continue

        now = datetime.now(TZ)
        anio = now.year

        fecha_iso_tmp = f"{anio}-{mes_num}-{dia.text.strip().zfill(2)}"
        fecha_dt = datetime.strptime(fecha_iso_tmp, "%Y-%m-%d")

        if fecha_dt.date() < now.date():
            fecha_dt = fecha_dt.replace(year=anio + 1)

        fecha_iso = fecha_dt.strftime("%Y-%m-%d")
        fecha_label = fecha_dt.strftime("%d %b %Y")

        hora_span = session.find("span", class_="session-card__time-session")
        hora_txt = (hora_span.text or "").strip().lower().replace(" ", "").replace("h", ":")

        m = re.match(r"^(\d{1,2})(?::?(\d{2}))?$", hora_txt)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2) or "00")
            hora = f"{hh:02d}:{mm:02d}"
        else:
            hora = hora_txt

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


# ================== SCRAPER ABONOTEATRO ================== #
def fetch_abonoteatro_shows(url: str, timeout: int = 20) -> set[tuple[str, str]]:
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out: set[tuple[str, str]] = set()

    sesiones = soup.find_all("div", class_="bsesion")
    for ses in sesiones:
        if not ses.find("a", class_="buyBtn"):
            continue

        fecha_div = ses.find("div", class_="bfechasesion")
        if not fecha_div:
            continue

        mes_y_anio_tag = fecha_div.find("p", class_="psess")
        if not mes_y_anio_tag:
            continue

        raw = mes_y_anio_tag.get_text(strip=True).lower()
        m_ma = re.match(r"^([a-záéíóúñ]+)\s+(\d{4})$", raw)
        if not m_ma:
            print("DEBUG mes/año raro en AbonoTeatro:", repr(raw))
            continue

        mes_nombre = m_ma.group(1)
        anio = m_ma.group(2)
        mes_num = MESES_LARGO.get(mes_nombre)
        if not mes_num:
            print("DEBUG mes desconocido:", mes_nombre)
            continue

        dia_tag = fecha_div.find("p", class_="psesb")
        if not dia_tag:
            continue
        dia_num = re.sub(r"\D", "", dia_tag.get_text(strip=True)).zfill(2)

        hora_h3 = ses.find("h3", class_="horasesion")
        if not hora_h3:
            continue

        hora_txt = hora_h3.get_text(" ", strip=True)
        m_hora = re.search(r"(\d{1,2}):(\d{2})", hora_txt)
        if not m_hora:
            print("DEBUG hora rara:", repr(hora_txt))
            continue

        hh = m_hora.group(1).zfill(2)
        mm = m_hora.group(2).zfill(2)
        hora = f"{hh}:{mm}"

        fecha_iso = f"{anio}-{mes_num}-{dia_num}"
        out.add((fecha_iso, hora))

    print("DEBUG AbonoTeatro fechas/hora:", sorted(out))
    return out


# ================== FEVER (SIN PLAYWRIGHT) ================== #
def fetch_fever_dates(url: str, timeout: int = 15) -> set[str]:
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        r.raise_for_status()

        m = re.search(r'"datesWithSessions"\s*:\s*\[(.*?)\]', r.text)
        if not m:
            return set()

        raw = m.group(1)
        fechas = re.findall(r'"(\d{4}-\d{2}-\d{2})"', raw)
        return set(fechas)

    except Exception as e:
        print(f"ERROR Fever scraping {url}: {e}")
        return set()


# ================== KULTUR helpers ================== #
def _walk_json(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_json(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _walk_json(x)

def _parse_iso_any(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None

def _extract_kultur_cap_stock(d: dict) -> tuple[int | None, int | None]:
    cap_keys = ("capacity", "totalCapacity", "maxCapacity", "totalTickets", "quota", "maxTickets", "cap")
    stock_keys = ("available", "availability", "remaining", "ticketsAvailable", "stock", "left")

    cap = next((d.get(k) for k in cap_keys if isinstance(d.get(k), (int, float))), None)
    stock = next((d.get(k) for k in stock_keys if isinstance(d.get(k), (int, float))), None)

    stats = d.get("stats")
    if isinstance(stats, dict):
        if cap is None:
            cap = next((stats.get(k) for k in cap_keys if isinstance(stats.get(k), (int, float))), None)
        if stock is None:
            stock = next((stats.get(k) for k in stock_keys if isinstance(stats.get(k), (int, float))), None)

    return (int(cap) if cap is not None else None, int(stock) if stock is not None else None)

def _extract_dt_from_dict(d: dict) -> datetime | None:
    # Intentamos muchas claves comunes
    for k in (
        "start", "startAt", "dateTime", "datetime", "startDate",
        "startsAt", "start_time", "startTime", "begin", "beginAt",
        "sessionStart", "sessionStartAt",
    ):
        s = d.get(k)
        if isinstance(s, str) and s:
            dt = _parse_iso_any(s)
            if dt:
                return dt

    # A veces viene como {"start": {"_seconds": ...}} (Firestore)
    for k in ("start", "startAt", "startTime", "dateTime"):
        v = d.get(k)
        if isinstance(v, dict) and "_seconds" in v:
            try:
                secs = int(v["_seconds"])
                return datetime.fromtimestamp(secs, tz=UTC).astimezone(TZ)
            except Exception:
                pass

    return None


# ================== KULTUR (getSessions) ================== #
def fetch_kultur_sessions_capacity(event_id: str, days: int = 30) -> dict[tuple[str, str], dict]:
    if not KULTUR_APPCHECK:
        print("⚠️ KULTUR token present: False (secret no configurado)")
        return {}

    print("KULTUR token present:", True)

    headers = {
        **UA,
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://appkultur.com",
        "referer": "https://appkultur.com/",
        "x-firebase-appcheck": KULTUR_APPCHECK,
    }

    now = datetime.now(TZ)
    out: dict[tuple[str, str], dict] = {}

    for i in range(days):
        day = (now + timedelta(days=i)).date()
        from_dt = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=TZ).astimezone(UTC)
        to_dt = from_dt + timedelta(days=1)

        payload = {
            "data": {
                "eventId": event_id,
                "from": from_dt.isoformat().replace("+00:00", "Z"),
                "to": to_dt.isoformat().replace("+00:00", "Z"),
            }
        }

        data = None
        for attempt in range(1, 3):
            try:
                r = requests.post(
                    KULTUR_SESSIONS_API,
                    headers=headers,
                    json=payload,
                    timeout=(10, 25),
                )
                if r.status_code in (401, 403):
                    print("⚠️ Kultur 401/403 (token inválido/expirado)")
                    return {}
                r.raise_for_status()
                data = r.json()
                break
            except requests.exceptions.ReadTimeout:
                if attempt == 2:
                    print(f"⚠️ Kultur timeout en {day}")
            except Exception as e:
                if attempt == 2:
                    print(f"⚠️ Kultur error en {day}: {e}")

        if data is None:
            continue

        if DEBUG_KULTUR and i == 0:
            try:
                print("DEBUG Kultur type:", type(data))
                if isinstance(data, dict):
                    print("DEBUG Kultur keys:", list(data.keys())[:50])
                print("DEBUG Kultur sample:", json.dumps(data, ensure_ascii=False)[:2500])
            except Exception:
                pass

        # Soportar envoltorios típicos: {"result": ...} / {"data": ...}
        root = data
        if isinstance(root, dict) and "result" in root and isinstance(root["result"], (dict, list)):
            root = root["result"]
        if isinstance(root, dict) and "data" in root and isinstance(root["data"], (dict, list)):
            root = root["data"]

        # Parsear cualquier dict que tenga datetime
        for d in _walk_json(root):
            dt = _extract_dt_from_dict(d)
            if not dt:
                continue

            cap, stock = _extract_kultur_cap_stock(d)
            out[(dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"))] = {
                "kultur_capacidad": cap,
                "kultur_stock": stock,
            }

    print("Kultur sesiones encontradas:", len(out))
    return out


# ================== OUTPUT ================== #
def build_rows(funcs: list[dict]) -> list[list]:
    return [
        [
            f["fecha_label"],
            f["hora"],
            f["vendidas_dt"],
            f["fecha_iso"],
            f.get("capacidad"),
            f.get("stock"),
            f.get("abono_estado"),
            f.get("fever_estado"),
            f.get("kultur_capacidad"),
            f.get("kultur_stock"),
        ]
        for f in funcs
    ]


def build_payload(eventos: dict, abono_shows: set[tuple[str, str]]) -> dict:
    now = datetime.now(TZ)
    out: dict[str, dict] = {}

    # Probar más rango por si las sesiones no están en los próximos 30 días
    kultur_map = fetch_kultur_sessions_capacity(KULTUR_EVENT_ID_ESCONDIDO, days=90)

    abono_fechas = {fecha for (fecha, _hora) in abono_shows}

    for sala, funcs in eventos.items():

        # ---------- ABONO ----------
        if sala == "Escondido":
            for f in funcs:
                fecha = f["fecha_iso"]
                hora = f["hora"]
                if (fecha, hora) in abono_shows:
                    f["abono_estado"] = "venta"
                elif fecha in abono_fechas:
                    f["abono_estado"] = "venta"
                else:
                    f["abono_estado"] = "agotado"
        else:
            for f in funcs:
                f["abono_estado"] = None

        # ---------- FEVER ----------
        if sala in ["Miedo", "Disfruta"]:
            fever_url = FEVER_URLS.get(sala)
            if fever_url:
                fever_dates = fetch_fever_dates(fever_url)
                print(f"DEBUG Fever {sala} fechas:", sorted(fever_dates))
                for f in funcs:
                    fecha = f["fecha_iso"]
                    f["fever_estado"] = "venta" if fecha in fever_dates else "agotado"
            else:
                for f in funcs:
                    f["fever_estado"] = None
        else:
            for f in funcs:
                f["fever_estado"] = None

        # ---------- KULTUR (Escondido) ----------
        if sala == "Escondido":
            for f in funcs:
                km = kultur_map.get((f["fecha_iso"], f["hora"]))
                f["kultur_capacidad"] = km.get("kultur_capacidad") if km else None
                f["kultur_stock"] = km.get("kultur_stock") if km else None
        else:
            for f in funcs:
                f["kultur_capacidad"] = None
                f["kultur_stock"] = None

        proximas: list[dict] = []
        pasadas: list[dict] = []

        for f in funcs:
            fecha_iso = f["fecha_iso"]
            hora_txt = f["hora"] or "00:00"
            try:
                ses_dt = datetime.strptime(f"{fecha_iso} {hora_txt}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
            except Exception:
                ses_dt = None

            if ses_dt and ses_dt >= now:
                proximas.append(f)
            elif ses_dt:
                pasadas.append(f)
            else:
                d = datetime.strptime(fecha_iso, "%Y-%m-%d").date()
                (proximas if d >= now.date() else pasadas).append(f)

        print(f"[DEBUG] {sala}: total={len(funcs)} · proximas={len(proximas)} · pasadas={len(pasadas)}")

        headers = ["Fecha", "Hora", "Vendidas", "FechaISO", "Capacidad", "Stock", "Abono", "Fever", "KulturCap", "KulturStock"]

        out[sala] = {
            "table": {
                "headers": headers,
                "rows": build_rows(proximas),
            },
            "proximas": {
                "table": {
                    "headers": headers,
                    "rows": build_rows(proximas),
                }
            },
        }

    return {
        "generated_at": datetime.now(TZ).isoformat(),
        "eventos": out,
        "fever_urls": FEVER_URLS,
    }


# ================== MAIN ================== #
if __name__ == "__main__":
    current: dict[str, list[dict]] = {}

    for sala, url in EVENTS.items():
        funcs = fetch_functions_dinaticket(url)
        current[sala] = funcs
        print(f"{sala}: {len(funcs)} funciones extraídas")

    try:
        abono_shows = fetch_abonoteatro_shows(ABONO_URL)
        print(f"AbonoTeatro: {len(abono_shows)} funciones en venta")
    except Exception as e:
        print(f"Error al leer AbonoTeatro: {e}")
        abono_shows = set()

    payload = build_payload(current, abono_shows)
    write_html(payload)
    write_schedule_json(payload)