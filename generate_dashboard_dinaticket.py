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

# ================== TEMPLATE (HTML) ================== #
TABS_HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>Cartelera — Magia & Teatro</title>

<style>
  :root{
    --bg:#000; --bg2:#090909; --panel:#0d0d0d;
    --ink:#f7f7f7; --muted:#b9b9b9; --hair:#272727;
    --gold:#d4af37; --green:#22c55e; --orange:#f59e0b; --sold:#6b7280;
    --r:.9rem; --rx:999px;
  }

  body{
    background:linear-gradient(180deg, var(--bg), var(--bg2));
    margin:0; color:var(--ink);
    font:600 16px/1.55 system-ui;
  }

  .wrap{max-width:1040px; margin:0 auto; padding:1rem}

  h1{margin:0 0 .35rem; font:900 24px/1.2 system-ui}

  #meta{margin-top:.25rem; color:var(--muted); font-size:.9rem}

  .tabs{
    display:flex; gap:.6rem; margin-top:.7rem;
    overflow-x:auto; padding:.2rem 0 .5rem;
  }
  .tab{
    padding:.7rem 1rem; border-radius:var(--rx);
    border:1px solid var(--hair); background:#161616;
    font-weight:800; cursor:pointer; color:var(--ink);
  }
  .tab.active{
    background:var(--gold); color:#111;
  }

  /* SUBTABS */
  .subtabs{
    display:flex; gap:.5rem; margin:1rem 0 .8rem;
    border-bottom:1px solid var(--hair); padding-bottom:.4rem;
  }
  .subtab{
    padding:.45rem .9rem; border-radius:var(--rx);
    background:#141414; border:1px solid var(--hair);
    font-weight:800; cursor:pointer; color:#9ca3af;
  }
  .subtab.active{
    background:#fff; color:#111;
  }

  .panel{
    background:#111; padding:1rem; border-radius:var(--r);
  }

  .list{display:flex; flex-direction:column; gap:1rem}

  .item{
    padding:1rem; border-radius:var(--r);
    border:1px solid var(--hair);
    display:flex; justify-content:space-between;
    background:#161616;
  }

  .chip{
    padding:.4rem .8rem; border-radius:var(--rx);
    font-weight:900;
  }
  .chip.green{background:var(--green); color:#000}
  .chip.gold{background:var(--gold); color:#000}
  .chip.gray{background:#444}
  .chip.warn{background:var(--orange); color:#000}
  .chip.sold{background:#555; text-decoration:line-through}

  .month{
    margin:1.2rem 0 .4rem;
    font-weight:900;
    font-size:.96rem;
    text-transform:capitalize;
    color:var(--gold);
    letter-spacing:.03em;
  }

  .abono-chip{
    font-size:.78rem;
    padding:.25rem .7rem;
    opacity:0.95;
  }
</style>
</head>

<body>
<div class="wrap">
  <h1>Cartelera — Escalera & Escondido</h1>
  <div id="meta"></div>
  <div id="tabs" class="tabs"></div>

  <div class="panel">
    <div id="subtabs" class="subtabs"></div>
    <div id="list" class="list"></div>
  </div>
</div>

<script id="PAYLOAD" type="application/json">{{PAYLOAD_JSON}}</script>

<script>
const payload = JSON.parse(document.getElementById("PAYLOAD").textContent);
const eventos = payload.eventos || {};
let active = Object.keys(eventos)[0] || null;
let subMode = "proximas"; // o "pasadas"

document.getElementById("meta").textContent =
  "Generado: " + new Date(payload.generated_at).toLocaleString("es-ES");

// === Crear tabs principales (con contador) ===
const tabsEl = document.getElementById("tabs");
for (const sala of Object.keys(eventos)) {
  const ev = eventos[sala];

  let total = 0;
  if (ev.proximas && ev.proximas.table && Array.isArray(ev.proximas.table.rows)) {
    total += ev.proximas.table.rows.length;
  }
  if (ev.pasadas && ev.pasadas.table && Array.isArray(ev.pasadas.table.rows)) {
    total += ev.pasadas.table.rows.length;
  }
  if (!total && ev.table && Array.isArray(ev.table.rows)) {
    total = ev.table.rows.length;
  }

  const b = document.createElement("button");
  b.textContent = `${sala} (${total})`;
  b.dataset.tab = sala;
  b.className = "tab" + (sala === active ? " active" : "");
  b.onclick = () => { active = sala; updateTabs(); render(); };
  tabsEl.appendChild(b);
}

function updateTabs(){
  document.querySelectorAll(".tab").forEach(t=>{
    t.classList.toggle("active", t.dataset.tab === active);
  });
}

// === Crear subtabs ===
const subtabsEl = document.getElementById("subtabs");
["proximas","pasadas"].forEach(mode=>{
  const sb = document.createElement("button");
  sb.textContent = mode==="proximas" ? "Próximas" : "Pasadas";
  sb.dataset.mode = mode;
  sb.className = "subtab" + (subMode===mode ? " active" : "");
  sb.onclick = () => { subMode = mode; updateSubtabs(); render(); };
  subtabsEl.appendChild(sb);
});

function updateSubtabs(){
  document.querySelectorAll(".subtab").forEach(s=>{
    s.classList.toggle("active", s.dataset.mode === subMode);
  });
}

// === Día de la semana ===
const DAYS = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
function dayName(fechaIso){
  const d = new Date(fechaIso + "T00:00:00");
  return DAYS[d.getDay()];
}

// ---- Util para leer filas según estructura del payload ----
function getRowsForActiveAndMode(){
  const ev = eventos[active];
  if (!ev) return [];

  // Caso 1: payload con proximas/pasadas
  if (ev.proximas || ev.pasadas){
    const sec = ev[subMode];
    if (!sec || !sec.table || !Array.isArray(sec.table.rows)) return [];
    return sec.table.rows || [];
  }

  // Caso 2 (fallback): payload plano con table.rows y filtramos aquí
  if (!ev.table || !Array.isArray(ev.table.rows)) return [];
  let rows = ev.table.rows;

  rows = rows.map(r => ({
    fecha_label: r[0],
    hora: r[1],
    vendidas: r[2],
    fecha_iso: r[3],
    cap: r[4],
    stock: r[5],
    abono: (r.length >= 7 ? r[6] : null)
  }));

  const today = new Date();
  today.setHours(0,0,0,0);

  rows = rows.filter(r=>{
    const hora = r.hora || "00:00";
    const dt = new Date(r.fecha_iso + "T" + hora + ":00");
    const dtDay = new Date(dt);
    dtDay.setHours(0,0,0,0);
    return subMode === "pasadas" ? dtDay < today : dtDay >= today;
  });

  return rows.map(r => [r.fecha_label, r.hora, r.vendidas, r.fecha_iso, r.cap, r.stock, r.abono]);
}

// === Render ===
function render(){
  const cont = document.getElementById("list");
  cont.innerHTML = "";
  if (!active || !eventos[active]) return;

  let rows = getRowsForActiveAndMode();
  if (!rows || rows.length === 0){
    cont.innerHTML = "<p style='color:#9ca3af'>Sin funciones en esta vista.</p>";
    return;
  }

  // Parse rows normalizados (7 columnas: incluye Abono)
  rows = rows.map(r => ({
    fecha_label: r[0],
    hora: r[1],
    vendidas: r[2],
    fecha_iso: r[3],
    cap: r[4],
    stock: r[5],
    abono: (r.length >= 7 ? r[6] : null)
  }));

  // Ordenar
  rows.sort((a,b)=> (a.fecha_iso + a.hora).localeCompare(b.fecha_iso + b.hora));

  // Agrupar por mes
  let currentMonthKey = null;
  for (const r of rows){
    const d = new Date(r.fecha_iso + "T00:00:00");
    const monthKey = d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0");
    if (monthKey !== currentMonthKey){
      currentMonthKey = monthKey;
      const label = d.toLocaleDateString("es-ES", { month: "long", year: "numeric" });
      const h = document.createElement("h3");
      h.className = "month";
      h.textContent = label;
      cont.appendChild(h);
    }

    const div = document.createElement("div");
    div.className="item";

    // chip color por vendidas
    let chip="gray";
    if (r.vendidas >=10) chip="gold";
    else if (r.vendidas >=1) chip="green";
    if (r.stock === 0) chip="sold";

    const esEscondido = (active === "Escondido");
    let abonoHTML = "";
    if (esEscondido && r.abono) {
      if (r.abono === "venta") {
        abonoHTML = `<div class="chip green abono-chip">Abono Teatro: siguen en venta</div>`;
      } else if (r.abono === "agotado") {
        abonoHTML = `<div class="chip sold abono-chip">Abono Teatro agotado</div>`;
      }
    }

    // === Texto "vendidas / capacidad" para Escondido ===
    let ventaLabel = `Vendidas: ${r.vendidas}`;
    if (esEscondido && r.cap){
      const cap = Number(r.cap) || 0;
      const stock = (typeof r.stock === "number") ? r.stock : null;
      const quedanTxt = (stock !== null) ? ` · quedan ${stock}` : "";
      ventaLabel = `Vendidas: ${r.vendidas} / ${cap}${quedanTxt}`;
    }

    const diaSemana = dayName(r.fecha_iso);

    div.innerHTML = `
      <div><b>${r.fecha_label} (${diaSemana})</b> — ${r.hora}</div>
      <div style="display:flex; flex-direction:column; gap:.3rem; align-items:flex-end">
        <div class="chip ${chip}">${ventaLabel}</div>
        ${abonoHTML}
      </div>
    `;
    cont.appendChild(div);
  }
}

render();
</script>
</body>
</html>
"""

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
        now = datetime.now(ZoneInfo("Europe/Madrid"))
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
    Separa en PROXIMAS / PASADAS en el servidor.
    Añade info de AbonoTeatro solo a Escondido:
      - 'venta'   si (fecha,hora) está en AbonoTeatro
      - 'venta'   si no coincide la hora pero hay sesión ese día en AbonoTeatro
      - 'agotado' si no aparece ese día en AbonoTeatro
    """
    today = datetime.now(ZoneInfo("Europe/Madrid")).date()
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
                    # Coincide fecha + hora exacta
                    f["abono_estado"] = "venta"
                elif fecha in abono_fechas:
                    # No coincide la hora pero sí hay sesión ese día en AbonoTeatro
                    f["abono_estado"] = "venta"
                else:
                    # Ese día no existe en AbonoTeatro
                    f["abono_estado"] = "agotado"
        else:
            for f in funcs:
                f.setdefault("abono_estado", None)

        proximas: list[dict] = []
        pasadas: list[dict] = []
        for f in funcs:
            try:
                d = datetime.strptime(f["fecha_iso"], "%Y-%m-%d").date()
            except Exception:
                continue
            if d >= today:
                proximas.append(f)
            else:
                pasadas.append(f)

        out[sala] = {
            "proximas": {
                "table": {
                    "headers": ["Fecha","Hora","Vendidas","FechaISO","Capacidad","Stock","Abono"],
                    "rows": build_rows(proximas),
                }
            },
            "pasadas":  {
                "table": {
                    "headers": ["Fecha","Hora","Vendidas","FechaISO","Capacidad","Stock","Abono"],
                    "rows": build_rows(pasadas),
                }
            },
        }

    return {
        "generated_at": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        "eventos": out,
    }

def write_html(payload: dict) -> None:
    html = TABS_HTML.replace(
        "{{PAYLOAD_JSON}}",
        json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")
    )
    Path("docs").mkdir(exist_ok=True)
    Path("docs/index.html").write_text(html, "utf-8")
    print("✔ Generado docs/index.html")

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