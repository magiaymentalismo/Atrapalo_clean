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
    "Disfruta": "https://www.dinaticket.com/es/provider/10402/event/4905281",
    "Miedo": "https://www.dinaticket.com/es/provider/10402/event/4915778",
    "Escondido": "https://www.dinaticket.com/es/provider/20073/event/4930233",
}

ABONO_URL = "https://compras.abonoteatro.com/?pagename=espectaculo&eventid=90857"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"}

MESES = {
    "Ene.": "01", "Feb.": "02", "Mar.": "03", "Abr.": "04", "May.": "05", "Jun.": "06",
    "Jul.": "07", "Ago.": "08", "Sep.": "09", "Oct.": "10", "Nov.": "11", "Dic.": "12"
}

# ================== TEMPLATE (HTML) ================== #
TABS_HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#000000">
<meta name="format-detection" content="telephone=no">
<meta name="color-scheme" content="dark">
<title>Cartelera — Magia & Teatro</title>

<style>
  :root{
    --bg:#000; --bg2:#090909; --panel:#0d0d0d; --card:#121212;
    --ink:#f7f7f7; --muted:#b9b9b9; --hair:#272727;
    --gold:#d4af37; --green:#22c55e; --orange:#f59e0b; --sold:#6b7280;
    --r:.9rem; --rx:999px; --pad:1rem;
  }
  body{
    margin:0; color:var(--ink);
    background: linear-gradient(180deg, #000, #0b0b0b);
    font:600 16px/1.55 -apple-system, system-ui;
  }
  .wrap{max-width:1040px; margin:0 auto; padding:1rem}

  header{position:sticky; top:0; padding:1rem; background:#000c; backdrop-filter:blur(10px)}
  h1{margin:0 0 .3rem; font:900 25px/1.2 system-ui}
  #meta{color:var(--muted); margin-bottom:.5rem}

  .tabs{display:flex; gap:.6rem; overflow-x:auto; padding-bottom:.4rem}
  .tab{
    padding:.7rem 1rem; background:#161616; border-radius:999px;
    border:1px solid var(--hair); color:var(--ink); font-weight:800;
  }
  .tab.active{background:var(--gold); color:#111}

  .panel{background:#111; padding:1rem; border-radius:.9rem}
  .list{display:flex; flex-direction:column; gap:1rem}

  .item{display:flex; justify-content:space-between; padding:1rem;
        background:#161616; border-radius:.9rem; border:1px solid #272727}

  .date{padding:.55rem .9rem; border-radius:.8rem; background:#0f0f0f; border:1px solid #2c2c2c; font-weight:900}
  .time{padding:.5rem .9rem; border-radius:999px; background:#141414; border:1px solid #2c2c2c}

  .chip{padding:.45rem .85rem; border-radius:999px; font-weight:900}
  .chip.gray{background:#2b2b2b}
  .chip.green{background:var(--green); color:#000}
  .chip.gold{background:var(--gold); color:#000}
  .chip.warn{background:var(--orange); color:#000}
  .chip.sold{background:#555; text-decoration:line-through}

  .meter{width:100%; height:8px; background:#0d0d0d; border:1px solid #2c2c2c; border-radius:6px; overflow:hidden}
  .fill{height:100%; background:linear-gradient(90deg,#198754,var(--gold)); width:0%}

  .meta2{margin-top:.3rem; color:var(--muted); font-size:.85rem}

  .month{margin:1rem 0 .3rem; color:var(--gold); font-weight:900}

  /* ABONO TEATRO badge */
  .abono-chip{
      display:inline-flex; gap:.45rem; align-items:center;
      padding:.42rem .9rem; border-radius:999px;
      font-weight:800; font-size:.8rem; border:1px solid transparent;
      margin-top:.4rem; letter-spacing:.4px;
  }
  .abono-chip .dot{
      width:9px; height:9px; border-radius:999px;
  }
  .abono-chip.ok{background:rgba(22,163,74,.15); border-color:#22c55e; color:#bbf7d0}
  .abono-chip.ok .dot{background:#22c55e}

  .abono-chip.off{background:rgba(220,38,38,.18); border-color:#f87171; color:#fecaca}
  .abono-chip.off .dot{background:#f87171}
</style>
</head>

<body>
<header>
  <div class="wrap">
    <h1>Cartelera — Escalera & Escondido</h1>
    <div id="meta"></div>
    <div id="tabs" class="tabs"></div>
  </div>
</header>

<main class="wrap">
  <section class="panel">
    <div id="list" class="list"></div>
  </section>
</main>

<script id="PAYLOAD" type="application/json">{{PAYLOAD_JSON}}</script>
<script>
const payload = JSON.parse(document.getElementById("PAYLOAD").textContent);
const eventos = payload.eventos || {};

const gen = new Date(payload.generated_at);
document.getElementById("meta").textContent =
  "Generado: " + gen.toLocaleString("es-ES");

let active = Object.keys(eventos)[0] || null;

const tabsEl = document.getElementById("tabs");
for (const sala of Object.keys(eventos)){
  const rows = eventos[sala].table.rows.length;
  const b = document.createElement("button");
  b.className = "tab" + (sala===active?" active":"");
  b.textContent = `${sala} (${rows})`;
  b.onclick = ()=>{ active=sala; updateTabs(); render(); };
  tabsEl.appendChild(b);
}

function updateTabs(){
  document.querySelectorAll(".tab").forEach(t=>{
    t.classList.toggle("active",t.textContent.startsWith(active));
  });
}

function parseRow(r){ return {
  fecha_label:r[0], hora:r[1], vendidas:r[2],
  fecha_iso:r[3], cap:r[4], stock:r[5], abono:r[6]
}; }

const DAYS=["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
function dayName(f){ return DAYS[new Date(f+'T00:00:00').getDay()] }
function render(){
  if(!active) return;
  const list = document.getElementById("list");
  list.innerHTML = "";

  let rows = eventos[active].table.rows.map(parseRow);
  rows.sort((a,b)=> (a.fecha_iso + a.hora).localeCompare(b.fecha_iso + b.hora));

  let currentMonth = "";
  for (const x of rows){
    const d = new Date(x.fecha_iso + "T00:00:00");
    const monthKey = d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0");
    const monthLabel = d.toLocaleDateString("es-ES",{month:"long",year:"numeric"});
    if(monthKey!==currentMonth){
      currentMonth=monthKey;
      list.insertAdjacentHTML("beforeend",`<h3 class="month">${monthLabel}</h3>`);
    }

    const fecha = `${x.fecha_label} (${dayName(x.fecha_iso)})`;

    let chipClass="chip gray";
    if(x.vendidas>=1) chipClass="chip green";
    if(x.vendidas>=10) chipClass="chip gold";
    if(x.stock===0) chipClass="chip sold";

    let abonoHTML="";
    if (x.abono==="venta"){
      abonoHTML = `
      <div class="abono-chip ok">
        <span class="dot"></span>
        <span>Abono Teatro · SIGUEN EN VENTA</span>
      </div>`;
    } else if (x.abono==="agotado"){
      abonoHTML = `
      <div class="abono-chip off">
        <span class="dot"></span>
        <span>Abono Teatro · AGOTADO</span>
      </div>`;
    }

    list.insertAdjacentHTML("beforeend",`
      <div class="item">
        <div class="left">
          <div class="date">${fecha}</div>
          <div class="time">${x.hora}</div>
        </div>

        <div style="min-width:220px; text-align:right">
          <span class="${chipClass}">Vendidas: <b>${x.vendidas}</b></span>
          ${abonoHTML}
        </div>
      </div>
    `);
  }
}

if(active) render();
</script>
</body>
</html>
"""

# ===================== SCRAPER DINATICKET ===================== #
def fetch_functions_dinaticket(url: str) -> list[dict]:
    r = requests.get(url, headers=UA, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")

    out=[]
    now = datetime.now(ZoneInfo("Europe/Madrid"))

    for s in soup.find_all("div","js-session-row"):
        parent=s.find_parent("div","js-session-group")
        if not parent: continue

        ddiv=parent.find("div","session-card__date")
        if not ddiv: continue

        dia=ddiv.find("span","num_dia")
        mes=ddiv.find("span","mes")
        if not (dia and mes): continue

        mes_num=MESES.get(mes.text.strip(),"01")
        fecha = datetime(now.year, int(mes_num), int(dia.text))

        if fecha.date() < now.date():
            fecha = fecha.replace(year=now.year+1)

        fecha_iso=fecha.strftime("%Y-%m-%d")
        fecha_label=fecha.strftime("%d %b %Y")

        h=s.find("span","session-card__time-session")
        htxt=(h.text or "").strip().lower().replace(" ","").replace("h",":")
        m=re.match(r"^(\d{1,2})(?::?(\d{2}))?$",htxt)
        hora=f"{int(m.group(1)):02d}:{int(m.group(2) or '00'):02d}" if m else "00:00"

        quota=s.find("div","js-quota-row")
        cap=int(quota.get("data-quota-total",0))
        stock=int(quota.get("data-stock",0))
        vendidas=max(0,cap-stock)

        out.append({
            "fecha_label":fecha_label,
            "fecha_iso":fecha_iso,
            "hora":hora,
            "vendidas_dt":vendidas,
            "capacidad":cap,
            "stock":stock
        })

    return out

# ===================== SCRAPER ABONO ===================== #
def fetch_abono():
    r=requests.get(ABONO_URL,headers=UA,timeout=20)
    soup=BeautifulSoup(r.text,"html.parser")

    fechas=[]
    for box in soup.find_all("div","bsesion"):
        month = box.find("p",class_="psess")
        day = box.find("p",class_="psesb")
        time = box.find("h3",class_="horasesion")
        if not(month and day and time): continue

        texto_mes = month.text.strip().lower()
        partes = texto_mes.split()
        mes_txt = partes[0][:3].capitalize()
        mes_num = MESES.get(mes_txt,"01")

        año = int(partes[-1])
        dia = day.text.strip().zfill(2)

        fecha_iso=f"{año}-{mes_num}-{dia}"
        hora_clean = time.text.replace(" ", "").replace("í","i").lower()
        hm = re.findall(r"(\d{1,2}):(\d{2})",hora_clean)
        if hm:
            hora=f"{hm[0][0]}:{hm[0][1]}"
        else:
            hora="00:00"

        fechas.append((fecha_iso,hora))

    print("DEBUG AbonoTeatro fechas:",fechas)
    return set(fechas)

# ===================== MERGE + PAYLOAD ===================== #
def build_event_rows(funcs:list[dict]) -> list[list]:
    return [[f["fecha_label"],f["hora"],f["vendidas_dt"],f["fecha_iso"],f["capacidad"],f["stock"],f.get("abono")] for f in funcs]

def build_payload(eventos:dict[str,list[dict]])->dict:
    return {
        "generated_at": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        "eventos":{
            sala:{
                "table":{
                    "headers":["Fecha","Hora","Vendidas","FechaISO","Capacidad","Stock","Abono"],
                    "rows":build_event_rows(funcs)
                }
            } for sala,funcs in eventos.items()
        }
    }

def write_html(payload):
    html=TABS_HTML.replace("{{PAYLOAD_JSON}}",
        json.dumps(payload,ensure_ascii=False).replace("</script>","<\\/script>")
    )
    Path("docs").mkdir(exist_ok=True)
    Path("docs/index.html").write_text(html,"utf-8")
    print("✔ Generado docs/index.html")

# ============================== MAIN ============================== #
if __name__=="__main__":
    print("Descargando Dinaticket…")
    eventos={}
    for nombre,url in EVENTS.items():
        funcs=fetch_functions_dinaticket(url)
        eventos[nombre]=funcs
        print(f"{nombre}: {len(funcs)} funciones")

    print("Descargando Abono Teatro…")
    abono=set(fetch_abono())

    # Asignar estado de abono a funciones de Escondido
    for f in eventos["Escondido"]:
        clave=(f["fecha_iso"],f["hora"])
        f["abono"] = "venta" if clave in abono else "agotado"

    payload=build_payload(eventos)
    write_html(payload)