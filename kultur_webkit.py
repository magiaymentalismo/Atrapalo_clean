#!/usr/bin/env python3
"""
Fetch Kultur calendar usando Playwright WebKit (Safari engine).
WebKit genera un X-Firebase-AppCheck válido, igual que Safari desktop.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
DOCS_DIR = Path("docs")

# eventId por sala — sacarlos de la URL o de las DevTools
KULTUR_EVENTS = {
    "Escondido": "YaWZRG4MCxo1CHvr",
    "Miedo":     "BW8A51aMmrnmTQzH",
}

KULTUR_PAGES = {
    "Escondido": "https://appkultur.com/madrid/el-juego-de-la-mente-magia-mental-con-ariel-hamui",
    "Miedo":     "https://appkultur.com/madrid/miedo-mentalismo-y-espiritismo-con-ariel-hamui",
}

CALENDAR_URL = "https://europe-west6-kultur-platform.cloudfunctions.net/events_api_v2-getCalendar"


def fetch_kultur_webkit(sala: str) -> dict:
    """
    Abre la página con WebKit, intercepta la llamada a getCalendar,
    y devuelve el JSON de respuesta.
    También intenta capturar la respuesta si ya fue hecha antes de que
    podamos interceptarla.
    """
    from playwright.sync_api import sync_playwright

    now = datetime.now(TZ)
    event_id = KULTUR_EVENTS[sala]
    page_url = KULTUR_PAGES[sala]

    result: dict = {}
    captured: list[dict] = []

    with sync_playwright() as p:
        # WEBKIT = Safari engine, genera App Check token válido
        browser = p.webkit.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        def on_response(resp):
            if "getCalendar" in resp.url:
                try:
                    data = resp.json()
                    captured.append(data)
                    print(f"  ✓ getCalendar capturado: {resp.status}")
                except Exception as e:
                    print(f"  ⚠ getCalendar error al parsear: {e}")

        page.on("response", on_response)

        print(f"  → Abriendo {page_url} con WebKit...")
        page.goto(page_url, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # Si no capturamos nada aún, intentar hacer la llamada manualmente
        # desde el contexto del navegador (ya tiene el App Check token)
        if not captured:
            print("  → No capturado aún, intentando fetch manual desde el browser...")
            from_date = now.strftime("%Y-%m-%d")
            to_date = (now + timedelta(days=60)).strftime("%Y-%m-%d")

            try:
                js_result = page.evaluate(f"""
                    async () => {{
                        const resp = await fetch(
                            "https://europe-west6-kultur-platform.cloudfunctions.net/events_api_v2-getCalendar",
                            {{
                                method: "POST",
                                headers: {{
                                    "Content-Type": "application/json",
                                    "Accept": "*/*",
                                }},
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
                    print(f"  ✓ getCalendar via fetch manual: OK")
            except Exception as e:
                print(f"  ⚠ fetch manual falló: {e}")

        browser.close()

    if captured:
        result = captured[0]

    return result


def parse_kultur_response(data: dict) -> dict[str, dict]:
    """
    Convierte la respuesta de getCalendar a idx:
    'YYYY-MM-DD|HH:MM' -> {disponibles, capacidad, vendidas}
    
    La respuesta tiene: result.data = [{date, available, time?, capacity?}, ...]
    """
    idx: dict[str, dict] = {}

    # Navegar la estructura
    items = None
    if isinstance(data, dict):
        # {"result": {"status": 200, "data": [...]}}
        result = data.get("result", data)
        if isinstance(result, dict):
            items = result.get("data", result.get("sessions", result.get("items")))
        if items is None:
            # {"data": [...]}
            items = data.get("data")

    if not isinstance(items, list):
        print(f"  ⚠ No se encontró lista de sesiones en: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        return idx

    print(f"  → {len(items)} sesiones encontradas")

    for item in items:
        if not isinstance(item, dict):
            continue

        date = item.get("date") or item.get("fecha") or item.get("day")
        time = item.get("time") or item.get("hora") or item.get("hour") or "00:00"
        available = item.get("available") or item.get("stock") or item.get("disponibles") or 0
        capacity = item.get("capacity") or item.get("capacidad") or item.get("total")
        sold = item.get("sold") or item.get("vendidas") or item.get("booked")

        if not date:
            continue

        # Normalizar hora
        time_str = str(time).strip()
        if ":" not in time_str:
            time_str = "00:00"

        try:
            available = int(available)
        except Exception:
            available = 0

        try:
            capacity = int(capacity) if capacity is not None else None
        except Exception:
            capacity = None

        try:
            sold = int(sold) if sold is not None else None
        except Exception:
            sold = None

        if sold is None and capacity is not None:
            sold = max(0, capacity - available)

        key = f"{date}|{time_str}"
        idx[key] = {
            "disponibles": available,
            "capacidad": capacity,
            "vendidas": sold,
        }
        print(f"    {key}: disponibles={available}, cap={capacity}, vendidas={sold}")

    return idx


def fetch_and_write_kultur_cache(sala: str) -> dict:
    """Entry point principal — reemplaza al que usaba Chromium."""
    DOCS_DIR.mkdir(exist_ok=True)

    print(f"\n{'='*50}")
    print(f"  Kultur WebKit [{sala}]")
    print(f"{'='*50}")

    raw = fetch_kultur_webkit(sala)

    if not raw:
        print(f"  ❌ No se obtuvo respuesta")
        return {}

    # Guardar raw para debug
    raw_path = DOCS_DIR / f"kultur_raw_{sala}.json"
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), "utf-8")
    print(f"  → Raw guardado en {raw_path}")

    idx = parse_kultur_response(raw)

    data = {"idx": idx}
    out_path = DOCS_DIR / f"kultur_cache_{sala}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    print(f"  ✔ Cache guardado: {out_path} ({len(idx)} sesiones)")

    return data


if __name__ == "__main__":
    for sala in KULTUR_EVENTS:
        try:
            result = fetch_and_write_kultur_cache(sala)
            idx = result.get("idx", {})
            if idx:
                print(f"\n  Resumen {sala}:")
                for k, v in sorted(idx.items()):
                    print(f"    {k} → {v}")
            else:
                print(f"\n  ⚠ {sala}: cache vacío")
        except Exception as e:
            import traceback
            print(f"\n❌ Error en {sala}: {e}")
            traceback.print_exc()