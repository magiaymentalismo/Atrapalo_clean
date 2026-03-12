#!/usr/bin/env python3
"""
Debug script para inspeccionar qué devuelve Kultur via red.
Ejecutar: python3 debug_kultur.py
Genera: debug_kultur_Escondido.json y debug_kultur_Miedo.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")

KULTUR_URLS = {
    "Miedo": "https://appkultur.com/madrid/miedo-mentalismo-y-espiritismo-con-ariel-hamui",
    "Escondido": "https://appkultur.com/madrid/el-juego-de-la-mente-magia-mental-con-ariel-hamui",
}


def debug_kultur(sala: str, url: str) -> None:
    from playwright.sync_api import sync_playwright

    all_responses = []

    print(f"\n{'='*60}")
    print(f"  Abriendo Kultur [{sala}]: {url}")
    print(f"{'='*60}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()

        def on_response(resp):
            try:
                ct = (resp.headers.get("content-type") or "").lower()
                entry = {
                    "url": resp.url,
                    "status": resp.status,
                    "content_type": ct,
                    "request_method": resp.request.method,
                    "request_headers": dict(resp.request.headers),
                }

                # Capturar body si es JSON o GraphQL o fetch de API
                is_json = "application/json" in ct
                is_graphql = "graphql" in ct or "graphql" in resp.url.lower()
                is_api = "/api/" in resp.url or "api." in resp.url

                if is_json or is_graphql or is_api:
                    try:
                        entry["body"] = resp.json()
                    except Exception:
                        try:
                            entry["body_text"] = resp.text()
                        except Exception:
                            entry["body_text"] = "(no se pudo leer)"

                all_responses.append(entry)
            except Exception as e:
                all_responses.append({"error": str(e), "url": getattr(resp, "url", "?")})

        page.on("response", on_response)

        print(f"  → Navegando...")
        page.goto(url, wait_until="domcontentloaded")
        print(f"  → Esperando JS (8s)...")
        page.wait_for_timeout(8000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # Intentar scroll para forzar carga lazy
        print(f"  → Scrolling para forzar carga lazy...")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(3000)

        # Capturar HTML final por si los datos están en el DOM
        html_final = page.content()
        Path(f"debug_kultur_{sala}_page.html").write_text(html_final, "utf-8")
        print(f"  → HTML guardado en debug_kultur_{sala}_page.html")

        browser.close()

    # Guardar JSON completo
    out = Path(f"debug_kultur_{sala}.json")
    out.write_text(json.dumps(all_responses, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n✔ {len(all_responses)} respuestas capturadas → {out}")

    # ---- RESUMEN ----
    print(f"\n--- URLs capturadas (todas) ---")
    for r in all_responses:
        url_r = r.get("url", "?")
        status = r.get("status", "?")
        ct = r.get("content_type", "")
        has_body = "body" in r or "body_text" in r
        marker = " ← JSON/API" if has_body else ""
        print(f"  [{status}] {url_r[:120]}{marker}")

    print(f"\n--- Detalle de respuestas JSON/API ---")
    found_any = False
    for r in all_responses:
        if "body" not in r and "body_text" not in r:
            continue
        found_any = True
        print(f"\n  URL: {r['url']}")
        print(f"  Status: {r['status']} | CT: {r['content_type']}")
        body = r.get("body") or r.get("body_text")
        body_str = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
        # Imprimir primeros 800 chars
        preview = body_str[:800]
        print(f"  Body preview: {preview}")
        if len(body_str) > 800:
            print(f"  ... ({len(body_str)} chars total)")

    if not found_any:
        print("  ⚠️  No se capturó ninguna respuesta JSON/API")
        print("  → Puede que los datos estén en el HTML directamente.")
        print(f"  → Revisar debug_kultur_{sala}_page.html")

        # Buscar datos en el HTML
        print(f"\n--- Buscando datos en el HTML ---")
        patterns = [
            r'"sessions?":\s*\[',
            r'"fechas?":\s*\[',
            r'"eventos?":\s*\[',
            r'"dates?":\s*\[',
            r'"schedule":\s*\[',
            r'"stock"\s*:',
            r'"capacidad"\s*:',
            r'"vendidas"\s*:',
            r'"available"\s*:',
            r'window\.__',
            r'__NEXT_DATA__',
            r'__NUXT__',
            r'window\.initialData',
        ]
        for pat in patterns:
            m = re.search(pat, html_final, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 30)
                end = min(len(html_final), m.end() + 200)
                print(f"  ✓ Encontrado '{pat}':")
                print(f"    {html_final[start:end]!r}")


if __name__ == "__main__":
    for sala, url in KULTUR_URLS.items():
        try:
            debug_kultur(sala, url)
        except Exception as e:
            print(f"\n❌ Error en {sala}: {e}")
            import traceback
            traceback.print_exc()

    print("\n\nListo. Revisa:")
    print("  - debug_kultur_Escondido.json")
    print("  - debug_kultur_Miedo.json")
    print("  - debug_kultur_Escondido_page.html")
    print("  - debug_kultur_Miedo_page.html")
