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

    calendar_data  = None
    appcheck_token = None

    async with async_playwright() as p:
        browser = await p.webkit.launch(headless=True)
        ctx  = await browser.new_context()
        page = await ctx.new_page()

        async def on_response(resp):
            nonlocal calendar_data
            if CALENDAR_ENDPOINT in resp.url:
                try:
                    calendar_data = await resp.json()
                    print(f"  getCalendar: {resp.status}")
                except Exception as e:
                    print(f"  Error getCalendar: {e}")

        async def on_request(req):
            nonlocal appcheck_token
            if CALENDAR_ENDPOINT in req.url or SESSIONS_ENDPOINT in req.url:
                tok = req.headers.get("x-firebase-appcheck")
                if tok:
                    appcheck_token = tok

        page.on("response", on_response)
        page.on("request",  on_request)

        await page.goto(page_url, wait_until="domcontentloaded")
        await asyncio.sleep(10)
        await browser.close()

    if not calendar_data:
        print("  Sin datos de getCalendar")
        return {}

    result = calendar_data.get("result", calendar_data)
    items  = result.get("data") if isinstance(result, dict) else None
    if not isinstance(items, list):
        items = calendar_data.get("data", [])

    idx = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        date  = item.get("date") or item.get("fecha") or item.get("day")
        avail = item.get("available") if item.get("available") is not None else item.get("stock")
        if date:
            key = f"{date}|00:00"
            idx[key] = {"disponibles": int(avail) if avail is not None else None, "capacidad": None, "vendidas": None}

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
                        d_local  = datetime.strptime(fecha, "%Y-%m-%d").replace(tzinfo=TZ)
                        from_utc = (d_local - timedelta(hours=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                        to_utc   = (d_local + timedelta(hours=23)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                        payload_str = json.dumps({"data": {"eventId": event_id, "from": from_utc, "to": to_utc}})

                        js = f"""
                        async () => {{
                            const r = await fetch("{SESSIONS_ENDPOINT}", {{
                                method: "POST",
                                headers: {{"Content-Type": "application/json", "x-firebase-appcheck": "{appcheck_token}"}},
                                body: {json.dumps(payload_str)}
                            }});
                            return await r.json();
                        }}
                        """
                        res = await page2.evaluate(js)
                        if res:
                            inner    = res.get("result", res)
                            sessions = inner.get("data", []) if isinstance(inner, dict) else []
                            for s in sessions:
                                if not isinstance(s, dict):
                                    continue
                                av   = s.get("availability", {})
                                sold = av.get("sold")
                                cap  = av.get("capacity")
                                avail = av.get("available")
                                start = s.get("startTime", "")
                                try:
                                    dt_local = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).astimezone(TZ)
                                    hora_key = dt_local.strftime("%H:%M")
                                except Exception:
                                    hora_key = "00:00"
                                old_key = f"{fecha}|00:00"
                                if old_key in idx:
                                    del idx[old_key]
                                idx[f"{fecha}|{hora_key}"] = {"disponibles": avail, "capacidad": cap, "vendidas": sold}
                                print(f"  getSessions {fecha} {hora_key}: vendidas={sold}, cap={cap}, disponibles={avail}")
                                break
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
