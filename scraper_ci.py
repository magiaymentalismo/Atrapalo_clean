#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

EVENTS = {
    "Disfruta": "https://www.dinaticket.com/es/provider/10402/event/4905281",
    "Miedo":    "https://www.dinaticket.com/es/provider/10402/event/4915778",
    "Escondi2": "https://www.dinaticket.com/es/provider/20864/event/4943466",
}

ABONO_URLS = {
    "Disfruta": "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=57914",
}

KULTUR_EVENTS = {
    "Miedo": "BW8A51aMmrnmTQzH",
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
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8",
    )
    print("✔ Generado docs/schedule.json")


def _extract_provider_event(url: str) -> tuple[str, str] | None:
    m = re.search(r"/provider/(\d+)/event/(\d+)", url)
    if not m:
        return None
    return m.group(1), m.group(2)


def _fetch_dinaticket_ajax_pages(url: str, max_pages: int = 8) -> str:
    """
    Descarga páginas extra de DinaTicket detrás de:
    ?pg_action=ajax_listado_pases&p=2,3,4...
    """
    ids = _extract_provider_event(url)
    if not ids:
        return ""

    provider_id, event_id = ids
    base = f"https://www.dinaticket.com/es/provider/{provider_id}/event/{event_id}"
    chunks: list[str] = []

    for p in range(2, max_pages + 1):
        ajax_url = f"{base}?pg_action=ajax_listado_pases&p={p}"
        try:
            r = requests.get(ajax_url, headers=UA, timeout=20)

            if r.status_code == 429:
                print(f"⚠️ Rate limit AJAX p={p}: {ajax_url}")
                break

            if r.status_code != 200:
                print(f"⚠️ AJAX status {r.status_code}: {ajax_url}")
                break

            text = r.text.strip()
            if not text:
                break

            chunks.append(text)
            time.sleep(1)

        except Exception as e:
            print(f"⚠️ Error AJAX p={p}: {e}")
            break

    return "\n".join(chunks)


def fetch_functions_dinaticket(url: str) -> list[dict]:
    try:
        r = requests.get(url, headers=UA, timeout=20)

        if r.status_code == 429:
            print(f"⚠️ Rate limit en DinaTicket: {url}")
            return []

        if r.status_code != 200:
            print(f"⚠️ Error DinaTicket status {r.status_code}: {url}")
            return []

    except Exception as e:
        print(f"⚠️ Error cargando DinaTicket {url}: {e}")
        return []

    html = r.text
    html_extra = _fetch_dinaticket_ajax_pages(url)
    if html_extra:
        html += "\n" + html_extra

    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for session in soup.find_all("div", class_="js-session-row"):
        parent = session.find_parent("div", class_="js-session-group")
        if not parent:
            continue

        dia = parent.find("span", class_="num_dia")
        mes = parent.find("span", class_="mes")
        if not dia or not mes:
            continue

        mes_map = {
            "Ene":"01","Feb":"02","Mar":"03","Abr":"04",
            "May":"05","Jun":"06","Jul":"07","Ago":"08",
            "Sep":"09","Oct":"10","Nov":"11","Dic":"12",
        }

        mes_txt = mes.text.strip().replace(".", "")
        mes_num = mes_map.get(mes_txt)
        if not mes_num:
            continue

        now = datetime.now(TZ)
        anio = now.year
        if int(mes_num) < now.month:
            anio += 1

        fecha_iso = f"{anio}-{mes_num}-{dia.text.strip().zfill(2)}"
        fecha_label = datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d %b %Y")

        hora_span = session.find("span", class_="session-card__time-session")
        hora = normalize_hhmm(hora_span.text if hora_span else "")

        key = (fecha_iso, hora)
        if key in seen:
            continue
        seen.add(key)

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

    out.sort(key=lambda x: (x["fecha_iso"], x["hora"]))
    return out


def fetch_abonoteatro_shows(url: str) -> set[tuple[str, str]]:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out: set[tuple[str, str]] = set()

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
            "enero":"01","febrero":"02","marzo":"03","abril":"04",
            "mayo":"05","junio":"06","julio":"07","agosto":"08",
            "septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12",
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

    mes_map = {
        "enero":"01","febrero":"02","marzo":"03","abril":"04",
        "mayo":"05","junio":"06","julio":"07","agosto":"08",
        "septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12",
    }
    dow = r"(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"

    for a in soup.find_all("a", string=lambda s: s and s.strip().lower() == "comprar"):
        block = a.find_parent(["article", "section", "div"]) or a.parent
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


def load_kultur_cache(sala: str) -> dict:
    p = DOCS_DIR / f"kultur_cache_{sala}.json"
    if not p.exists():
        print(f"  Sin cache Kultur para {sala}")
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}


