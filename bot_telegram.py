import os, json, re, requests, time, logging
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

# ------------------ Config ------------------
URL = "https://magiaymentalismo.github.io/Atrapalo_clean/?v=1632222"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux) AppleWebKit/537.36 Chrome/123 Safari/537.36"}
TZ = ZoneInfo("Europe/Madrid")
TELEGRAM_LIMIT = 4096
CACHE_TTL = 60  # segundos
STATE_FILE = Path("state.json")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_cache: Tuple[float, Dict[str, Any]] | None = None


def _now() -> float:
    return time.monotonic()


# ------------------ Utils ------------------
def _normalize_int(x) -> Optional[int]:
    if x in (None, "", "—", "-", "N/A", "NA"):
        return None
    try:
        s = str(x).replace(".", "").replace(",", "")
        return int(s)
    except Exception:
        return None


def _split_for_telegram(text: str, limit: int = TELEGRAM_LIMIT) -> List[str]:
    if len(text) <= limit:
        return [text]
    parts, chunk = [], []
    total = 0
    for line in text.splitlines(keepends=True):
        if total + len(line) > limit:
            parts.append("".join(chunk))
            chunk, total = [line], len(line)
        else:
            chunk.append(line)
            total += len(line)
    if chunk:
        parts.append("".join(chunk))
    return parts


def _extract_payload_from_html(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    tag = soup.find("script", id="PAYLOAD")
    if tag and tag.string:
        return json.loads(tag.string)

    tag = soup.find("script", attrs={"data-payload": True})
    if tag and tag.string:
        return json.loads(tag.string)

    for s in soup.find_all("script"):
        txt = s.string or ""
        m = re.search(r"window\.PAYLOAD\s*=\s*(\{.*?\})\s*;?", txt, flags=re.S)
        if m:
            return json.loads(m.group(1))

    raise ValueError("No encontré el PAYLOAD en el HTML.")


def fetch_payload(force: bool = False) -> Dict[str, Any]:
    global _cache
    if (not force) and _cache and (_now() - _cache[0] < CACHE_TTL):
        return _cache[1]
    r = requests.get(URL, headers=UA, timeout=20)
    r.raise_for_status()
    data = _extract_payload_from_html(r.text)
    _cache = (_now(), data)
    return data


def _safe_pct(vendidas: Optional[int], cap: Optional[int]) -> Optional[int]:
    if vendidas is None or cap in (None, 0):
        return None
    try:
        return round((vendidas / cap) * 100)
    except Exception:
        return None


def _fmt_extra(vendidas, cap, stock) -> str:
    parts = []
    if cap is not None and vendidas is not None:
        pct = _safe_pct(vendidas, cap)
        if pct is not None:
            parts.append(f"{vendidas}/{cap} ({pct}%)")
        else:
            parts.append(f"{vendidas}/{cap}")
    elif vendidas is not None:
        parts.append(f"vendidas {vendidas}")
    if stock not in (None, ""):
        parts.append(f"quedan {stock}")
    return (" · " + " · ".join(parts)) if parts else ""


def format_resume(data: Dict[str, Any], evento: Optional[str] = None, top: int = 5) -> str:
    eventos = data.get("eventos", {})
    gen_str = data.get("generated_at") or data.get("generatedAt") or datetime.now(tz=TZ).isoformat()
    try:
        gen_dt = datetime.fromisoformat(gen_str.replace("Z", "+00:00")).astimezone(TZ)
    except Exception:
        gen_dt = datetime.now(tz=TZ)
    header = f"🪄 Cartelera (actualizado {gen_dt:%d/%m %H:%M})"

    lines = [header]
    keys = list(eventos.keys())
    if evento:
        wanted = evento.casefold()
        keys = [k for k in keys if wanted in k.casefold()]
        if not keys:
            return f"No encontré un evento que contenga “{evento}”."

    for k in keys:
        rows = (eventos[k].get("table", {}).get("rows", []))[:top]
        if not rows:
            continue
        lines.append(f"\n— {k} —")
        for r in rows:
            fecha_label = r[0]
            hora = r[1]
            vendidas = _normalize_int(r[2] if len(r) > 2 else None)
            cap = _normalize_int(r[4] if len(r) > 4 else None)
            stock = _normalize_int(r[5] if len(r) > 5 else None)
            extra = _fmt_extra(vendidas, cap, stock)
            lines.append(f"• {fecha_label} {hora}{extra}")
    return "\n".join(lines) if len(lines) > 1 else "Sin funciones."


def _iter_all_rows(data: Dict[str, Any]):
    for k, v in (data.get("eventos") or {}).items():
        for r in v.get("table", {}).get("rows", []):
            yield k, r


async def _reply_long(update: Update, text: str):
    for part in _split_for_telegram(text):
        if update.callback_query:
            await update.callback_query.message.reply_text(part)
        else:
            await update.message.reply_text(part)


# ------------------ Estado persistente ------------------
def _load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"subscribers": [], "counts": {}}


def _save_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("No pude guardar state.json: %s", e)


