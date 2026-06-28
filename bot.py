import asyncio
import json
import logging
import os
import re
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from game_total import build_game_total_reply, looks_like_game_message


BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images"
CHART_IMAGE_DIR = BASE_DIR / "chart_image"
STATE_FILE = BASE_DIR / "state.json"
CHAT_MEMORY_FILE = BASE_DIR / "chat_memory.json"
SETTINGS_FILE = BASE_DIR / "bot_settings.json"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
BOT_TIMEZONE = ZoneInfo("Asia/Kolkata")
QUIET_HOURS_START = time(4, 0)
QUIET_HOURS_END = time(6, 0)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


state_lock = asyncio.Lock()


def natural_sort_key(file_path: Path) -> list[int | str]:
    parts = re.split(r"(\d+)", file_path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def load_state() -> dict[str, int]:
    if not STATE_FILE.exists():
        return {}

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read state file. Starting with empty state.")
        return {}

    return {str(chat_id): int(index) for chat_id, index in data.items()}


def save_state(state: dict[str, int]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_chat_memory() -> dict[str, str]:
    if not CHAT_MEMORY_FILE.exists():
        return {}

    try:
        data = json.loads(CHAT_MEMORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read chat memory file. Starting with empty memory.")
        return {}

    if not isinstance(data, dict):
        return {}

    memory: dict[str, str] = {}
    for chat_id, value in data.items():
        key = str(chat_id)
        if isinstance(value, str) and value.strip():
            memory[key] = value.strip()
            continue
        if isinstance(value, list):
            messages = [str(item).strip() for item in value if str(item).strip()]
            if messages:
                memory[key] = messages[-1]
    return memory


def save_chat_memory(memory: dict[str, str]) -> None:
    CHAT_MEMORY_FILE.write_text(
        json.dumps(memory, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def load_settings() -> dict[str, int]:
    if not SETTINGS_FILE.exists():
        return {}

    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read settings file. Starting with empty settings.")
        return {}

    if not isinstance(data, dict):
        return {}

    settings: dict[str, int] = {}
    target_group_id = data.get("target_group_id")
    if isinstance(target_group_id, int):
        settings["target_group_id"] = target_group_id
    elif isinstance(target_group_id, str):
        parsed_target_group_id = parse_chat_id(target_group_id)
        if parsed_target_group_id is not None:
            settings["target_group_id"] = parsed_target_group_id
    return settings


def save_settings(settings: dict[str, int]) -> None:
    SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_chat_id(value: str | int | None) -> int | None:
    if value is None:
        return None

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def get_target_group_id() -> int | None:
    settings = load_settings()
    if "target_group_id" in settings:
        return settings["target_group_id"]

    return parse_chat_id(os.getenv("TARGET_GROUP_ID"))


def get_images() -> list[Path]:
    if not IMAGES_DIR.exists():
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    return sorted(
        (
            file_path
            for file_path in IMAGES_DIR.iterdir()
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
        ),
        key=natural_sort_key,
    )


def get_chart_image() -> Path | None:
    if not CHART_IMAGE_DIR.exists():
        CHART_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    chart_images = sorted(
        file_path
        for file_path in CHART_IMAGE_DIR.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return chart_images[0] if chart_images else None


def get_update_message(update: Update):
    return update.message or update.business_message or update.effective_message


def get_business_kwargs(update: Update) -> dict[str, str]:
    message = get_update_message(update)
    business_connection_id = getattr(message, "business_connection_id", None)
    if not business_connection_id:
        return {}

    return {"business_connection_id": business_connection_id}


def is_quiet_hours() -> bool:
    current_time = datetime.now(BOT_TIMEZONE).time()
    return QUIET_HOURS_START <= current_time < QUIET_HOURS_END


async def reply_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    **kwargs,
) -> None:
    message = get_update_message(update)
    await context.bot.send_message(
        chat_id=message.chat_id,
        text=text,
        **get_business_kwargs(update),
        **kwargs,
    )


async def reply_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, photo) -> None:
    message = get_update_message(update)
    await context.bot.send_photo(
        chat_id=message.chat_id,
        photo=photo,
        **get_business_kwargs(update),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    await reply_text(
        update,
        context,
        "QR image ke liye `qr` likho. Bot `images` folder ki files ko sequence order me bhejega. Chart image ke liye `chart` likho.",
        parse_mode="Markdown",
    )


async def send_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    message = get_update_message(update)
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)

    if chat_id is None:
        await reply_text(update, context, "Group ID nahi mila.")
        return

    await reply_text(update, context, f"Group ID: `{chat_id}`", parse_mode="Markdown")


async def show_target_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    target_group_id = get_target_group_id()
    if target_group_id is None:
        await reply_text(
            update,
            context,
            "Abhi target group set nahi hai. `/settargetgroup -1004304577201` ya target group ke andar `/settargetgroup` likho.",
            parse_mode="Markdown",
        )
        return

    await reply_text(
        update,
        context,
        f"Current target group ID: `{target_group_id}`",
        parse_mode="Markdown",
    )


async def set_target_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    message = get_update_message(update)
    args = list(getattr(context, "args", []) or [])

    target_group_id: int | None = None
    if args:
        target_group_id = parse_chat_id(args[0])
    else:
        chat = getattr(message, "chat", None)
        chat_type = str(getattr(chat, "type", "") or "").lower()
        if chat_type in {"group", "supergroup", "channel"}:
            target_group_id = parse_chat_id(getattr(chat, "id", None))

    if target_group_id is None:
        await reply_text(
            update,
            context,
            "Target group set karne ke liye `/settargetgroup -1004304577201` likho ya jis group ko target banana ho uske andar `/settargetgroup` likho.",
            parse_mode="Markdown",
        )
        return

    settings = load_settings()
    settings["target_group_id"] = target_group_id
    save_settings(settings)

    await reply_text(
        update,
        context,
        f"Target group set ho gaya: `{target_group_id}`",
        parse_mode="Markdown",
    )


async def clear_target_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    settings = load_settings()
    if "target_group_id" in settings:
        del settings["target_group_id"]
        save_settings(settings)

    env_target_group_id = parse_chat_id(os.getenv("TARGET_GROUP_ID"))
    if env_target_group_id is not None:
        await reply_text(
            update,
            context,
            f"Saved target group clear ho gaya. Env fallback abhi bhi `{env_target_group_id}` hai.",
            parse_mode="Markdown",
        )
        return

    await reply_text(update, context, "Target group clear ho gaya.")


async def send_next_qr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    images = get_images()
    if not images:
        await reply_text(
            update,
            context,
            "Abhi `images` folder me koi image nahi hai. JPG, PNG ya WEBP file add karo.",
        )
        return

    message = get_update_message(update)
    state_key = f"{getattr(message, 'business_connection_id', '')}:{message.chat_id}"

    async with state_lock:
        state = load_state()
        image_index = state.get(state_key, 0) % len(images)
        image_path = images[image_index]
        state[state_key] = (image_index + 1) % len(images)
        save_state(state)

    with image_path.open("rb") as image_file:
        await reply_photo(update, context, image_file)


async def send_chart_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    chart_image = get_chart_image()
    if not chart_image:
        await reply_text(
            update,
            context,
            "Abhi `chart_image` folder me chart image nahi hai. JPG, PNG ya WEBP file add karo.",
        )
        return

    with chart_image.open("rb") as image_file:
        await reply_photo(update, context, image_file)


async def send_game_total(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    message = get_update_message(update)
    reply_to_message = getattr(message, "reply_to_message", None)
    source_text = ""

    if reply_to_message and getattr(reply_to_message, "text", None):
        source_text = str(reply_to_message.text or "").strip()
    else:
        memory = load_chat_memory()
        source_text = memory.get(str(message.chat_id), "").strip()

    if not source_text:
        await reply_text(
            update,
            context,
            "Total nikalne ke liye kisi game message par reply karke `total` likho ya pehle game message bhejo.",
        )
        return

    success, reply_text_value, _summary = build_game_total_reply(source_text)
    if not success:
        await reply_text(update, context, reply_text_value)
        return

    await reply_text(update, context, reply_text_value)


async def send_ds_ok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    target_group_id = get_target_group_id()
    if target_group_id is None:
        await reply_text(
            update,
            context,
            "Target group set nahi hai. Pehle `/settargetgroup -1004304577201` ya target group ke andar `/settargetgroup` likho.",
            parse_mode="Markdown",
        )
        return

    message = get_update_message(update)
    reply_to_message = getattr(message, "reply_to_message", None)
    source_text = ""

    if reply_to_message and getattr(reply_to_message, "text", None):
        source_text = str(reply_to_message.text or "").strip()
    else:
        memory = load_chat_memory()
        source_text = memory.get(str(message.chat_id), "").strip()

    if not source_text:
        await reply_text(
            update,
            context,
            "Koi recent game message nahi mila. Pehle number wala message bhejo ya us message par reply karke `ds ok` likho.",
            parse_mode="Markdown",
        )
        return

    if not looks_like_game_message(source_text):
        await reply_text(
            update,
            context,
            "Latest message game format me nahi mila. Number wala game message bhejo ya usi par reply karke `ds ok` likho.",
            parse_mode="Markdown",
        )
        return

    await reply_text(update, context, "DISAWAR GAME OK ✔")
    await context.bot.send_message(chat_id=target_group_id, text=source_text)


async def remember_recent_game_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = get_update_message(update)
    text = str(getattr(message, "text", "") or "").strip()
    if not text:
        return

    memory = load_chat_memory()
    chat_key = str(message.chat_id)

    if re.fullmatch(r"(?i)\s*(/total|total|ds\s+ok)\s*", text):
        return

    if not looks_like_game_message(text):
        if chat_key in memory:
            del memory[chat_key]
            save_chat_memory(memory)
        return

    memory[chat_key] = text
    save_chat_memory(memory)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Please set TELEGRAM_BOT_TOKEN environment variable.")

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("groupid", send_group_id))
    application.add_handler(CommandHandler("targetgroup", show_target_group))
    application.add_handler(CommandHandler("settargetgroup", set_target_group))
    application.add_handler(CommandHandler("cleartargetgroup", clear_target_group))
    application.add_handler(CommandHandler("chart", send_chart_image))
    application.add_handler(CommandHandler("qr", send_next_qr))
    application.add_handler(CommandHandler("total", send_game_total))
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i)(chart|time|timing|\u091a\u093e\u0930\u094d\u091f|\u091f\u093e\u0907\u092e|\u091f\u093e\u0907\u092e\u093f\u0902\u0917)"
            ),
            send_chart_image,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i)(qr|\u0915\u094d\u092f\u0942\u0906\u0930|scanner|scan|barcode|bar\s*code)"
            ),
            send_next_qr,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"(?i)^\s*total\s*$"),
            send_game_total,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"(?i)^\s*ds\s+ok\s*$"),
            send_ds_ok,
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, remember_recent_game_message),
        group=1,
    )

    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        port = int(os.getenv("PORT", "10000"))
        webhook_path = os.getenv("WEBHOOK_PATH", "/telegram-webhook")
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path.lstrip("/"),
            webhook_url=f"{webhook_url.rstrip('/')}/{webhook_path.lstrip('/')}",
            allowed_updates=Update.ALL_TYPES,
        )
        return

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
