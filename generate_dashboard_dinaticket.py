#!/usr/bin/env python3
from __future__ import annotations
import json, re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import List, Dict

from playwright.sync_api import sync_playwright

# ===================== CONFIG ===================== #
EVENTS = {
    "Escondido": "https://www.dinaticket.com/es/provider/20073/event/4919204",
    "Escalera": "https://www.dinaticket.com/es/provider/10402/event/4923185"
}

MESES = {
    "Ene.": "01", "Feb.": "02", "Mar.": "03", "Abr.": "04", "May.": "05", "Jun.": "06",
    "Jul.": "07", "Ago.": "08", "Sep.": "09", "Oct.": "10", "Nov.": "11", "Dic.": "12"
}

HISTORIAL_FILE = "historial_sesiones.json"
OUTPUT_HTML = "dashboard_tabs.html"

# ================== SCRAPER ================== #
def fetch_functions_dinaticket(url: str) -> List[Dict]:
    """Scrapea todas las funciones usando Playwright (incluye JS)."""
    funciones = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30000)
        page.wait_for_selector("div.js-session-row", timeout=15000)

        sessions = page.query_selector_all("div.js-session-row")
        for session in sessions:
            parent = session.query_selector("div.js-session-group")
            if not parent:
                continue

            # Fecha
            date_div = parent.query_selector("div.session-card__date")
            if not date_div:
                continue
            dia_span = date_div.query_selector("span.num_dia")
            mes_span = date_div.query_selector("span.mes")
            if not (dia_span and mes_span):
                continue

            mes_num = MESES.get(mes_span.inner_text().strip(), "01")
            anio = datetime.now().year
            fecha_iso = f"{anio}-{mes_num}-{dia_span.inner_text().strip().zfill(2)}"
            fecha_dt = datetime.strptime(fecha_iso, "%Y-%m-%d")
            fecha_label = fecha_dt.strftime("%d %b %Y")

            # Hora
            hora_span = session.query_selector("span.session-card__time-session")
            hora_txt = (hora_span.inner_text() if hora_span else "").strip()
            h = hora_txt.lower().replace(" ", "").replace("h", ":")
            m = re.match(r"^(\d{1,2})(?::?(\d{2}))?$", h)
            hora = f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}" if m else hora_txt

            # Capacidad y stock
            quota_div = session.query_selector("div.js-quota-row")
            if not quota_div:
                continue
            try:
                capacidad = int(quota_div.get_attribute("data-quota-total") or 0)
                stock = int(quota_div.get_attribute("data-stock") or 0)
                vendidas = max(0, capacidad - stock)
            except Exception:
                continue

            funciones.append({
                "fecha_label": fecha_label,
                "fecha_iso": fecha_iso,
                "hora": hora,
                "vendidas": vendidas,
                "capacidad": capacidad,
                "stock": stock
            })
        browser.close()
    return funciones

# ================== HISTORIAL ================== #
def load_historial() -> Dict[str, List[Dict]]:
    if Path(HISTORIAL_FILE).exists():
        return json.loads(Path(HISTORIAL_FILE).read_text(encoding="utf-8"))
    return {}

def save_historial(historial: Dict[str, List[Dict]]):
    Path(HISTORIAL_FILE).write_text(json.dumps(historial, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK ✓ Historial actualizado: {HISTORIAL_FILE}")

# ================== HTML ================== #
TABS_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<title>Cartelera — Magia & Teatro</title>
<style>
body{background:#000;color:#fff;font-family:sans-serif;}
.tabs{display:flex;gap:1rem;overflow-x:auto;}
.tab{padding:.5rem 1rem;background:#222;border-radius:8px;cursor:pointer;}
.tab.active{background:#d4af37;color:#000;}
.panel{margin-top:1rem;}
.item{padding:.5rem;border-bottom:1px solid #333;}
button{margin-top:.5rem;padding:.3rem .6rem;border:none;border-radius:6px;cursor:pointer;}
</style>
</head>
<body>
<h1>Cartelera — Escalera y Escondido</h1>
<div class="tabs" id="tabs"></div>
<div id="panel" class="panel"></div>
<script>
const payload = {{PAYLOAD_JSON}};
let active=Object.keys(payload.eventos)[0];
function setActive(tab){active=tab;render();}
function render(){
    const list=document.getElementById('panel'); list.innerHTML='';
    let data = payload.eventos[active].filter(f => f.fecha_iso + 'T' + f.hora >= payload.now);
    for(const x of data){
        list.innerHTML += `<div class="item">${x.fecha_label} ${x.hora} — Vendidas: ${x.vendidas} / ${x.capacidad} (stock: ${x.stock})</div>`;
    }
    // Botón historial
    const historial=payload.historial[active]||[];
    if(historial.length){
        const b=document.createElement('button');
        b.textContent='Ver sesiones pasadas';
        b.onclick=()=>{ 
            list.innerHTML='';
            for(const x of historial){
                list.innerHTML += `<div class="item">${x.fecha_label} ${x.hora} — Vendidas: ${x.vendidas} / ${x.capacidad} (stock: ${x.stock})</div>`;
            }
        };
        list.appendChild(b);
    }
}
window.addEventListener('load',()=>render());
document.getElementById('tabs').innerHTML = Object.keys(payload.eventos).map(t=>`<div class="tab ${t===active?'active':''}" onclick="setActive('${t}')">${t}</div>`).join('');
</script>
</body>
</html>
"""

def write_html(payload: Dict):
    html = TABS_HTML.replace("{{PAYLOAD_JSON}}", json.dumps(payload, ensure_ascii=False))
    Path(OUTPUT_HTML).write_text(html, encoding="utf-8")
    print(f"OK ✓ HTML generado: {OUTPUT_HTML}")

# ================== MAIN ================== #
if __name__ == "__main__":
    historial = load_historial()
    eventos_dt = {}
    now_str = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%dT%H:%M")

    for nombre, url in EVENTS.items():
        funciones = fetch_functions_dinaticket(url)
        eventos_dt[nombre] = [f for f in funciones if f"{f['fecha_iso']}T{f['hora']}" >= now_str]

        # Guardar histórico de sesiones pasadas
        pasadas = [f for f in funciones if f"{f['fecha_iso']}T{f['hora']}" < now_str]
        historial.setdefault(nombre, []).extend(pasadas)

        print(f"{nombre}: {len(funciones)} funciones totales, {len(eventos_dt[nombre])} futuras")

    save_historial(historial)

    payload = {
        "generated_at": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        "now": now_str,
        "eventos": eventos_dt,
        "historial": historial
    }
    write_html(payload)