def _is_subscribed(chat_id: int) -> bool:
    st = _load_state()
    return chat_id in st.get("subscribers", [])


def _subscribe(chat_id: int) -> bool:
    st = _load_state()
    if chat_id not in st["subscribers"]:
        st["subscribers"].append(chat_id)
        _save_state(st)
        return True
    return False


def _unsubscribe(chat_id: int) -> bool:
    st = _load_state()
    if chat_id in st["subscribers"]:
        st["subscribers"].remove(chat_id)
        _save_state(st)
        return True
    return False


# ------------------ Comandos ------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = fetch_payload()
    eventos = list((data.get("eventos") or {}).keys())

    buttons, row = [], []
    for name in eventos[:6]:
        row.append(InlineKeyboardButton(name, callback_data=f"evento_exact:{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🪄 Todos", callback_data="status")])

    chat_id = update.effective_chat.id
    if _is_subscribed(chat_id):
        sub_btn = InlineKeyboardButton("🔕 Desuscribirme", callback_data="sub:off")
    else:
        sub_btn = InlineKeyboardButton("🔔 Suscribirme", callback_data="sub:on")
    buttons.append([sub_btn])

    await update.message.reply_text(
        "🎩 ¡Hola! Soy el bot de la cartelera.\n¿De qué show querés saber hoy?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        data = fetch_payload()
        msg = format_resume(data, evento=None, top=10)
        await _reply_long(update, msg)
    except Exception as e:
        await update.message.reply_text(f"Error leyendo datos: {e}")


async def evento_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        q = " ".join(ctx.args).strip()
        if not q:
            await update.message.reply_text("Uso: /evento <texto>")
            return
        data = fetch_payload()
        msg = format_resume(data, evento=q, top=20)
        await _reply_long(update, msg)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ------------------ Polling de cambios ------------------
async def poll_and_notify(context):
    try:
        data = fetch_payload()
    except Exception as e:
        logger.warning("No pude obtener payload en poll: %s", e)
        return

    state = _load_state()
    last_counts: Dict[str, int] = state.get("counts", {})
    changes = []

    current_functions = []
    eventos = data.get("eventos", {})
    for evento, info in (eventos or {}).items():
        for r in (info.get("table", {}) or {}).get("rows", []):
            fecha_label, hora = r[0], r[1]
            vendidas = _normalize_int(r[2] if len(r) > 2 else None)
            fecha_iso = r[3] if len(r) > 3 else ""
            cap = _normalize_int(r[4] if len(r) > 4 else None)
            stock = _normalize_int(r[5] if len(r) > 5 else None)
            key = f"{evento}::{fecha_iso}::{hora}"
            current_functions.append(
                {"key": key, "evento": evento, "fecha_label": fecha_label, "hora": hora, "vendidas": vendidas, "cap": cap, "stock": stock}
            )

    for f in current_functions:
        k = f["key"]
        v = f["vendidas"] or 0
        prev = last_counts.get(k)
        if prev is None:
            changes.append(f"🆕 *Nueva función* — {f['evento']}\n• {f['fecha_label']} {f['hora']}")
        elif v > prev:
            diff = v - prev
            extra = _fmt_extra(v, f["cap"], f["stock"])
            changes.append(f"📈 *Nuevas ventas* (+{diff}) — {f['evento']}\n• {f['fecha_label']} {f['hora']}{extra}")
        last_counts[k] = v

    state["counts"] = {f["key"]: f["vendidas"] or 0 for f in current_functions}
    _save_state(state)

    if changes and state["subscribers"]:
        text = "🔔 *Actualizaciones de cartelera*\n\n" + "\n\n".join(changes)
        for chat_id in state["subscribers"]:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            except Exception as e:
                logger.warning("No pude enviar alerta a %s: %s", chat_id, e)


# ------------------ Botones ------------------
async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "status":
        data_json = fetch_payload()
        msg = format_resume(data_json, evento=None, top=10)
        await _reply_long(update, msg)
        return

    if data.startswith("evento_exact:"):
        nombre = data.split(":", 1)[1]
        data_json = fetch_payload()
        msg = format_resume(data_json, evento=nombre, top=20)
        await _reply_long(update, msg)
        return

    if data == "sub:on":
        changed = _subscribe(update.effective_chat.id)
        text = "✅ Suscripción activa. Te avisaré cuando suban las ventas o aparezcan funciones nuevas." if changed else "Ya estabas suscrito ✅"
        await query.message.reply_text(text)
        return

    if data == "sub:off":
        changed = _unsubscribe(update.effective_chat.id)
        text = "❌ Suscripción cancelada. Ya no enviaré alertas." if changed else "No estabas suscrito."
        await query.message.reply_text(text)
        return

    await query.edit_message_text("No entendí tu selección 😅")


# ------------------ Main ------------------
def main():
    token = "8566367368:AAGK4ottcT8QLuMlCQ_k541T2ZNqEw-7JzE"  # tu token directo

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("evento", evento_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.job_queue.run_repeating(poll_and_notify, interval=120, first=5)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
