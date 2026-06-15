import asyncio
import json
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images"
CHART_IMAGE_DIR = BASE_DIR / "chart_image"
STATE_FILE = BASE_DIR / "state.json"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


state_lock = asyncio.Lock()


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


def get_images() -> list[Path]:
    if not IMAGES_DIR.exists():
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    return sorted(
        file_path
        for file_path in IMAGES_DIR.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
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
    await reply_text(
        update,
        context,
        "QR image ke liye `qr` likho. Chart image ke liye `chart` likho.",
        parse_mode="Markdown",
    )


async def send_next_qr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Please set TELEGRAM_BOT_TOKEN environment variable.")

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("chart", send_chart_image))
    application.add_handler(CommandHandler("qr", send_next_qr))
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"(?i)(chart|\u091a\u093e\u0930\u094d\u091f)"),
            send_chart_image,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(r"(?i)(qr|\u0915\u094d\u092f\u0942\u0906\u0930|scanner|scan)"),
            send_next_qr,
        )
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
