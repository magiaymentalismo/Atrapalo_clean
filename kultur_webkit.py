#!/usr/bin/env python3
"""
Fetcher de Kultur via WebKit (Safari engine) — macOS only.
Llama a getCalendar para todas las fechas, y getSessions para las que
estan dentro de las proximas 48hs.
Guarda: docs/kultur_cache_{sala}.json
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

TZ = ZoneInfo("Europe/Madrid")
DOCS_DIR = Path("docs")

KULTUR_EVENTS = {
    "Escondido": "YaWZRG4MCxo1CHvr",
    "Miedo":     "BW8A51aMmrnmTQzH",
}

KULTUR_PAGES = {
    "Escondido": "https://appkultur.com/madrid/el-juego-de-la-mente-magia-mental-con-ariel-hamui",
    "Miedo":     "https://appkultur.com/madrid/miedo-mentalismo-y-espiritismo-con-ariel-hamui",
}

SESSIONS_ENDPOINT = "https://europe-west6-kultur-platform.cloudfunctions.net/events_api_v2-getSessions"
CALENDAR_ENDPOINT = "https://europe-west6-kultur-platform.cloudfunctions.net/events_api_v2-getCalendar"


async def fetch_kultur_data(sala: str) -> dict:
    event_id = KULTUR_EVENTS[sala]
    page_url  = KULTUR_PAGES[sala]
    now       = datetime.now(TZ)

    print(f"\n{'='*50}")
    print(f"  Kultur WebKit [{sala}]")
    print(f"{'='*50}")
    print(f"  -> Abriendo {page_url}...")

    calendar_data = None
    appcheck_token = None
    calendar_event = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.webkit.launch(headless=True)
        ctx  = await browser.new_context()
        page = await ctx.new_page()

        async def on_response(resp):
            nonlocal calendar_data
            if CALENDAR_ENDPOINT in resp.url:
                try:
                    status = resp.status
                    print(f"  getCalendar: {status}")
                    data = await resp.json()

                    result = data.get("result", data) if isinstance(data, dict) else {}
                    items = result.get("data") if isinstance(result, dict) else None

                    if status == 200 and isinstance(items, list):
                        calendar_data = data
                        calendar_event.set()
                    else:
                        print(
                            f"  getCalendar ignorado: status={status}, "
                            f"items={len(items) if isinstance(items, list) else 'None'}"
                        )
                except Exception as e:
                    print(f"  Error parseando getCalendar: {e}")

        async def on_request(req):
            nonlocal appcheck_token
            if CALENDAR_ENDPOINT in req.url or SESSIONS_ENDPOINT in req.url:
                tok = req.headers.get("x-firebase-appcheck")
                if tok:
                    appcheck_token = tok

        page.on("request", on_request)
        page.on("response", on_response)

        for attempt in (1, 2):
            try:
                if attempt == 1:
                    print("  -> Intento 1 cargando pagina")
                    await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                else:
                    print("  -> Intento 2 recargando pagina")
                    calendar_event.clear()
                    await page.reload(wait_until="domcontentloaded", timeout=30000)

                await page.wait_for_timeout(8000)

                try:
                    await asyncio.wait_for(calendar_event.wait(), timeout=15)
                except Exception:
                    print(f"  Error esperando getCalendar en intento {attempt}")

                if calendar_data:
                    break

                try:
                    await page.mouse.wheel(0, 800)
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass
            except Exception as e:
                print(f"  Error cargando pagina en intento {attempt}: {e}")

            if calendar_data:
                break

        await asyncio.sleep(2)
        await browser.close()

    if not calendar_data:
        print("  Sin datos de getCalendar")
        return {}

    result = calendar_data.get("result", calendar_data)
    items  = result.get("data") if isinstance(result, dict) else None
    if not isinstance(items, list):
        items = calendar_data.get("data", [])

    idx = {}
    calendar_avail_by_date = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        date = item.get("date") or item.get("fecha") or item.get("day")
        avail = item.get("available") if item.get("available") is not None else item.get("stock")
        avail_int = int(avail) if avail is not None else None
        if date:
            calendar_avail_by_date[date] = avail_int
            key = f"{date}|00:00"
            idx[key] = {"disponibles": avail_int, "capacidad": None, "vendidas": None}

    print(f"  -> {len(idx)} fechas en calendario")

    if appcheck_token:
        dates_to_check = []
        for key in list(idx.keys()):
            fecha = key.split("|")[0]
            try:
                d = datetime.strptime(fecha, "%Y-%m-%d").replace(tzinfo=TZ)
                if -86400 < (d - now).total_seconds() <= 172800:
                    dates_to_check.append(fecha)
            except Exception:
                pass

        if dates_to_check:
            print(f"  -> getSessions para {len(dates_to_check)} fecha(s) proximas: {dates_to_check}")
            async with async_playwright() as p2:
                browser2 = await p2.webkit.launch(headless=True)
                ctx2  = await browser2.new_context()
                page2 = await ctx2.new_page()

                for fecha in dates_to_check:
                    try:
                        d_local = datetime.strptime(fecha, "%Y-%m-%d").replace(tzinfo=TZ)
                        day_start_local = d_local.replace(hour=0, minute=0, second=0, microsecond=0)
                        day_end_local = day_start_local + timedelta(days=1)
                        from_utc = day_start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                        to_utc = day_end_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                        payload = {"data": {"eventId": event_id, "from": from_utc, "to": to_utc}}

                        js = f"""
                        async () => {{
                            const payload = {json.dumps(payload)};
                            const r = await fetch("{SESSIONS_ENDPOINT}", {{
                                method: "POST",
                                headers: {{"Content-Type": "application/json", "x-firebase-appcheck": "{appcheck_token}"}},
                                body: JSON.stringify(payload)
                            }});
                            return await r.json();
                        }}
                        """
                        res = await page2.evaluate(js)
                        if res:
                            inner = res.get("result", res)
                            sessions = inner.get("data", []) if isinstance(inner, dict) else []
                            calendar_available = calendar_avail_by_date.get(fecha)
                            valid_sessions = []

                            for s in sessions:
                                if not isinstance(s, dict):
                                    continue

                                av = s.get("availability") or {}
                                sold = av.get("sold")
                                cap = av.get("capacity")
                                avail = av.get("available")
                                start = s.get("startTime", "")

                                try:
                                    dt_local = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).astimezone(TZ)
                                    hora_key = dt_local.strftime("%H:%M")
                                except Exception:
                                    hora_key = "00:00"

                                suspicious_zero = (
                                    (calendar_available is not None and calendar_available > 0)
                                    and (avail in (0, None))
                                    and (cap in (0, None))
                                )

                                if suspicious_zero:
                                    print(
                                        f"  getSessions {fecha} {hora_key}: ignorado por inconsistente "
                                        f"(calendar={calendar_available}, vendidas={sold}, cap={cap}, disponibles={avail})"
                                    )
                                    continue

                                valid_sessions.append((hora_key, avail, cap, sold))

                            if valid_sessions:
                                old_key = f"{fecha}|00:00"
                                if old_key in idx:
                                    del idx[old_key]

                                for hora_key, avail, cap, sold in valid_sessions:
                                    final_avail = avail if avail is not None else calendar_available
                                    idx[f"{fecha}|{hora_key}"] = {
                                        "disponibles": final_avail,
                                        "capacidad": cap,
                                        "vendidas": sold,
                                    }
                                    print(f"  getSessions {fecha} {hora_key}: vendidas={sold}, cap={cap}, disponibles={final_avail}")
                            else:
                                print(f"  getSessions {fecha}: sin sesiones validas; se conserva getCalendar={calendar_available}")
                    except Exception as e:
                        print(f"  getSessions {fecha}: error - {e}")

                await browser2.close()
        else:
            print("  -> Sin fechas proximas para getSessions")
    else:
        print("  Sin token AppCheck - saltando getSessions")

    return idx


def main():
    DOCS_DIR.mkdir(exist_ok=True)
    for sala in KULTUR_EVENTS:
        idx = asyncio.run(fetch_kultur_data(sala))
        if not idx:
            print(f"  Sin datos para {sala}")
            continue
        cache_path = DOCS_DIR / f"kultur_cache_{sala}.json"
        cache_path.write_text(json.dumps({"idx": idx}, ensure_ascii=False, indent=2), "utf-8")
        print(f"\n  Cache guardado: {cache_path} ({len(idx)} sesiones)")
        print(f"\n  Resumen {sala}:")
        for k, v in list(idx.items())[:10]:
            print(f"    {k} -> {v}")


if __name__ == "__main__":
    main()
