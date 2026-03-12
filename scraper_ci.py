#!/usr/bin/env python3
from __future__ import annotations

import json
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
    "Miedo":    "https://www.dinaticket.com/es/provider/10402/event/4915778",
    "Escondido":"https://www.dinaticket.com/es/provider/20073/event/4930233",
}

ABONO_URLS = {
    "Escondido": "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=90857",
    "Disfruta":  "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=57914",
}

KULTUR_EVENTS = {
    "Escondido": "YaWZRG4MCxo1CHvr",
    "Miedo":     "BW8A51aMmrnmTQzH",
}

KULTUR_PAGES = {
    "Escondido": "https://appkultur.com/madrid/el-juego-de-la-mente-magia-mental-con-ariel-hamui",
    "Miedo":     "https://appkultur.com/madrid/miedo-mentalismo-y-espiritismo-con-ariel-hamui",
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
SW_PATH        = Path("sw.js")
DOCS_DIR       = Path("docs")


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
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8",
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
            "Ene":"01","Feb":"02","Mar":"03","Abr":"04",
            "May":"05","Jun":"06","Jul":"07","Ago":"08",
            "Sep":"09","Oct":"10","Nov":"11","Dic":"12",
        }
        mes_txt = mes.text.strip().replace(".", "")
        mes_num = mes_map.get(mes_txt)
        if not mes_num:
            continue
        now  = datetime.now(TZ)
        anio = now.year
        fecha_iso   = f"{anio}-{mes_num}-{dia.text.strip().zfill(2)}"
        fecha_label = datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d %b %Y")
        hora_span   = session.find("span", class_="session-card__time-session")
        hora        = normalize_hhmm(hora_span.text if hora_span else "")
        quota       = session.find("div", class_="js-quota-row")
        if not quota:
            continue
        cap      = int(quota.get("data-quota-total", 0))
        stock    = int(quota.get("data-stock", 0))
        vendidas = max(0, cap - stock)
        out.append({
            "fecha_label": fecha_label,
            "fecha_iso":   fecha_iso,
            "hora":        hora,
            "vendidas_dt": vendidas,
            "capacidad":   cap,
            "stock":       stock,
        })
    return out


# ===================== ABONO ===================== #

def fetch_abonoteatro_shows(url: str) -> set[tuple[str, str]]:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out: set[tuple[str, str]] = set()

    # Formato antiguo
    for ses in soup.find_all("div", class_="bsesion"):
        if not ses.find("a", class_="buyBtn"):
            continue
        mes_tag  = ses.find("p", class_="psess")
        dia_tag  = ses.find("p", class_="psesb")
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
        hora      = normalize_hhmm(f"{hora_match.group(1)}:{hora_match.group(2)}")
        fecha_iso = f"{anio}-{mes_num}-{dia}"
        out.add((fecha_iso, hora))

    if out:
        return out

    # Formato nuevo
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
            r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(20\d{2})\b", t,
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
        dia    = str(int(m_day.group(1))).zfill(2)
        m_time = re.search(r"\b([0-2]?\d):([0-5]\d)\b", t)
        if not m_time:
            continue
        hora      = normalize_hhmm(f"{m_time.group(1)}:{m_time.group(2)}")
        fecha_iso = f"{anio}-{mes_num}-{dia}"
        out.add((fecha_iso, hora))

    return out


# ===================== KULTUR (WEBKIT) ===================== #

