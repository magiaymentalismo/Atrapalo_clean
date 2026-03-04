#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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

# ✅ KULTUR (solo Miedo y Escondido; Disfruta por ahora no tiene)
KULTUR_URLS = {
    "Miedo": "https://appkultur.com/madrid/city-search/miedo-mentalismo-y-espiritismo-con-ariel-hamui",
    "Escondido": "https://appkultur.com/madrid/el-juego-de-la-mente-magia-mental-con-ariel-hamui",
}

# AbonoTeatro por sala
ABONO_URLS = {
    "Escondido": "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=90857",
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

# Service worker: preferimos el que está en docs/
SW_SOURCE_PATHS = [Path("docs/sw.js"), Path("sw.js")]

# Cache files de Kultur (en docs/)
KULTUR_CACHE_PATHS = {
    "Miedo": Path("docs/kultur_cache_Miedo.json"),
    "Escondido": Path("docs/kultur_cache_Escondido.json"),
    "Disfruta": Path("docs/kultur_cache_Disfruta.json"),
}

# ===================== FLAGS (ENV) ===================== #

def env_flag(name: str, default: str = "0") -> bool:
    v = os.getenv(name, default)
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


KULTUR_DEBUG = env_flag("KULTUR_DEBUG", "0")
KULTUR_CACHE = env_flag("KULTUR_CACHE", "1")       # usar cache si existe
KULTUR_NO_CACHE = env_flag("KULTUR_NO_CACHE", "0") # forzar ignorar cache
KULTUR_DIRECT = env_flag("KULTUR_DIRECT", "0")     # intentar scrape live

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


def safe_int(x):
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def debug(msg: str):
    if KULTUR_DEBUG:
        print(f"[DEBUG] {msg}")


# ---- KULTUR CACHE (idx) ----
# Esperamos:
# { "idx": { "YYYY-MM-DD|HH:MM": {"capacidad": 12, "stock": 10, "vendidas": 2}, ... } }
def load_kultur_idx(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
        idx = (data or {}).get("idx", {}) or {}
        if isinstance(idx, dict):
            return idx
        return {}
    except Exception:
        return {}


def write_kultur_idx(path: Path, idx: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"idx": idx}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")


def extract_json_object_containing_idx(text: str) -> dict | None:
    """
    Busca un objeto JSON que contenga una key "idx".
    Esto es best-effort: si AppKultur cambia, no rompe el script.
    """
    # Intento 1: encontrar `"idx":{` y expandir llaves para capturar el objeto padre.
    m = re.search(r'"idx"\s*:\s*{', text)
    if not m:
        return None

    # buscamos el inicio del objeto padre más cercano hacia atrás: el '{' anterior
    start = text.rfind("{", 0, m.start())
    if start < 0:
        return None

    # expandir hasta el cierre balanceado
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                try:
                    obj = json.loads(blob)
                    if isinstance(obj, dict) and "idx" in obj and isinstance(obj["idx"], dict):
                        return obj
                except Exception:
                    return None
    return None


def fetch_kultur_idx_direct(url: str) -> dict:
    """
    Intento live (sin prometer): baja HTML y busca JSON con idx embebido.
    Si no lo encuentra, devuelve {} sin romper.
    """
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        html = r.text

        obj = extract_json_object_containing_idx(html)
        if obj and isinstance(obj.get("idx"), dict):
            debug(f"Kultur: idx encontrado embebido en HTML ({len(obj['idx'])} keys)")
            return obj["idx"]

        # Intento 2: buscar <script type="application/json">...
        soup = BeautifulSoup(html, "html.parser")
        for s in soup.find_all("script"):
            t = (s.string or "").strip()
            if not t:
                continue
            if '"idx"' in t:
                obj = extract_json_object_containing_idx(t)
                if obj and isinstance(obj.get("idx"), dict):
                    debug(f"Kultur: idx encontrado en <script> ({len(obj['idx'])} keys)")
                    return obj["idx"]

        debug("Kultur: no pude extraer idx del HTML (sin romper).")
        return {}
    except Exception as e:
        debug(f"Kultur direct error: {e}")
        return {}


def get_kultur_idx_for_sala(sala: str) -> dict:
    cache_path = KULTUR_CACHE_PATHS.get(sala)
    idx_cache = load_kultur_idx(cache_path) if cache_path else {}

    # Si NO_CACHE, ignoramos cache
    if KULTUR_NO_CACHE:
        idx_cache = {}

    # Si DIRECT y tengo URL, intento live
    idx_direct = {}
    if KULTUR_DIRECT and sala in KULTUR_URLS:
        idx_direct = fetch_kultur_idx_direct(KULTUR_URLS[sala])
        # si conseguimos algo, lo guardamos a cache para futuras ejecuciones
        if idx_direct and cache_path:
            write_kultur_idx(cache_path, idx_direct)

    # Prioridad: direct si tiene datos, sino cache
    return idx_direct if idx_direct else (idx_cache if (KULTUR_CACHE and idx_cache) else {})


# ===================== HTML OUTPUT ===================== #

def write_html(payload: dict) -> None:
    html_template = TEMPLATE_PATH.read_text("utf-8")
    html = html_template.replace(
        "{{PAYLOAD_JSON}}",
        json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>"),
    )

    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)

    (docs_dir / "index.html").write_text(html, "utf-8")

    if MANIFEST_PATH.exists():
        shutil.copy(MANIFEST_PATH, docs_dir / "manifest.json")

    # SW: si existe en docs, lo dejamos; si existe solo en root, lo copiamos
    sw_src = next((p for p in SW_SOURCE_PATHS if p.exists()), None)
    if sw_src:
        # copiamos a docs/sw.js solo si el source NO es ya docs/sw.js
        if sw_src.resolve() != (docs_dir / "sw.js").resolve():
            shutil.copy(sw_src, docs_dir / "sw.js")

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


# ===================== BUILD PAYLOAD ===================== #

def build_payload(
    eventos: dict[str, list[dict]],
    abono_by_sala: dict[str, set[tuple[str, str]]],
    kultur_by_sala: dict[str, dict],
):
    now = datetime.now(TZ)
    out: dict[str, dict] = {}

    for sala, funcs in eventos.items():
        abono_shows = abono_by_sala.get(sala, set())
        has_abono = sala in abono_by_sala

        kultur_idx = kultur_by_sala.get(sala, {}) or {}

        proximas: list[dict] = []

        for f in funcs:
            f["hora"] = normalize_hhmm(f.get("hora"))

            # ABONO
            f["abono_estado"] = (
                "venta" if (f["fecha_iso"], f["hora"]) in abono_shows else "agotado"
            ) if has_abono else None

            # KULTUR (vendidas/capacidad/stock)
            k_key = f"{f['fecha_iso']}|{f['hora']}"
            k = kultur_idx.get(k_key) if isinstance(kultur_idx, dict) else None

            f["kultur_vendidas"] = safe_int(k.get("vendidas")) if isinstance(k, dict) else None
            f["kultur_capacidad"] = safe_int(k.get("capacidad")) if isinstance(k, dict) else None
            f["kultur_stock"] = safe_int(k.get("stock")) if isinstance(k, dict) else None

            ses_dt = datetime.strptime(
                f"{f['fecha_iso']} {f['hora']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=TZ)

            if ses_dt >= now:
                proximas.append(f)

        # ✅ Nuevo formato de columnas:
        # [Fecha, Hora, VendidasDT, FechaISO, CapacidadDT, StockDT, Abono, KulturVendidas, KulturCapacidad, KulturStock]
        rows = [
            [
                f["fecha_label"],
                f["hora"],
                f["vendidas_dt"],
                f["fecha_iso"],
                f["capacidad"],
                f["stock"],
                f["abono_estado"],
                f["kultur_vendidas"],
                f["kultur_capacidad"],
                f["kultur_stock"],
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
            "KulturStock",
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

    # ✅ Kultur por sala: cache + (opcional) direct
    kultur_by_sala: dict[str, dict] = {}
    for sala in EVENTS.keys():
        kultur_by_sala[sala] = get_kultur_idx_for_sala(sala)
        if sala in KULTUR_URLS:
            print(f"Kultur {sala}: {len(kultur_by_sala[sala])} sesiones (idx)")
        else:
            print(f"Kultur {sala}: sin URL")

    payload = build_payload(current, abono_by_sala, kultur_by_sala)
    write_html(payload)
    write_schedule_json(payload)
