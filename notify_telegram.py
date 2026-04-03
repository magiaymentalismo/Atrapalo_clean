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

if not CURR.exists():
    sys.exit(0)

curr_data = json.loads(CURR.read_text())
curr = get_rows(curr_data)

if not PREV.exists():
    PREV.write_text(CURR.read_text())
    print("Primera vez: snapshot guardado.")
    sys.exit(0)

prev = get_rows(json.loads(PREV.read_text()))
changes = []

for key, c in curr.items():
    p = prev.get(key)
    sala  = c["sala"]
    fecha = c["fecha"]
    hora  = c["hora"]

    try:
        cv = int(c["vendidas"]) if c["vendidas"] is not None else None
        pv = int(p["vendidas"]) if p and p["vendidas"] is not None else None
    except Exception:
        cv = pv = None

    if cv is not None and pv is not None and cv != pv:
        diff = cv - pv
        emoji = "📈" if diff > 0 else "📉"
        cap_str = f"/{c['cap']}" if c['cap'] else ""
        changes.append(f"{emoji} *{sala}* — {fecha} {hora}\nDina: {cv}{cap_str} ({'+' if diff>0 else ''}{diff})")

    try:
        ckv = int(c["kVend"]) if c["kVend"] is not None else None
        pkv = int(p["kVend"]) if p and p["kVend"] is not None else None
    except Exception:
        ckv = pkv = None

    if ckv is not None and pkv is not None and ckv != pkv:
        diff = ckv - pkv
        emoji = "📈" if diff > 0 else "📉"
        cap_str = f"/{c['kCap']}" if c['kCap'] else ""
        changes.append(f"{emoji} *{sala}* — {fecha} {hora}\nKultur: {ckv}{cap_str} ({'+' if diff>0 else ''}{diff})")

PREV.write_text(CURR.read_text())

if not changes:
    print("Sin cambios.")
    sys.exit(0)

if not TOKEN or not CHAT_ID:
    print("Sin credenciales Telegram.")
    sys.exit(0)

msg = "🎭 *Actualización de ventas*\n\n" + "\n\n".join(changes)
send(msg)
print(f"Enviado: {len(changes)} cambios.")
