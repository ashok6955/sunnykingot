import asyncio
import json
import logging
import os
import re
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from telegram import ChatPermissions, Update
from telegram.error import TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters

from game_total import build_game_total_reply, looks_like_game_message


BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images"
CHART_IMAGE_DIR = BASE_DIR / "chart_image"
STATE_FILE = BASE_DIR / "state.json"
CHAT_MEMORY_FILE = BASE_DIR / "chat_memory.json"
SETTINGS_FILE = BASE_DIR / "bot_settings.json"
RELAY_STATE_FILE = BASE_DIR / "relay_state.json"
GROUP_LOCK_STATE_FILE = BASE_DIR / "group_lock_state.json"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
BOT_TIMEZONE = ZoneInfo("Asia/Kolkata")
QUIET_HOURS_START = time(4, 0)
QUIET_HOURS_END = time(5, 20)
GAME_OK_TRIGGER_TEXT = "🎮 GAME OK ✔️✔️"


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


state_lock = asyncio.Lock()
group_lock_task: asyncio.Task | None = None


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


def load_chat_memory() -> dict[str, list[str]]:
    if not CHAT_MEMORY_FILE.exists():
        return {}

    try:
        data = json.loads(CHAT_MEMORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read chat memory file. Starting with empty memory.")
        return {}

    if not isinstance(data, dict):
        return {}

    memory: dict[str, list[str]] = {}
    for chat_id, value in data.items():
        key = str(chat_id)
        if isinstance(value, str) and value.strip():
            memory[key] = [value.strip()]
            continue
        if isinstance(value, list):
            messages = [str(item).strip() for item in value if str(item).strip()]
            if messages:
                memory[key] = messages
    return memory


def save_chat_memory(memory: dict[str, list[str]]) -> None:
    CHAT_MEMORY_FILE.write_text(
        json.dumps(memory, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def load_relay_state() -> dict[str, dict[str, int | str | list[str] | list[dict[str, int | str]]]]:
    if not RELAY_STATE_FILE.exists():
        return {}

    try:
        data = json.loads(RELAY_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read relay state file. Starting with empty relay state.")
        return {}

    if not isinstance(data, dict):
        return {}

    relay_state: dict[str, dict[str, int | str | list[str] | list[dict[str, int | str]]]] = {}
    for relay_key, relay_value in data.items():
        if not isinstance(relay_key, str) or not isinstance(relay_value, dict):
            continue

        message_id = parse_chat_id(relay_value.get("message_id"))
        user_label = str(relay_value.get("user_label", "") or "").strip()
        user_id = parse_chat_id(relay_value.get("user_id"))
        entries_raw = relay_value.get("entries", [])
        entries = [str(item).strip() for item in entries_raw if str(item).strip()] if isinstance(entries_raw, list) else []
        pending_raw = relay_value.get("pending_screenshots", [])
        pending_screenshots: list[dict[str, int | str]] = []
        if isinstance(pending_raw, list):
            for pending_item in pending_raw:
                if not isinstance(pending_item, dict):
                    continue
                pending_message_id = parse_chat_id(pending_item.get("message_id"))
                pending_entry_text = str(pending_item.get("entry_text", "") or "").strip()
                if pending_message_id is None:
                    continue
                pending_screenshots.append(
                    {
                        "message_id": int(pending_message_id),
                        "entry_text": pending_entry_text or "[SCREENSHOT] Screenshot received",
                    }
                )

        relay_state[relay_key] = {
            "message_id": int(message_id or 0),
            "user_label": user_label,
            "user_id": int(user_id or 0),
            "entries": entries[-200:],
            "pending_screenshots": pending_screenshots[-50:],
        }

    return relay_state


def save_relay_state(relay_state: dict[str, dict[str, int | str | list[str] | list[dict[str, int | str]]]]) -> None:
    RELAY_STATE_FILE.write_text(
        json.dumps(relay_state, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def load_group_lock_state() -> dict[str, str]:
    if not GROUP_LOCK_STATE_FILE.exists():
        return {}

    try:
        data = json.loads(GROUP_LOCK_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read group lock state file. Starting with empty lock state.")
        return {}

    if not isinstance(data, dict):
        return {}

    return {str(key): str(value) for key, value in data.items() if isinstance(key, str)}


def save_group_lock_state(lock_state: dict[str, str]) -> None:
    GROUP_LOCK_STATE_FILE.write_text(
        json.dumps(lock_state, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def load_settings() -> dict[str, int | dict[str, int]]:
    if not SETTINGS_FILE.exists():
        return {}

    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read settings file. Starting with empty settings.")
        return {}

    if not isinstance(data, dict):
        return {}

    settings: dict[str, int | dict[str, int]] = {}

    for key in (
        "target_group_id",
        "game_target_group_id",
        "source_group_id",
        "relay_chat_id",
        "admin_forum_group_id",
        "owner_user_id",
    ):
        value = data.get(key)
        if isinstance(value, int):
            settings[key] = value
            continue
        if isinstance(value, str):
            parsed_value = parse_chat_id(value)
            if parsed_value is not None:
                settings[key] = parsed_value

    topic_map_data = data.get("user_topic_map")
    if isinstance(topic_map_data, dict):
        parsed_topic_map: dict[str, int] = {}
        for user_key, thread_value in topic_map_data.items():
            if not isinstance(user_key, str):
                continue
            parsed_thread_id = parse_chat_id(thread_value)
            if parsed_thread_id is None:
                continue
            parsed_topic_map[user_key] = parsed_thread_id
        settings["user_topic_map"] = parsed_topic_map

    return settings


def save_settings(settings: dict[str, int | dict[str, int]]) -> None:
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
        return int(settings["target_group_id"])

    return parse_chat_id(os.getenv("TARGET_GROUP_ID"))


def get_game_target_group_id() -> int | None:
    settings = load_settings()
    if "game_target_group_id" in settings:
        return int(settings["game_target_group_id"])

    return parse_chat_id(os.getenv("GAME_TARGET_GROUP_ID")) or get_target_group_id()


def get_source_group_id() -> int | None:
    settings = load_settings()
    if "source_group_id" in settings:
        return int(settings["source_group_id"])

    return parse_chat_id(os.getenv("SOURCE_GROUP_ID"))


def get_relay_chat_id() -> int | None:
    settings = load_settings()
    if "relay_chat_id" in settings:
        return int(settings["relay_chat_id"])
    if "admin_forum_group_id" in settings:
        return int(settings["admin_forum_group_id"])

    return (
        parse_chat_id(os.getenv("RELAY_CHAT_ID"))
        or parse_chat_id(os.getenv("ADMIN_FORUM_GROUP_ID"))
        or parse_chat_id(os.getenv("ADMIN_CHAT_ID"))
    )


def get_owner_user_id() -> int | None:
    settings = load_settings()
    if "owner_user_id" in settings:
        return int(settings["owner_user_id"])

    return parse_chat_id(os.getenv("OWNER_USER_ID"))


def get_recent_game_messages(memory: dict[str, list[str]], chat_id: int, limit: int = 10) -> list[str]:
    messages = memory.get(str(chat_id), [])
    return [message for message in messages if message.strip()][-limit:]


def build_locked_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False,
    )


def build_unlocked_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


async def apply_source_group_lock(bot, source_group_id: int, lock_group: bool) -> None:
    permissions = build_locked_permissions() if lock_group else build_unlocked_permissions()
    await bot.set_chat_permissions(
        chat_id=source_group_id,
        permissions=permissions,
        use_independent_chat_permissions=True,
    )


async def enforce_source_group_lock(bot) -> None:
    source_group_id = get_source_group_id()
    if source_group_id is None:
        return

    now = datetime.now(BOT_TIMEZONE)
    today_key = now.strftime("%Y-%m-%d")
    current_time = now.time()
    lock_state = load_group_lock_state()
    last_locked_date = lock_state.get("last_locked_date", "")
    last_unlocked_date = lock_state.get("last_unlocked_date", "")

    if QUIET_HOURS_START <= current_time < QUIET_HOURS_END:
        if last_locked_date == today_key:
            return
        await apply_source_group_lock(bot, source_group_id, True)
        lock_state["last_locked_date"] = today_key
        save_group_lock_state(lock_state)
        logger.info("Source group locked automatically for date=%s chat_id=%s", today_key, source_group_id)
        return

    if current_time >= QUIET_HOURS_END and last_unlocked_date == today_key:
        return

    await apply_source_group_lock(bot, source_group_id, False)
    lock_state["last_unlocked_date"] = today_key
    save_group_lock_state(lock_state)
    logger.info("Source group unlocked automatically for date=%s chat_id=%s", today_key, source_group_id)


async def source_group_lock_worker(application: Application) -> None:
    while True:
        try:
            await enforce_source_group_lock(application.bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic source group lock worker failed.")
        await asyncio.sleep(30)


async def on_application_start(application: Application) -> None:
    global group_lock_task

    await enforce_source_group_lock(application.bot)
    group_lock_task = asyncio.create_task(source_group_lock_worker(application))


async def on_application_shutdown(application: Application) -> None:
    del application
    global group_lock_task

    if group_lock_task is None:
        return

    group_lock_task.cancel()
    try:
        await group_lock_task
    except asyncio.CancelledError:
        pass
    group_lock_task = None


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


async def send_with_retry(send_callable, *args, retries: int = 2, retry_delay: float = 1.0, **kwargs):
    last_error = None
    for attempt in range(retries + 1):
        try:
            return await send_callable(*args, **kwargs)
        except TimedOut as error:
            last_error = error
            logger.warning("Telegram request timed out on attempt %s/%s", attempt + 1, retries + 1)
            if attempt >= retries:
                raise
            await asyncio.sleep(retry_delay)

    raise last_error


async def telegram_api_post(method: str, payload: dict, files: dict | None = None) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Please set TELEGRAM_BOT_TOKEN environment variable.")

    url = f"https://api.telegram.org/bot{token}/{method}"
    timeout = httpx.Timeout(30.0, connect=30.0, read=30.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if files:
            response = await client.post(url, data=payload, files=files)
        else:
            response = await client.post(url, json=payload)
        response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed: {data}")

    return data["result"]


def build_user_label(user) -> str:
    first_name = str(getattr(user, "first_name", "") or "").strip()
    last_name = str(getattr(user, "last_name", "") or "").strip()
    username = str(getattr(user, "username", "") or "").strip()

    base = " ".join(part for part in (first_name, last_name) if part).strip()
    if username:
        base = f"{base} (@{username})".strip() if base else f"@{username}"
    if not base:
        base = f"User {getattr(user, 'id', 'unknown')}"
    return base[:120]


def is_image_document(message) -> bool:
    document = getattr(message, "document", None)
    if not document:
        return False

    mime_type = str(getattr(document, "mime_type", "") or "").lower()
    file_name = str(getattr(document, "file_name", "") or "").lower()
    return mime_type.startswith("image/") or file_name.endswith(tuple(SUPPORTED_EXTENSIONS))


def should_relay_group_message(message) -> bool:
    text = str(getattr(message, "text", "") or "").strip()
    return bool(text and looks_like_game_message(text))


def build_relay_header(message) -> str:
    user = getattr(message, "from_user", None)
    user_label = build_user_label(user)
    user_id = getattr(user, "id", "unknown")
    return f"USER: {user_label}\nUSER ID: `{user_id}`"


def build_relay_user_key(source_group_id: int, user_id: int) -> str:
    return f"{source_group_id}:{user_id}"


def build_relay_item_text(message) -> str:
    text = str(getattr(message, "text", "") or "").strip()
    normalized_text = " | ".join(line.strip() for line in text.splitlines() if line.strip())
    return normalized_text


def get_relay_item_kind(message) -> str:
    del message
    return "game"


def build_relay_summary_text(user_label: str, user_id: int, entries: list[str]) -> str:
    del user_id
    header_lines = [
        f"{user_label}",
        f"Games: {len(entries)}",
        "",
    ]
    body_lines = [f"{index}. {entry}" for index, entry in enumerate(entries, start=1)]
    max_length = 3800

    visible_lines: list[str] = []
    total_hidden = 0
    for reverse_index, line in enumerate(reversed(body_lines), start=1):
        candidate_lines = list(reversed(visible_lines + [line]))
        hidden_count = max(len(body_lines) - len(candidate_lines), 0)
        prefix_lines = header_lines.copy()
        if hidden_count:
            prefix_lines.append(f"... older {hidden_count} items hidden ...")
            prefix_lines.append("")
        candidate_text = "\n".join(prefix_lines) + ("\n\n".join(candidate_lines) if candidate_lines else "")
        if len(candidate_text) > max_length:
            total_hidden = hidden_count + 1
            break
        visible_lines.append(line)
        total_hidden = hidden_count

    final_body = list(reversed(visible_lines))
    final_lines = header_lines.copy()
    if total_hidden:
        final_lines.append(f"... older {total_hidden} items hidden ...")
        final_lines.append("")
    return "\n".join(final_lines) + ("\n\n".join(final_body) if final_body else "")


async def ensure_owner_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    owner_user_id = get_owner_user_id()
    if owner_user_id is None:
        return True

    message = get_update_message(update)
    user_id = parse_chat_id(getattr(getattr(message, "from_user", None), "id", None))
    if user_id == owner_user_id:
        return True

    await reply_text(update, context, "Ye settings command sirf owner chala sakta hai.")
    return False


async def log_incoming_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = get_update_message(update)
    if not message:
        logger.info("Incoming update without message payload: %s", type(update).__name__)
        return

    chat_id = getattr(message, "chat_id", None)
    chat_type = getattr(getattr(message, "chat", None), "type", None)
    text = str(getattr(message, "text", "") or "").strip()
    has_photo = bool(getattr(message, "photo", None))
    has_video = bool(getattr(message, "video", None))
    has_document = bool(getattr(message, "document", None))

    logger.info(
        "Incoming update chat_id=%s chat_type=%s text=%r photo=%s video=%s document=%s business=%s",
        chat_id,
        chat_type,
        text[:200],
        has_photo,
        has_video,
        has_document,
        bool(getattr(message, "business_connection_id", None)),
    )


async def log_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error while processing update=%r", update, exc_info=context.error)


async def reply_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    **kwargs,
) -> None:
    message = get_update_message(update)
    await send_with_retry(
        context.bot.send_message,
        chat_id=message.chat_id,
        text=text,
        **get_business_kwargs(update),
        **kwargs,
    )


async def reply_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, photo) -> None:
    message = get_update_message(update)
    await send_with_retry(
        context.bot.send_photo,
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
        "QR image ke liye `qr` likho. Bot `images` folder ki files ko sequence order me bhejega. Chart image ke liye `chart` likho.\n\nUser-wise relay ke liye source group me `/setsourcegroup` aur receiving chat/group me `/setrelaychat` likho.\n\nSari commands aur unka kaam dekhne ke liye `/codecommand` likho.",
        parse_mode="Markdown",
    )


async def show_code_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    help_text = (
        "Bot Ki Sari Commands Aur Unka Kaam\n\n"
        "`/codecommand`\n"
        "Is command ko likhne par bot aapko sari commands aur unka kaam dikha dega.\n\n"
        "`/start`\n"
        "Bot ka short intro milega. Agar basic shuruat dekhni ho to ye command likho.\n\n"
        "`/qr`\n"
        "Bot next QR image bhejega. Har baar sequence me agli image aayegi.\n\n"
        "`qr`\n"
        "Agar aap message me sirf qr likhoge to bhi bot QR image bhej dega.\n\n"
        "`/chart`\n"
        "Chart image bhejne ke liye ye command use hoti hai.\n\n"
        "`chart` / `time` / `timing`\n"
        "Ye words likhne par bot chart image bhej dega.\n\n"
        "`/total`\n"
        "Agar aap kisi game message par reply karke ye command likhoge to us game ka total niklega. Reply na ho to latest saved game ka total niklega.\n\n"
        "`total`\n"
        "Ye bhi `/total` jaisa hi kaam karega aur latest saved game ka total nikalega.\n\n"
        "`ds ok`\n"
        "Ye purana system hai. Isse recent saved game uthkar `ds ok` wale target group me bot ke naam se chali jayegi.\n\n"
        f"`{GAME_OK_TRIGGER_TEXT}`\n"
        "Ye alag system hai. Is exact text ko bhejne par recent saved game `game ok` wale alag target group me bot ke naam se chali jayegi.\n\n"
        "Group Aur Setting Commands\n\n"
        "`/groupid`\n"
        "Jis group ya chat me ye command likhoge uska Telegram ID mil jayega. Group set karne me ye kaam aata hai.\n\n"
        "`/targetgroup`\n"
        "Isse pata chalega ki abhi `ds ok` likhne par game kis group me jayegi.\n\n"
        "`/settargetgroup`\n"
        "Ye `ds ok` ke liye target group set karta hai. Jis group ke andar ye command chalaoge, `ds ok` wali game usi group me jayegi. Agar ID ke saath chalaoge to us ID wala group set ho jayega.\n\n"
        "`/cleartargetgroup`\n"
        "Ye saved `ds ok` target group hata deta hai. Iske baad `ds ok` tab tak kaam nahi karega jab tak dobara group set na karo.\n\n"
        "`/gametargetgroup`\n"
        f"Isse pata chalega ki abhi `{GAME_OK_TRIGGER_TEXT}` bhejne par game kis group me jayegi.\n\n"
        "`/setgametargetgroup`\n"
        f"Ye `{GAME_OK_TRIGGER_TEXT}` ke liye alag target group set karta hai. Jis group ke andar ye command chalaoge, us trigger wali game usi group me jayegi. Agar ID ke saath chalaoge to us ID wala group set ho jayega.\n\n"
        "`/cleargametargetgroup`\n"
        f"Ye saved `{GAME_OK_TRIGGER_TEXT}` target group hata deta hai. Iske baad ye trigger tab tak kaam nahi karega jab tak dobara group set na karo.\n\n"
        "`/sourcegroup`\n"
        "Isse pata chalega ki relay system ke liye kaunsa source group set hai.\n\n"
        "`/setsourcegroup`\n"
        "Ye source group set karta hai. Jis group se games uthani hain relay ke liye, us group ko is command se set karte hain.\n\n"
        "`/relaychat`\n"
        "Isse pata chalega ki relay kahan aa rahi hai, yani receiving private chat ya group kaun sa set hai.\n\n"
        "`/setrelaychat`\n"
        "Ye receiving chat set karta hai. Source group se uthne wali relay isi chat ya group me aayegi.\n\n"
        "`/adminforum`\n"
        "Ye `/relaychat` jaisa hi command hai. Sirf compatibility ke liye rakha gaya hai.\n\n"
        "`/setadminforum`\n"
        "Ye `/setrelaychat` jaisa hi command hai. Sirf compatibility ke liye rakha gaya hai.\n\n"
        "Jaruri Notes\n\n"
        f"- `ds ok` aur `{GAME_OK_TRIGGER_TEXT}` dono alag-alag groups me bheje ja sakte hain.\n"
        "- `ds ok` apne target group ko use karta hai.\n"
        f"- `{GAME_OK_TRIGGER_TEXT}` apne alag target group ko use karta hai.\n"
        f"- Sirf exact `{GAME_OK_TRIGGER_TEXT}` text par hi ye trigger chalega.\n"
        "- Bot subah `4:00 AM` se `5:20 AM` tak reply nahi karta."
    )

    await reply_text(update, context, help_text, parse_mode="Markdown")


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

    message = get_update_message(update)
    current_chat_id = parse_chat_id(getattr(message, "chat_id", None))
    target_group_id = get_target_group_id()
    if target_group_id is None:
        await reply_text(
            update,
            context,
            "Abhi `ds ok` target group set nahi hai. `/settargetgroup -1004304577201` ya target group ke andar `/settargetgroup` likho.",
            parse_mode="Markdown",
        )
        return

    group_status_line = ""
    if current_chat_id == target_group_id:
        group_status_line = "\nYe current group/chat abhi `ds ok` ke liye set hai."

    await reply_text(
        update,
        context,
        f"`ds ok` target group ID: `{target_group_id}`\nIs group me `ds ok` likhne par game isi target group me jayegi.{group_status_line}",
        parse_mode="Markdown",
    )


async def show_game_target_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    message = get_update_message(update)
    current_chat_id = parse_chat_id(getattr(message, "chat_id", None))
    game_target_group_id = get_game_target_group_id()
    if game_target_group_id is None:
        await reply_text(
            update,
            context,
            f"Abhi `{GAME_OK_TRIGGER_TEXT}` target group set nahi hai. `/setgametargetgroup -1004304577201` ya target group ke andar `/setgametargetgroup` likho.",
            parse_mode="Markdown",
        )
        return

    group_status_line = ""
    if current_chat_id == game_target_group_id:
        group_status_line = f"\nYe current group/chat abhi `{GAME_OK_TRIGGER_TEXT}` ke liye set hai."

    await reply_text(
        update,
        context,
        f"`{GAME_OK_TRIGGER_TEXT}` target group ID: `{game_target_group_id}`\nIs group me `{GAME_OK_TRIGGER_TEXT}` wali game bheji jayegi.{group_status_line}",
        parse_mode="Markdown",
    )


async def show_source_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    source_group_id = get_source_group_id()
    if source_group_id is None:
        await reply_text(
            update,
            context,
            "Abhi source group set nahi hai. `/setsourcegroup -1004304577201` ya source group ke andar `/setsourcegroup` likho.",
            parse_mode="Markdown",
        )
        return

    await reply_text(
        update,
        context,
        f"Current source group ID: `{source_group_id}`",
        parse_mode="Markdown",
    )


async def show_relay_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    relay_chat_id = get_relay_chat_id()
    if relay_chat_id is None:
        await reply_text(
            update,
            context,
            "Abhi relay chat set nahi hai. Receiving private chat/group ke andar `/setrelaychat` likho.",
            parse_mode="Markdown",
        )
        return

    await reply_text(
        update,
        context,
        f"Current relay chat ID: `{relay_chat_id}`",
        parse_mode="Markdown",
    )


async def set_target_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    if not await ensure_owner_access(update, context):
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
            "`ds ok` target group set karne ke liye `/settargetgroup -1004304577201` likho ya jis group ko target banana ho uske andar `/settargetgroup` likho.",
            parse_mode="Markdown",
        )
        return

    settings = load_settings()
    settings["target_group_id"] = target_group_id
    save_settings(settings)

    await reply_text(
        update,
        context,
        f"`ds ok` target group set ho gaya: `{target_group_id}`",
        parse_mode="Markdown",
    )


async def set_game_target_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    if not await ensure_owner_access(update, context):
        return

    message = get_update_message(update)
    args = list(getattr(context, "args", []) or [])

    game_target_group_id: int | None = None
    if args:
        game_target_group_id = parse_chat_id(args[0])
    else:
        chat = getattr(message, "chat", None)
        chat_type = str(getattr(chat, "type", "") or "").lower()
        if chat_type in {"group", "supergroup", "channel"}:
            game_target_group_id = parse_chat_id(getattr(chat, "id", None))

    if game_target_group_id is None:
        await reply_text(
            update,
            context,
            f"`{GAME_OK_TRIGGER_TEXT}` target group set karne ke liye `/setgametargetgroup -1004304577201` likho ya jis group ko target banana ho uske andar `/setgametargetgroup` likho.",
            parse_mode="Markdown",
        )
        return

    settings = load_settings()
    settings["game_target_group_id"] = game_target_group_id
    save_settings(settings)

    await reply_text(
        update,
        context,
        f"`{GAME_OK_TRIGGER_TEXT}` target group set ho gaya: `{game_target_group_id}`",
        parse_mode="Markdown",
    )


async def set_source_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    if not await ensure_owner_access(update, context):
        return

    message = get_update_message(update)
    args = list(getattr(context, "args", []) or [])

    source_group_id: int | None = None
    if args:
        source_group_id = parse_chat_id(args[0])
    else:
        chat = getattr(message, "chat", None)
        chat_type = str(getattr(chat, "type", "") or "").lower()
        if chat_type in {"group", "supergroup"}:
            source_group_id = parse_chat_id(getattr(chat, "id", None))

    if source_group_id is None:
        await reply_text(
            update,
            context,
            "Source group set karne ke liye `/setsourcegroup -1004304577201` likho ya source group ke andar `/setsourcegroup` likho.",
            parse_mode="Markdown",
        )
        return

    settings = load_settings()
    settings["source_group_id"] = source_group_id
    save_settings(settings)

    await reply_text(
        update,
        context,
        f"Source group set ho gaya: `{source_group_id}`",
        parse_mode="Markdown",
    )


async def set_relay_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    if not await ensure_owner_access(update, context):
        return

    message = get_update_message(update)
    chat = getattr(message, "chat", None)
    relay_chat_id = parse_chat_id(getattr(chat, "id", None))

    if relay_chat_id is None:
        await reply_text(
            update,
            context,
            "Receiving private chat ya group ke andar ye command chalao.",
        )
        return

    settings = load_settings()
    settings["relay_chat_id"] = relay_chat_id
    save_settings(settings)

    await reply_text(
        update,
        context,
        f"Relay chat set ho gaya: `{relay_chat_id}`",
        parse_mode="Markdown",
    )


async def clear_target_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    if not await ensure_owner_access(update, context):
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
            f"Saved `ds ok` target group clear ho gaya. Env fallback abhi bhi `{env_target_group_id}` hai.",
            parse_mode="Markdown",
        )
        return

    await reply_text(update, context, "`ds ok` target group clear ho gaya.", parse_mode="Markdown")


async def clear_game_target_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    if not await ensure_owner_access(update, context):
        return

    settings = load_settings()
    if "game_target_group_id" in settings:
        del settings["game_target_group_id"]
        save_settings(settings)

    env_game_target_group_id = parse_chat_id(os.getenv("GAME_TARGET_GROUP_ID"))
    if env_game_target_group_id is not None:
        await reply_text(
            update,
            context,
            f"Saved `{GAME_OK_TRIGGER_TEXT}` target group clear ho gaya. Env fallback abhi bhi `{env_game_target_group_id}` hai.",
            parse_mode="Markdown",
        )
        return

    await reply_text(update, context, f"`{GAME_OK_TRIGGER_TEXT}` target group clear ho gaya.", parse_mode="Markdown")


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
        recent_messages = get_recent_game_messages(memory, message.chat_id, limit=1)
        source_text = recent_messages[-1].strip() if recent_messages else ""

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


def collect_game_source_messages(message) -> tuple[list[str], bool]:
    reply_to_message = getattr(message, "reply_to_message", None)
    if reply_to_message and getattr(reply_to_message, "text", None):
        source_text = str(reply_to_message.text or "").strip()
        return ([source_text] if source_text else []), True

    memory = load_chat_memory()
    return get_recent_game_messages(memory, message.chat_id), False


async def send_game_ok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    message = get_update_message(update)
    if GAME_OK_TRIGGER_TEXT not in str(getattr(message, "text", "") or ""):
        return

    target_group_id = get_game_target_group_id()
    if target_group_id is None:
        await reply_text(
            update,
            context,
            f"`{GAME_OK_TRIGGER_TEXT}` target group set nahi hai. Pehle `/setgametargetgroup -1004304577201` ya target group ke andar `/setgametargetgroup` likho.",
            parse_mode="Markdown",
        )
        return

    source_messages, used_reply_message = collect_game_source_messages(message)
    source_messages = [text for text in source_messages if text.strip()]

    if not source_messages:
        await reply_text(
            update,
            context,
            f"Koi recent game message nahi mila. Pehle number wale game message bhejo ya unme se kisi message par reply karke `{GAME_OK_TRIGGER_TEXT}` likho.",
            parse_mode="Markdown",
        )
        return

    invalid_messages = [text for text in source_messages if not looks_like_game_message(text)]
    if invalid_messages:
        await reply_text(
            update,
            context,
            f"Recent saved message game format me nahi mila. Number wala game message bhejo ya game message par reply karke `{GAME_OK_TRIGGER_TEXT}` likho.",
            parse_mode="Markdown",
        )
        return

    await reply_text(update, context, "GAME OK ✔")
    for source_text in source_messages:
        await send_with_retry(context.bot.send_message, chat_id=target_group_id, text=source_text)

    if not used_reply_message:
        memory = load_chat_memory()
        chat_key = str(message.chat_id)
        if chat_key in memory:
            del memory[chat_key]
            save_chat_memory(memory)


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
    source_messages, used_reply_message = collect_game_source_messages(message)
    source_messages = [text for text in source_messages if text.strip()]

    if not source_messages:
        await reply_text(
            update,
            context,
            "Koi recent game message nahi mila. Pehle number wale game message bhejo ya unme se kisi message par reply karke `ds ok` likho.",
            parse_mode="Markdown",
        )
        return

    invalid_messages = [text for text in source_messages if not looks_like_game_message(text)]
    if invalid_messages:
        await reply_text(
            update,
            context,
            "Recent saved message game format me nahi mila. Number wala game message bhejo ya game message par reply karke `ds ok` likho.",
            parse_mode="Markdown",
        )
        return

    await reply_text(update, context, "DISAWAR GAME OK ✔")
    for source_text in source_messages:
        await send_with_retry(context.bot.send_message, chat_id=target_group_id, text=source_text)

    if not used_reply_message:
        memory = load_chat_memory()
        chat_key = str(message.chat_id)
        if chat_key in memory:
            del memory[chat_key]
            save_chat_memory(memory)


async def relay_source_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_quiet_hours():
        return

    source_group_id = get_source_group_id()
    relay_chat_id = get_relay_chat_id()
    if source_group_id is None or relay_chat_id is None:
        return

    message = get_update_message(update)
    if not message:
        return

    chat_id = parse_chat_id(getattr(message, "chat_id", None))
    if chat_id != source_group_id:
        return

    if not should_relay_group_message(message):
        return

    if getattr(message, "from_user", None) and getattr(message.from_user, "is_bot", False):
        return

    try:
        user = getattr(message, "from_user", None)
        user_id = parse_chat_id(getattr(user, "id", None))
        if user_id is None:
            return

        relay_state = load_relay_state()
        relay_key = build_relay_user_key(source_group_id, user_id)
        relay_entry = relay_state.get(
            relay_key,
            {
                "message_id": 0,
                "user_label": build_user_label(user),
                "user_id": user_id,
                "entries": [],
            },
        )

        relay_entry["user_label"] = build_user_label(user)
        relay_entry["user_id"] = user_id
        existing_entries = relay_entry.get("entries", [])
        if not isinstance(existing_entries, list):
            existing_entries = []
        item_text = build_relay_item_text(message)
        existing_entries.append(item_text)
        relay_entry["entries"] = [str(item).strip() for item in existing_entries if str(item).strip()][-200:]

        summary_text = build_relay_summary_text(
            str(relay_entry["user_label"]),
            int(relay_entry["user_id"]),
            list(relay_entry["entries"]),
        )

        message_id = parse_chat_id(relay_entry.get("message_id"))
        if message_id:
            try:
                await send_with_retry(
                    context.bot.edit_message_text,
                    chat_id=relay_chat_id,
                    message_id=message_id,
                    text=summary_text,
                    parse_mode="Markdown",
                )
            except Exception:
                sent_message = await send_with_retry(
                    context.bot.send_message,
                    chat_id=relay_chat_id,
                    text=summary_text,
                    parse_mode="Markdown",
                )
                relay_entry["message_id"] = sent_message.message_id
        else:
            sent_message = await send_with_retry(
                context.bot.send_message,
                chat_id=relay_chat_id,
                text=summary_text,
                parse_mode="Markdown",
            )
            relay_entry["message_id"] = sent_message.message_id

        relay_state[relay_key] = relay_entry
        save_relay_state(relay_state)
    except Exception:
        logger.exception(
            "Could not relay source group message chat_id=%s message_id=%s to relay_chat_id=%s",
            chat_id,
            getattr(message, "message_id", None),
            relay_chat_id,
        )


async def remember_recent_game_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = get_update_message(update)
    text = str(getattr(message, "text", "") or "").strip()
    if not text:
        return

    memory = load_chat_memory()
    chat_key = str(message.chat_id)

    if re.fullmatch(r"(?i)\s*(/total|total|ds\s+ok)\s*", text) or GAME_OK_TRIGGER_TEXT in text:
        return

    if not looks_like_game_message(text):
        return

    existing_messages = get_recent_game_messages(memory, message.chat_id, limit=9)
    existing_messages.append(text)
    memory[chat_key] = existing_messages[-10:]
    save_chat_memory(memory)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Please set TELEGRAM_BOT_TOKEN environment variable.")

    application = (
        Application.builder()
        .token(token)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .post_init(on_application_start)
        .post_shutdown(on_application_shutdown)
        .build()
    )

    application.add_error_handler(log_error)

    application.add_handler(TypeHandler(Update, log_incoming_update), group=-1)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("codecommand", show_code_commands))
    application.add_handler(CommandHandler("groupid", send_group_id))
    application.add_handler(CommandHandler("targetgroup", show_target_group))
    application.add_handler(CommandHandler("gametargetgroup", show_game_target_group))
    application.add_handler(CommandHandler("settargetgroup", set_target_group))
    application.add_handler(CommandHandler("setgametargetgroup", set_game_target_group))
    application.add_handler(CommandHandler("cleartargetgroup", clear_target_group))
    application.add_handler(CommandHandler("cleargametargetgroup", clear_game_target_group))
    application.add_handler(CommandHandler("sourcegroup", show_source_group))
    application.add_handler(CommandHandler("setsourcegroup", set_source_group))
    application.add_handler(CommandHandler("relaychat", show_relay_chat))
    application.add_handler(CommandHandler("adminforum", show_relay_chat))
    application.add_handler(CommandHandler("setrelaychat", set_relay_chat))
    application.add_handler(CommandHandler("setadminforum", set_relay_chat))
    application.add_handler(CommandHandler("chart", send_chart_image))
    application.add_handler(CommandHandler("qr", send_next_qr))
    application.add_handler(CommandHandler("total", send_game_total))
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i)(?:\bchart\b|\btime\b|\btiming\b|\u091a\u093e\u0930\u094d\u091f|\u091f\u093e\u0907\u092e|\u091f\u093e\u0907\u092e\u093f\u0902\u0917)"
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
            filters.TEXT & filters.Regex(r"(?i)^\s*/?codecommand\s*$"),
            show_code_commands,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(re.escape(GAME_OK_TRIGGER_TEXT)),
            send_game_ok,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"(?i)^\s*ds\s+ok\s*$"),
            send_ds_ok,
        )
    )
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, relay_source_group_message),
        group=1,
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, remember_recent_game_message),
        group=2,
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