def load_previous_event_rows(sala: str) -> list[dict]:
    p = DOCS_DIR / "schedule.json"
    if not p.exists():
        return []

    try:
        data = json.loads(p.read_text("utf-8"))
        rows = (
            data.get("eventos", {})
            .get(sala, {})
            .get("table", {})
            .get("rows", [])
        )

        out: list[dict] = []
        for row in rows:
            if len(row) < 6:
                continue
            out.append({
                "fecha_label": row[0],
                "hora": row[1],
                "vendidas_dt": row[2],
                "fecha_iso": row[3],
                "capacidad": row[4],
                "stock": row[5],
            })
        return out
    except Exception:
        return []


def build_payload(
    eventos: dict[str, list[dict]],
    abono_by_sala: dict[str, set[tuple[str, str]]],
) -> dict:
    now = datetime.now(TZ)
    out: dict[str, dict] = {}

    for sala, funcs in eventos.items():
        abono_shows = abono_by_sala.get(sala, set())
        has_abono = sala in abono_by_sala

        kultur_cache = load_kultur_cache(sala) if sala in KULTUR_EVENTS else {}
        kultur_idx = (kultur_cache.get("idx") or {}) if isinstance(kultur_cache, dict) else {}

        proximas: list[dict] = []

        for f in funcs:
            f["hora"] = normalize_hhmm(f.get("hora"))
            f["abono_estado"] = (
                "venta" if (f["fecha_iso"], f["hora"]) in abono_shows else "agotado"
            ) if has_abono else None

            def _find_kultur(idx, fecha_iso, hora):
                exact = idx.get(f"{fecha_iso}|{hora}")
                if exact is not None:
                    return exact if isinstance(exact, dict) else {
                        "disponibles": exact,
                        "capacidad": None,
                        "vendidas": None,
                    }
                for k, v in idx.items():
                    if k.startswith(fecha_iso):
                        return v if isinstance(v, dict) else {
                            "disponibles": v,
                            "capacidad": None,
                            "vendidas": None,
                        }
                return None

            k_data = _find_kultur(kultur_idx, f["fecha_iso"], f["hora"])
            if isinstance(k_data, dict):
                f["kultur_disponibles"] = k_data.get("disponibles")
                f["kultur_vendidas"] = k_data.get("vendidas")
                f["kultur_capacidad"] = k_data.get("capacidad")
            else:
                f["kultur_disponibles"] = None
                f["kultur_vendidas"] = None
                f["kultur_capacidad"] = None

            ses_dt = datetime.strptime(
                f"{f['fecha_iso']} {f['hora']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=TZ)

            if ses_dt >= now:
                proximas.append(f)

        rows = [
            [
                f["fecha_label"],
                f["hora"],
                f["vendidas_dt"],
                f["fecha_iso"],
                f["capacidad"],
                f["stock"],
                f["abono_estado"],
                f.get("kultur_disponibles"),
                f.get("kultur_vendidas"),
                f.get("kultur_capacidad"),
            ]
            for f in proximas
        ]

        headers = [
            "Fecha", "Hora", "Vendidas", "FechaISO",
            "Capacidad", "Stock", "Abono", "KulturDisponibles",
            "KulturVendidas", "KulturCapacidad",
        ]

        out[sala] = {
            "table": {"headers": headers, "rows": rows},
            "proximas": {"table": {"headers": headers, "rows": rows}},
        }

    return {"generated_at": datetime.now(TZ).isoformat(), "eventos": out}


if __name__ == "__main__":
    current: dict[str, list[dict]] = {}

    for sala, url in EVENTS.items():
        funcs = fetch_functions_dinaticket(url)

        if not funcs and sala == "Escondi2":
            old_funcs = load_previous_event_rows(sala)
            if old_funcs:
                print(f"⚠️ Usando cache previa para {sala}: {len(old_funcs)} funciones")
                funcs = old_funcs

        current[sala] = funcs
        print(f"Dina {sala}: {len(funcs)} funciones")

    abono_by_sala: dict[str, set[tuple[str, str]]] = {}
    for sala, url in ABONO_URLS.items():
        shows = fetch_abonoteatro_shows(url)
        abono_by_sala[sala] = shows
        print(f"Abono {sala}: {len(shows)}")

    for sala in KULTUR_EVENTS:
        cache = load_kultur_cache(sala)
        idx = cache.get("idx", {})
        if idx:
            print(f"Kultur {sala}: {len(idx)} fechas en cache")

    payload = build_payload(current, abono_by_sala)
    write_html(payload)
    write_schedule_json(payload)
