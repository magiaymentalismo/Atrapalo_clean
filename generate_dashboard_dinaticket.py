#!/usr/bin/env python3
from __future__ import annotations

import json, re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ===================== CONFIG ===================== #
EVENTS = {
    "Escondido": "https://www.dinaticket.com/es/provider/20073/event/4919204",
    "Escalera": "https://www.dinaticket.com/es/provider/10402/event/4923185"
}

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"}

MESES = {
    "Ene.": "01", "Feb.": "02", "Mar.": "03", "Abr.": "04", "May.": "05", "Jun.": "06",
    "Jul.": "07", "Ago.": "08", "Sep.": "09", "Oct.": "10", "Nov.": "11", "Dic.": "12"
}

HISTORIC_FILE = Path("docs/historic.json")
OUTPUT_HTML = Path("docs/dashboard_tabs.html")

# ================== SCRAPER ================== #
def fetch_functions_dinaticket(url: str, timeout: int = 20) -> list[dict]:
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    funciones = []
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
        anio = datetime.now().year
        fecha_iso = f"{anio}-{mes_num}-{dia.text.strip().zfill(2)}"
        fecha_dt = datetime.strptime(fecha_iso, "%Y-%m-%d")
        fecha_label = fecha_dt.strftime("%d %b %Y")

        hora_span = session.find("span", class_="session-card__time-session")
        hora_txt = (hora_span.text or "").strip()
        h = hora_txt.lower().replace(" ", "").replace("h", ":")
        m = re.match(r"^(\d{1,2})(?::?(\d{2}))?$", h)
        if m:
            hh = int(m.group(1)); mm = int(m.group(2) or "00")
            hora = f"{hh:02d}:{mm:02d}"
        else:
            hora = hora_txt.strip()

        quota_row = session.find("div", class_="js-quota-row")
        if not quota_row:
            continue
        try:
            capacidad = int(quota_row.get("data-quota-total", 0))
            stock = int(quota_row.get("data-stock", 0))
            vendidas = max(0, capacidad - stock)
        except Exception:
            continue

        funciones.append({
            "fecha_label": fecha_label,
            "fecha_iso": fecha_iso,
            "hora": hora,
            "vendidas_dt": vendidas,
            "capacidad": capacidad,
            "stock": stock
        })
    return funciones

# ============== PAYLOAD ================== #
def build_event_rows(funcs_dt: list[dict]) -> list[list]:
    return [[f["fecha_label"], f["hora"], f["vendidas_dt"], f["fecha_iso"], f.get("capacidad"), f.get("stock")] for f in funcs_dt]

def build_tabbed_payload(eventos_dt: dict[str, list[dict]]) -> dict:
    eventos_out = {}
    for nombre, funciones in eventos_dt.items():
        rows = build_event_rows(funciones)
        eventos_out[nombre] = {"table": {"headers": ["Fecha","Hora","Vendidas","FechaISO","Capacidad","Stock"], "rows": rows}}
    return {
        "generated_at": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        "meta": {"source": "Dinaticket", "note": "Legible alto contraste; Escondido con capacidad/stock y % ocupación"},
        "eventos": eventos_out
    }

# ============== HISTÓRICO ================== #
def load_historic() -> dict:
    if HISTORIC_FILE.exists():
        return json.loads(HISTORIC_FILE.read_text(encoding="utf-8"))
    return {}

def save_historic(historic: dict) -> None:
    HISTORIC_FILE.parent.mkdir(exist_ok=True)
    HISTORIC_FILE.write_text(json.dumps(historic, ensure_ascii=False, indent=2), encoding="utf-8")

def merge_historic(new: dict, historic: dict) -> dict:
    for evento, data in new["eventos"].items():
        old_rows = {row[3]: row for row in historic.get(evento, {}).get("table", {}).get("rows", [])}
        for row in data["table"]["rows"]:
            old_rows[row[3]] = row  # sobrescribe si existe, agrega si no
        data["table"]["rows"] = list(old_rows.values())
    return new

# ================== HTML ================== #
TABS_HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cartelera — Magia & Teatro</title>
<style>
body{background:#000;color:#fff;font-family:sans-serif;}
h1{color:#d4af37;}
.tab{cursor:pointer;padding:.5rem 1rem;margin:.2rem;background:#222;display:inline-block;border-radius:5px;}
.tab.active{background:#d4af37;color:#000;}
.item{padding:.5rem;border-bottom:1px solid #333;margin:.2rem 0;}
</style>
</head>
<body>
<h1>Cartelera — Escalera de Jacob y Escondido</h1>
<div id="tabs"></div>
<div id="list"></div>

<script id="PAYLOAD" type="application/json">{{PAYLOAD_JSON}}</script>
<script>
const payload = JSON.parse(document.getElementById('PAYLOAD').textContent);
const eventos = payload.eventos;
let active = Object.keys(eventos)[0];

function render(){
    const listEl = document.getElementById('list');
    listEl.innerHTML = '';
    const rows = eventos[active].table.rows.sort((a,b)=> (a[3]+a[1]).localeCompare(b[3]+b[1]));
    let currentMonth='';
    for(const r of rows){
        const date = new Date(r[3]+'T00:00:00');
        const monthKey = `${date.getFullYear()}-${date.getMonth()+1}`;
        if(monthKey!==currentMonth){
            currentMonth = monthKey;
            listEl.insertAdjacentHTML('beforeend', `<h3>${date.toLocaleDateString('es-ES',{month:'long',year:'numeric'})}</h3>`);
        }
        listEl.insertAdjacentHTML('beforeend', `<div class="item">${r[0]} ${r[1]} — Vendidas: ${r[2]}</div>`);
    }
}

function initTabs(){
    const tabsEl = document.getElementById('tabs');
    tabsEl.innerHTML='';
    Object.keys(eventos).forEach((e,i)=>{
        const b=document.createElement('div');
        b.className='tab'+(i===0?' active':''); b.textContent=`${e} (${eventos[e].table.rows.length})`;
        b.onclick=()=>{active=e; document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active')); b.classList.add('active'); render();}
        tabsEl.appendChild(b);
    });
}

initTabs();
render();
</script>
</body>
</html>
"""

def write_tabs_html(payload: dict, out_html: Path = OUTPUT_HTML) -> None:
    out_html.parent.mkdir(exist_ok=True)
    html = TABS_HTML.replace("{{PAYLOAD_JSON}}", json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>"))
    out_html.write_text(html, encoding="utf-8")
    print(f"OK ✓ Escribí {out_html} (abrilo en tu navegador).")

# ============================== MAIN ============================== #
if __name__ == "__main__":
    eventos_dt: dict[str, list[dict]] = {}
    for nombre, url in EVENTS.items():
        funciones = fetch_functions_dinaticket(url)
        eventos_dt[nombre] = funciones
        print(f"{nombre}: {len(funciones)} funciones")

    payload = build_tabbed_payload(eventos_dt)
    historic = load_historic()
    merged = merge_historic(payload, historic)
    save_historic(merged)
    write_tabs_html(merged)