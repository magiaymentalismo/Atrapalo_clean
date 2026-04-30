#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
import urllib.request

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

PREV = Path("docs/schedule_prev.json")
CURR = Path("docs/schedule.json")


def send(text):
    if not TOKEN or not CHAT_ID:
        print("Sin credenciales Telegram.")
        sys.exit(0)

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    urllib.request.urlopen(req, timeout=10)


def to_int(value):
    if value in (None, "", "—", "-", "N/A", "NA"):
        return None

    try:
        return int(str(value).replace(".", "").replace(",", ""))
    except Exception:
        return None


def get_rows(data):
    out = {}

    for sala, info in (data.get("eventos") or {}).items():
        rows = ((info.get("proximas") or {}).get("table") or {}).get("rows") or []

        for r in rows:
            if len(r) >= 4:
                key = f"{sala}::{r[3]}::{r[1]}"

                out[key] = {
                    "sala": sala,
                    "fecha": r[0],
                    "hora": r[1],
                    "vendidas": r[2],
                    "cap": r[4] if len(r) > 4 else None,
                    "stock": r[5] if len(r) > 5 else None,
                    "kVend": r[8] if len(r) > 8 else None,
                    "kCap": r[9] if len(r) > 9 else None,
                }

    return out


def has_valid_data(rows):
    return any(r["vendidas"] is not None for r in rows.values())


def main():
    if not CURR.exists():
        print("No existe docs/schedule.json.")
        sys.exit(0)

    curr_data = json.loads(CURR.read_text(encoding="utf-8"))
    curr = get_rows(curr_data)

    if not has_valid_data(curr):
        print("Datos inválidos — saliendo.")
        sys.exit(0)

    if PREV.exists():
        try:
            maximos = json.loads(PREV.read_text(encoding="utf-8"))
        except Exception:
            maximos = {}
    else:
        maximos = {}

    changes = []

    for key, c in curr.items():
        sala = c["sala"]
        fecha = c["fecha"]
        hora = c["hora"]

        cv = to_int(c["vendidas"])
        pv = maximos.get(key)

        if cv is not None:
            if pv is None:
                maximos[key] = cv
            elif cv > pv:
                diff = cv - pv
                cap_str = f"/{c['cap']}" if c["cap"] else ""
                changes.append(
                    f"📈 *{sala}* — {fecha} {hora}\n"
                    f"Dina: {cv}{cap_str} (+{diff})"
                )
                maximos[key] = cv

        ckv = to_int(c["kVend"])
        pkv = maximos.get(f"{key}::k")

        if ckv is not None:
            if pkv is None:
                maximos[f"{key}::k"] = ckv
            elif ckv > pkv:
                diff = ckv - pkv
                cap_str = f"/{c['kCap']}" if c["kCap"] else ""
                changes.append(
                    f"📈 *{sala}* — {fecha} {hora}\n"
                    f"Kultur: {ckv}{cap_str} (+{diff})"
                )
                maximos[f"{key}::k"] = ckv

    PREV.parent.mkdir(parents=True, exist_ok=True)
    PREV.write_text(json.dumps(maximos, ensure_ascii=False, indent=2), encoding="utf-8")

    if not changes:
        print("Sin cambios.")
        sys.exit(0)

    msg = "🎭 *Actualización de ventas*\n\n" + "\n\n".join(changes)
    send(msg)

    print(f"Enviado: {len(changes)} cambios.")


if __name__ == "__main__":
    main()
