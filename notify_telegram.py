#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PREV    = Path("docs/schedule_prev.json")
CURR    = Path("docs/schedule.json")

def send(text):
    import urllib.request
    url  = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode()
    req  = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)

def get_rows(data):
    out = {}
    for sala, info in (data.get("eventos") or {}).items():
        rows = ((info.get("proximas") or {}).get("table") or {}).get("rows") or []
        for r in rows:
            if len(r) >= 4:
                key = f"{sala}::{r[3]}::{r[1]}"
                out[key] = {
                    "sala": sala, "fecha": r[0], "hora": r[1],
                    "vendidas": r[2], "cap": r[4] if len(r)>4 else None,
                    "stock": r[5] if len(r)>5 else None,
                    "kVend": r[8] if len(r)>8 else None,
                    "kCap": r[9] if len(r)>9 else None
                }
    return out

def has_valid_data(rows):
    for r in rows.values():
        if r["vendidas"] is not None:
            return True
    return False

if not CURR.exists():
    sys.exit(0)

curr_data = json.loads(CURR.read_text())
curr = get_rows(curr_data)

if not has_valid_data(curr):
    print("Datos inválidos — saliendo.")
    sys.exit(0)

# Cargar maximos historicos
if PREV.exists():
    try:
        maximos = json.loads(PREV.read_text())
    except Exception:
        maximos = {}
else:
    maximos = {}

changes = []

for key, c in curr.items():
    sala  = c["sala"]
    fecha = c["fecha"]
    hora  = c["hora"]

    try:
        cv = int(c["vendidas"]) if c["vendidas"] is not None else None
    except Exception:
        cv = None

    pv = maximos.get(key)  # maximo historico conocido

    if cv is not None:
        if pv is None:
            # Primera vez que vemos esta funcion
            maximos[key] = cv
        elif cv > pv:
            # Subida real — avisar y actualizar maximo
            diff = cv - pv
            cap_str = f"/{c['cap']}" if c['cap'] else ""
            changes.append(f"📈 *{sala}* — {fecha} {hora}\nDina: {cv}{cap_str} (+{diff})")
            maximos[key] = cv
        # Si cv <= pv: no avisar, no actualizar maximo

    try:
        ckv = int(c["kVend"]) if c["kVend"] is not None else None
    except Exception:
        ckv = None

    pkv = maximos.get(f"{key}::k")

    if ckv is not None:
        if pkv is None:
            maximos[f"{key}::k"] = ckv
        elif ckv > pkv:
            diff = ckv - pkv
            cap_str = f"/{c['kCap']}" if c['kCap'] else ""
            changes.append(f"📈 *{sala}* — {fecha} {hora}\nKultur: {ckv}{cap_str} (+{diff})")
            maximos[f"{key}::k"] = ckv

# Guardar maximos actualizados
PREV.write_text(json.dumps(maximos, ensure_ascii=False, indent=2))

if not changes:
    print("Sin cambios.")
    sys.exit(0)

if not TOKEN or not CHAT_ID:
    print("Sin credenciales Telegram.")
    sys.exit(0)

msg = "🎭 *Actualización de ventas*\n\n" + "\n\n".join(changes)
send(msg)
print(f"Enviado: {len(changes)} cambios.")
