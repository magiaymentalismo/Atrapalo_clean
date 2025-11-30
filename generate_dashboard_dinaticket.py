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

ABONO_URL = "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=90857"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
        "AppleWebKit/537.36 (KHTML, como Gecko) Chrome/123 Safari/537.36"
    )
}

MESES = {
    "Ene.": "01",
    "Feb.": "02",
    "Mar.": "03",
    "Abr.": "04",
    "May.": "05",
    "Jun.": "06",
    "Jul.": "07",
    "Ago.": "08",
    "Sep.": "09",
    "Oct.": "10",
    "Nov.": "11",
    "Dic.": "12",
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

HISTORY_PATH = Path("state_dinaticket.json")
TZ = ZoneInfo("Europe/Madrid")

import shutil

# ================== TEMPLATE (HTML) ================== #
TEMPLATE_PATH = Path("template.html")
MANIFEST_PATH = Path("manifest.json")
SW_PATH = Path("sw.js")

# ... (rest of the script remains the same until write_html)

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

    # Copiar archivos PWA
    if MANIFEST_PATH.exists():
        shutil.copy(MANIFEST_PATH, docs_dir / "manifest.json")
        print("✔ Copiado manifest.json")
    
    if SW_PATH.exists():
        shutil.copy(SW_PATH, docs_dir / "sw.js")
        print("✔ Copiado sw.js")

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

        mes_num = MESES.get(mes.text.strip(), "01")

        # === FIX DEL AÑO ===
        now = datetime.now(TZ)
        anio = now.year

        fecha_iso_tmp = f"{anio}-{mes_num}-{dia.text.strip().zfill(2)}"
        fecha_dt = datetime.strptime(fecha_iso_tmp, "%Y-%m-%d")

        if fecha_dt.date() < now.date():
            fecha_dt = fecha_dt.replace(year=anio + 1)

        fecha_iso = fecha_dt.strftime("%Y-%m-%d")
        fecha_label = fecha_dt.strftime("%d %b %Y")
        # ===================

        hora_span = session.find("span", class_="session-card__time-session")
        hora_txt = (hora_span.text or "").strip().lower().replace(" ", "").replace("h", ":")
        m = re.match(r"^(\d{1,2})(?::?(\d{2}))?$", hora_txt)
        if m:
            hh = int(m.group(1)); mm = int(m.group(2) or "00")
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
    """
    Devuelve set de (fecha_iso, hora) que están ACTUALMENTE en venta en AbonoTeatro.
    Sólo se consideran sesiones con botón "Comprar" (buyBtn).
    """
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out: set[tuple[str, str]] = set()

    # Cada sesión está en un div.bsesion (dentro de .bsesiones)
    sesiones = soup.find_all("div", class_="bsesion")
    for ses in sesiones:
        # Si no hay botón de compra, asumimos que no está en venta en Abono
        if not ses.find("a", class_="buyBtn"):
            continue

        fecha_div = ses.find("div", class_="bfechasesion")
        if not fecha_div:
            continue

        # Primer psess: "noviembre 2025"
        mes_y_anio_tag = fecha_div.find("p", class_="psess")
        if not mes_y_anio_tag:
            continue

        raw = mes_y_anio_tag.get_text(strip=True).lower()
        # Esperamos algo tipo "noviembre 2025"
        m_ma = re.match(r"^([a-záéíóúñ]+)\s+(\d{4})$", raw)
        if not m_ma:
            print("DEBUG mes/año raro en AbonoTeatro:", repr(raw))
            continue

        mes_nombre = m_ma.group(1)
        anio = m_ma.group(2)
        mes_num = MESES_LARGO.get(mes_nombre)
        if not mes_num:
            print("DEBUG mes desconocido en AbonoTeatro:", mes_nombre, "en", raw)
            continue

        # Día: <p class="psesb">30</p>
        dia_tag = fecha_div.find("p", class_="psesb")
        if not dia_tag:
            continue
        # Nos quedamos con los dígitos por si viene algo raro
        dia_text = dia_tag.get_text(strip=True)
        dia_num = re.sub(r"\D", "", dia_text).zfill(2)
        if not dia_num:
            print("DEBUG día raro en AbonoTeatro:", repr(dia_text))
            continue

        # Hora: <h3 class="horasesion ..."><i ...></i>17:00</h3>
        hora_h3 = ses.find("h3", class_="horasesion")
        if not hora_h3:
            continue
        hora_txt = hora_h3.get_text(" ", strip=True)
        # Buscamos un patrón hh:mm en el texto
        m_hora = re.search(r"(\d{1,2}):(\d{2})", hora_txt)
        if not m_hora:
            print("DEBUG hora rara en AbonoTeatro:", repr(hora_txt))
            continue
        hh = m_hora.group(1).zfill(2)
        mm = m_hora.group(2).zfill(2)
        hora = f"{hh}:{mm}"

        fecha_iso = f"{anio}-{mes_num}-{dia_num}"
        out.add((fecha_iso, hora))

    # DEBUG: ver qué está detectando
    print("DEBUG AbonoTeatro fechas/hora:", sorted(out))
    return out

# ================== HISTORIAL ================== #
def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    try:
        raw = json.loads(HISTORY_PATH.read_text("utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}

    clean: dict[str, list[dict]] = {}
    for sala, lista in raw.items():
        if not isinstance(sala, str) or not isinstance(lista, list):
            continue
        good: list[dict] = []
        for x in lista:
            if isinstance(x, dict) and "fecha_iso" in x and "hora" in x:
                good.append(x)
        if good:
            clean[sala] = good
    return clean

def save_history(data: dict) -> None:
    HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

def merge_eventos(history: dict, current: dict) -> dict:
    merged: dict[str, list[dict]] = {}
    for sala in set(history) | set(current):
        prev = history.get(sala, []) or []
        curr = current.get(sala, []) or []
        by_key: dict[str, dict] = {}
        for x in prev:
            if not isinstance(x, dict) or "fecha_iso" not in x or "hora" not in x:
                continue
            key = f"{x['fecha_iso']} {x['hora']}"
            by_key[key] = x
        for x in curr:
            if not isinstance(x, dict) or "fecha_iso" not in x or "hora" not in x:
                continue
            key = f"{x['fecha_iso']} {x['hora']}"
            by_key[key] = x
        merged[sala] = sorted(by_key.values(), key=lambda f: (f["fecha_iso"], f["hora"]))
    return merged

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
        ]
        for f in funcs
    ]

def build_payload(eventos: dict, abono_shows: set[tuple[str, str]]) -> dict:
    """
    Separa en PROXIMAS / PASADAS en el servidor usando FECHA+HORA.
    Añade info de AbonoTeatro solo a Escondido:
      - 'venta'   si (fecha,hora) está en AbonoTeatro
      - 'venta'   si no coincide la hora pero hay sesión ese día en AbonoTeatro
      - 'agotado' si no aparece ese día en AbonoTeatro

    Además, deja un bloque plano "table" por evento
    para compatibilidad con el bot de Telegram.
    """
    now = datetime.now(TZ)
    out: dict[str, dict] = {}

    # Preparamos también un set solo de fechas (para el fallback por día)
    abono_fechas = {fecha for (fecha, _hora) in abono_shows}

    for sala, funcs in eventos.items():
        # Marcar estado de abono solo para Escondido
        if sala == "Escondido":
            for f in funcs:
                fecha = f["fecha_iso"]
                hora = f["hora"]
                key = (fecha, hora)

                if key in abono_shows:
                    f["abono_estado"] = "venta"
                elif fecha in abono_fechas:
                    f["abono_estado"] = "venta"
                else:
                    f["abono_estado"] = "agotado"
        else:
            for f in funcs:
                f.setdefault("abono_estado", None)

        proximas: list[dict] = []
        pasadas: list[dict] = []

        for f in funcs:
            fecha_iso = f.get("fecha_iso")
            hora_txt = f.get("hora") or "00:00"
            if not fecha_iso:
                continue

            # Intentamos FECHA+HORA primero
            try:
                ses_dt = datetime.strptime(
                    f"{fecha_iso} {hora_txt}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=TZ)
            except Exception:
                # Fallback: solo fecha
                try:
                    d = datetime.strptime(fecha_iso, "%Y-%m-%d").date()
                except Exception:
                    continue
                if d >= now.date():
                    proximas.append(f)
                else:
                    pasadas.append(f)
                continue

            if ses_dt >= now:
                proximas.append(f)
            else:
                pasadas.append(f)

        # DEBUG contadores para entender 20 vs 17 etc.
        print(
            f"[DEBUG] {sala}: total={len(funcs)} · "
            f"proximas={len(proximas)} · pasadas={len(pasadas)}"
        )

        out[sala] = {
            # Bloque plano para el bot de Telegram (todas las funciones)
            "table": {
                "headers": ["Fecha","Hora","Vendidas","FechaISO","Capacidad","Stock","Abono"],
                "rows": build_rows(funcs),
            },
            # Bloques separados para la web
            "proximas": {
                "table": {
                    "headers": ["Fecha","Hora","Vendidas","FechaISO","Capacidad","Stock","Abono"],
                    "rows": build_rows(proximas),
                }
            },
            "pasadas": {
                "table": {
                    "headers": ["Fecha","Hora","Vendidas","FechaISO","Capacidad","Stock","Abono"],
                    "rows": build_rows(pasadas),
                }
            },
        }

    return {
        "generated_at": datetime.now(TZ).isoformat(),
        "eventos": out,
    }

# ================== MAIN ================== #
if __name__ == "__main__":
    # 1. Scrape Dinaticket
    current: dict[str, list[dict]] = {}
    for sala, url in EVENTS.items():
        funcs = fetch_functions_dinaticket(url)
        current[sala] = funcs
        print(f"{sala}: {len(funcs)} funciones extraídas")

    # 2. Historial
    history = load_history()
    print("Historial cargado.")

    merged = merge_eventos(history, current)
    save_history(merged)

    # 3. AbonoTeatro
    abono_shows: set[tuple[str, str]] = set()
    try:
        abono_shows = fetch_abonoteatro_shows(ABONO_URL)
        print(f"AbonoTeatro: {len(abono_shows)} funciones en venta")
    except Exception as e:
        print(f"Error al leer AbonoTeatro: {e}")

    # 4. Payload + HTML
    payload = build_payload(merged, abono_shows)
    write_html(payload)