def fetch_kultur_webkit(sala: str) -> dict:
    """Usa Playwright WebKit (Safari engine) para pasar App Check."""
    from playwright.sync_api import sync_playwright

    now        = datetime.now(TZ)
    event_id   = KULTUR_EVENTS[sala]
    page_url   = KULTUR_PAGES[sala]
    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.webkit.launch(headless=True)
        ctx  = browser.new_context()
        page = ctx.new_page()

        def on_response(resp):
            if "getCalendar" in resp.url:
                try:
                    captured.append(resp.json())
                    print(f"  ✓ getCalendar {resp.status}")
                except Exception as e:
                    print(f"  ⚠ getCalendar parse error: {e}")

        page.on("response", on_response)
        page.goto(page_url, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # Fallback: fetch manual desde dentro del browser (ya tiene el token)
        if not captured:
            from_date = now.strftime("%Y-%m-%d")
            to_date   = (now + timedelta(days=60)).strftime("%Y-%m-%d")
            try:
                js_result = page.evaluate(f"""
                    async () => {{
                        const resp = await fetch(
                            "https://europe-west6-kultur-platform.cloudfunctions.net/events_api_v2-getCalendar",
                            {{
                                method: "POST",
                                headers: {{"Content-Type": "application/json"}},
                                body: JSON.stringify({{
                                    data: {{
                                        eventId: "{event_id}",
                                        from: "{from_date}",
                                        to: "{to_date}"
                                    }}
                                }})
                            }}
                        );
                        return await resp.json();
                    }}
                """)
                if js_result:
                    captured.append(js_result)
                    print(f"  ✓ getCalendar via fetch manual")
            except Exception as e:
                print(f"  ⚠ fetch manual falló: {e}")

        browser.close()

    return captured[0] if captured else {}


def parse_kultur_response(data: dict) -> dict[str, int]:
    """
    Devuelve idx: 'YYYY-MM-DD' -> disponibles
    (la API solo da fecha + disponibles, sin hora ni capacidad total)
    """
    idx: dict[str, int] = {}

    result = data.get("result", data)
    items  = None
    if isinstance(result, dict):
        items = result.get("data") or result.get("sessions") or result.get("items")
    if items is None:
        items = data.get("data")
    if not isinstance(items, list):
        return idx

    for item in items:
        if not isinstance(item, dict):
            continue
        date = item.get("date") or item.get("fecha") or item.get("day")
        avail = item.get("available") or item.get("stock") or item.get("disponibles") or 0
        if not date:
            continue
        try:
            idx[str(date)] = int(avail)
        except Exception:
            pass

    return idx


def fetch_and_write_kultur_cache(sala: str) -> dict:
    DOCS_DIR.mkdir(exist_ok=True)
    print(f"\n  Kultur WebKit [{sala}]...")

    raw = fetch_kultur_webkit(sala)
    if not raw:
        print(f"  ❌ Sin respuesta Kultur para {sala}")
        return {}

    # Guardar raw
    (DOCS_DIR / f"kultur_raw_{sala}.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), "utf-8"
    )

    # idx por FECHA (sin hora, la API no la da)
    idx = parse_kultur_response(raw)
    print(f"  → {len(idx)} fechas Kultur: {list(idx.keys())[:5]}")

    data = {"idx": idx}
    (DOCS_DIR / f"kultur_cache_{sala}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
    )
    print(f"  ✔ kultur_cache_{sala}.json ({len(idx)} fechas)")
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

def build_payload(
    eventos: dict[str, list[dict]],
    abono_by_sala: dict[str, set[tuple[str, str]]],
) -> dict:
    now = datetime.now(TZ)
    out: dict[str, dict] = {}

    for sala, funcs in eventos.items():
        abono_shows = abono_by_sala.get(sala, set())
        has_abono   = sala in abono_by_sala

        # Kultur: idx por fecha  →  disponibles
        kultur_cache = load_kultur_cache(sala) if sala in KULTUR_EVENTS else {}
        kultur_idx   = (kultur_cache.get("idx") or {}) if isinstance(kultur_cache, dict) else {}

        proximas: list[dict] = []

        for f in funcs:
            f["hora"] = normalize_hhmm(f.get("hora"))

            # Abono
            f["abono_estado"] = (
                "venta" if (f["fecha_iso"], f["hora"]) in abono_shows else "agotado"
            ) if has_abono else None

            # Kultur: buscar por fecha (sin hora)
            k_disponibles = kultur_idx.get(f["fecha_iso"])  # int o None
            f["kultur_disponibles"] = k_disponibles

            ses_dt = datetime.strptime(
                f"{f['fecha_iso']} {f['hora']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=TZ)

            if ses_dt >= now:
                proximas.append(f)

        # 8 columnas: Fecha, Hora, VendidasDT, FechaISO, CapacidadDT, StockDT, Abono, KulturDisponibles
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
            ]
            for f in proximas
        ]

        headers = [
            "Fecha", "Hora", "Vendidas", "FechaISO",
            "Capacidad", "Stock", "Abono", "KulturDisponibles",
        ]

        out[sala] = {
            "table":    {"headers": headers, "rows": rows},
            "proximas": {"table": {"headers": headers, "rows": rows}},
        }

    return {"generated_at": datetime.now(TZ).isoformat(), "eventos": out}


# ===================== MAIN ===================== #

if __name__ == "__main__":
    # 1. Dinaticket
    current: dict[str, list[dict]] = {}
    for sala, url in EVENTS.items():
        funcs = fetch_functions_dinaticket(url)
        current[sala] = funcs
        print(f"Dina {sala}: {len(funcs)} funciones")

    # 2. AbonoTeatro
    abono_by_sala: dict[str, set[tuple[str, str]]] = {}
    for sala, url in ABONO_URLS.items():
        shows = fetch_abonoteatro_shows(url)
        abono_by_sala[sala] = shows
        print(f"Abono {sala}: {len(shows)}")

    # 3. Kultur (WebKit)
    for sala in KULTUR_EVENTS:
        try:
            fetch_and_write_kultur_cache(sala)
        except Exception as e:
            print(f"⚠️  Kultur {sala}: {e}")

    # 4. Build & write
    payload = build_payload(current, abono_by_sala)
    write_html(payload)
    write_schedule_json(payload)
