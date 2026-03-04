#!/usr/bin/env python3
from __future__ import annotations

import json
import re
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

# AbonoTeatro por sala
ABONO_URLS = {
    "Escondido": "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=90857",
    "Disfruta": "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=57914",
}

# Kultur (usamos cache local versionado en docs/)
# Si una sala no tiene, simplemente queda "—" en la UI.
KULTUR_CACHE_FILES = {
    "Escondido": "docs/kultur_cache_Escondido.json",
    "Miedo": "docs/kultur_cache_Miedo.json",     # si lo creás/commiteás, se muestra
    "Disfruta": "docs/kultur_cache_Disfruta.json" # si lo creás/commiteás, se muestra
}

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
    )
}

TZ = ZoneInfo("Europe/Madrid")

TEMPLATE_PATH = Path("template.html")


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


def safe_int(x, default=None):
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default


# ===================== OUTPUT ===================== #

def write_html(payload: dict) -> None:
    html_template = TEMPLATE_PATH.read_text("utf-8")
    html = html_template.replace(
        "{{PAYLOAD_JSON}}",
        json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>"),
    )

    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "index.html").write_text(html, "utf-8")
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

        cap = safe_int(quota.get("data-quota-total", 0), 0)
        stock = safe_int(quota.get("data-stock", 0), 0)
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

    # --- 1) Formato antiguo ---
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

    # --- 2) Formato nuevo (texto + link Comprar) ---
    mes_map = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }
    dow = r"(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"

    comprar_links = soup.find_all("a", string=lambda s: s and s.strip().lower() == "comprar")

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


# ===================== KULTUR (desde cache versionado) ===================== #

def load_kultur_idx_for_sala(sala: str) -> dict[str, dict]:
    """
    Lee docs/kultur_cache_<Sala>.json y devuelve idx:
    {
      "2026-03-05|20:00": {"capacidad":12,"stock":10,"vendidas":2}
    }
    """
    path_str = KULTUR_CACHE_FILES.get(sala)
    if not path_str:
        return {}
    p = Path(path_str)
    if not p.exists():
        return {}

    try:
        data = json.loads(p.read_text("utf-8"))
    except Exception:
        return {}

    idx = data.get("idx")
    if not isinstance(idx, dict):
        return {}
    return idx


# ===================== BUILD PAYLOAD ===================== #

def build_payload(
    eventos: dict[str, list[dict]],
    abono_by_sala: dict[str, set[tuple[str, str]]],
    kultur_idx_by_sala: dict[str, dict[str, dict]],
):
    now = datetime.now(TZ)
    out: dict[str, dict] = {}

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

    for sala, funcs in eventos.items():
        abono_shows = abono_by_sala.get(sala, set())
        has_abono = sala in abono_by_sala

        kidx = kultur_idx_by_sala.get(sala, {}) or {}

        proximas: list[dict] = []

        for f in funcs:
            f["hora"] = normalize_hhmm(f.get("hora"))

            # Abono
            f["abono_estado"] = (
                "venta" if (f["fecha_iso"], f["hora"]) in abono_shows else "agotado"
            ) if has_abono else None

            # Kultur (vendidas/capacidad) por clave fecha|hora
            key = f"{f['fecha_iso']}|{f['hora']}"
            k = kidx.get(key)
            if isinstance(k, dict):
                f["kultur_vendidas"] = safe_int(k.get("vendidas"), None)
                f["kultur_capacidad"] = safe_int(k.get("capacidad"), None)
            else:
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
                f.get("kultur_vendidas"),
                f.get("kultur_capacidad"),
            ]
            for f in proximas
        ]

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

    for sala, url in EVENTS.items():
        funcs = fetch_functions_dinaticket(url)
        current[sala] = funcs
        print(f"{sala}: {len(funcs)} funciones")

    abono_by_sala: dict[str, set[tuple[str, str]]] = {}
    for sala, url in ABONO_URLS.items():
        shows = fetch_abonoteatro_shows(url)
        abono_by_sala[sala] = shows
        print(f"AbonoTeatro {sala}: {len(shows)}")

    kultur_idx_by_sala = {s: load_kultur_idx_for_sala(s) for s in EVENTS.keys()}

    payload = build_payload(current, abono_by_sala, kultur_idx_by_sala)
    write_html(payload)
    write_schedule_json(payload)
