"""Simple Telegram movie publisher: photo + video -> Gemini caption -> selected channel."""
import asyncio
import base64
import json
import mimetypes
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv
from telethon import Button, TelegramClient, events

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
SESSION_NAME = os.getenv("SESSION_NAME", "auto_post_bot_session").strip()
DATA_FILE = os.getenv("DATA_FILE", "bot_data.json").strip()
AI_TIMEOUT = max(10, int(os.getenv("AI_TIMEOUT", "45")))
FIXED_VIDEO_LINK = os.getenv("FIXED_VIDEO_LINK", "https://t.me/addlist/YuaibAle-uEwMWQ9").strip()

ADMIN_IDS = {6081621017, 6940887457, 6432487408}
ADMIN_USERNAMES = {"waiyanphyo99", "waiyan7861", "bingopop1991"}
MEDIA_DIR = Path("movie_media")
MEDIA_DIR.mkdir(exist_ok=True)

VISION_PROMPT = """
You are a Burmese movie social-media caption writer. Analyze the attached movie poster.
Return valid JSON only with these keys: movie_name, year, genre, caption, hashtags.
movie_name: readable movie title.
year: only if clearly visible or reliable; otherwise empty string.
genre: short genre, preferably English or Burmese; otherwise empty string.
caption: a short attractive Burmese synopsis based only on the image and supplied text.
Do not invent actors, ratings, awards, links, or unsupported facts.
hashtags: exactly five short hashtags, no spaces inside a hashtag.
""".strip()


def default_data():
    return {"targets": [], "selected_targets": {}, "pending": {}}


def load_data():
    path = Path(DATA_FILE)
    if not path.exists():
        return default_data()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_data()
    result = default_data()
    result["targets"] = list(dict.fromkeys(data.get("targets", [])))
    # Migrate the previous direct target once, but never expose A/B/C.
    old_target = data.get("channels", {}).get("direct_target", "")
    if old_target and old_target not in result["targets"]:
        result["targets"].append(old_target)
    result["selected_targets"].update(data.get("selected_targets", {}))
    result["pending"].update(data.get("pending", {}))
    return result


def save_data(data):
    temp = f"{DATA_FILE}.tmp"
    Path(temp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, DATA_FILE)


def is_admin(event):
    sender_id = getattr(event, "sender_id", None)
    if sender_id is not None and int(sender_id) in ADMIN_IDS:
        return True
    sender = getattr(event, "sender", None)
    username = getattr(sender, "username", "") or ""
    return username.lower() in ADMIN_USERNAMES


def normalise_channel(value):
    value = value.strip()
    match = re.search(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)", value)
    if match:
        value = "@" + match.group(1)
    if not value.startswith("@"):
        value = "@" + value
    return value


def fixed_links(text):
    found = re.findall(r"https?://\S+", text or "")
    links = []
    for link in found:
        link = link.rstrip(".,)]}>")
        if link and link != FIXED_VIDEO_LINK and link not in links:
            links.append(link)
            break
    if FIXED_VIDEO_LINK and FIXED_VIDEO_LINK not in links:
        links.append(FIXED_VIDEO_LINK)
    return links[:2]


def hashtag(value):
    value = re.sub(r"[^\w\u1000-\u109F]+", "", str(value or ""), flags=re.UNICODE)
    return f"#{value}" if value else ""


def make_caption(result, links, target):
    title = result.get("movie_name") or "Movie"
    year = str(result.get("year") or "").strip()
    genre = str(result.get("genre") or "").strip()
    synopsis = result.get("caption") or "ဒီ Movie ကို ကြည့်ရှုနိုင်ပါသည်။"
    tags = []
    for item in result.get("hashtags") or []:
        token = hashtag(item)
        if token and token.lower() not in {x.lower() for x in tags}:
            tags.append(token)
    for item in [title, genre, "MyanmarMovie", "Movie", "Telegram"]:
        token = hashtag(item)
        if token and token.lower() not in {x.lower() for x in tags}:
            tags.append(token)
        if len(tags) == 5:
            break
    lines = [f"🎬 Title: {title}{f' [{year}]' if year else ''}", "", f"💬 {synopsis}", ""]
    if year:
        lines.append(f"🗓 Year: {year}")
    if genre:
        lines.append(f"🎭 Genre: {genre}")
    lines += [f"📺 Channel: {target}", "", " ".join(tags[:5]), "", "👇 Video Link"]
    lines += [f"🔗 {link}" for link in links]
    return "\n".join(lines)


def gemini_caption(image_bytes, mime_type, extra_text, links, target):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY မရှိပါ")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [
            {"text": VISION_PROMPT + "\nSupplied text and links:\n" + (extra_text or "(none)")},
            {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}},
        ]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 700, "responseMimeType": "application/json"},
    }
    response = requests.post(url, json=payload, timeout=AI_TIMEOUT)
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.IGNORECASE).strip()
    return make_caption(json.loads(text), links, target)


def target_buttons(targets, prefix=b"choose:"):
    buttons = []
    for index, target in enumerate(targets):
        buttons.append([Button.inline(f"📺 {target}", prefix + str(index).encode())])
    return buttons


def user_keyboard():
    return [[Button.text("🎬 Movie Post")], [Button.text("📺 Channel ရွေးရန်"), Button.text("❓ Help")]]


def admin_keyboard():
    return user_keyboard() + [[Button.text("⚙️ Channel စီမံရန်"), Button.text("📊 Status")]]


def main_keyboard(event):
    return admin_keyboard() if is_admin(event) else user_keyboard()


def cleanup_pending(item):
    for key in ("photo_path", "video_path"):
        path = item.get(key)
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass


client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


@client.on(events.NewMessage(pattern=r"^/start$"))
async def start(event):
    await event.respond(
        "🤖 <b>Movie Post Bot</b>\n\n"
        "ပုံ + video ပို့ပြီး Gemini AI ဇာတ်ညွှန်းအသစ်၊ hashtag ၅ ခုနဲ့ channel တင်နိုင်ပါတယ်။\n\n"
        "🎬 Movie Post ကိုနှိပ်ပါ။",
        parse_mode="HTML", buttons=main_keyboard(event),
    )


@client.on(events.NewMessage(pattern=r"^🎬 Movie Post$"))
async def start_movie(event):
    data = load_data()
    if not data["targets"]:
        await event.respond("⚠️ Admin က အရင် Channel စီမံရန် ထဲမှာ target channel ထည့်ပေးရပါမယ်။", buttons=main_keyboard(event))
        return
    await event.respond("📺 တင်မည့် channel ကိုရွေးပါ။", buttons=target_buttons(data["targets"]))


@client.on(events.NewMessage(pattern=r"^📺 Channel ရွေးရန်$"))
async def show_channels(event):
    data = load_data()
    if not data["targets"]:
        await event.respond("⚠️ Target channel မရှိသေးပါ။ Admin ကို channel ထည့်ခိုင်းပါ။", buttons=main_keyboard(event))
        return
    await event.respond("📺 Channel ရွေးပါ။", buttons=target_buttons(data["targets"]))


@client.on(events.NewMessage(pattern=r"^⚙️ Channel စီမံရန်$"))
async def manage_channels(event):
    if not is_admin(event):
        await event.respond("⛔ Admin များသာ channel ထည့်နိုင်ပါတယ်။")
        return
    data = load_data()
    current = ", ".join(data["targets"]) or "မရှိသေးပါ"
    await event.respond(f"📺 <b>Target Channels</b>\n\n{current}\n\nChannel အသစ်ထည့်ရန် ခလုပ်နှိပ်ပါ။", parse_mode="HTML", buttons=[
        [Button.inline("➕ Channel ထည့်ရန်", b"add_target")],
        [Button.inline("🗑️ Channel ဖျက်ရန်", b"remove_target")],
        [Button.inline("↩️ Main Menu", b"main")],
    ])


@client.on(events.NewMessage(pattern=r"^📊 Status$"))
async def status(event):
    if not is_admin(event):
        return
    data = load_data()
    await event.respond(f"✅ Bot အလုပ်လုပ်နေပါသည်\n📺 Target channel: {len(data['targets'])}\n🤖 Gemini: {'ON' if GEMINI_API_KEY else 'OFF'}", buttons=main_keyboard(event))


@client.on(events.NewMessage(pattern=r"^❓ Help$"))
async def help_message(event):
    await event.respond(
        "❓ <b>အသုံးပြုပုံ</b>\n\n"
        "1) 🎬 Movie Post နှိပ်ပါ\n"
        "2) Channel ရွေးပါ\n"
        "3) Movie ပုံပို့ပါ\n"
        "4) Video ဖိုင်ပို့ပါ\n"
        "5) Bot က Gemini AI ဖြင့် ဇာတ်ညွှန်းနဲ့ hashtag ၅ ခုထုတ်ပြီး ပုံ+video ကို channel တင်ပါမယ်။\n\n"
        "Video link ကို ပုံ caption ထဲထည့်ပါ။ Fixed link ကို bot က အမြဲထည့်ပါမယ်။",
        parse_mode="HTML", buttons=main_keyboard(event),
    )


@client.on(events.CallbackQuery)
async def callbacks(event):
    data = load_data()
    action = event.data.decode()
    if action == "main":
        await event.answer()
        await event.edit("🤖 Main Menu", buttons=main_keyboard(event))
        return
    if action == "add_target":
        if not is_admin(event):
            await event.answer("Admin only", alert=True); return
        data["pending"][str(event.chat_id)] = {"action": "add_target"}
        save_data(data)
        await event.answer()
        await event.edit("➕ Channel username သို့မဟုတ် link ပို့ပါ။\nဥပမာ: @mychannel")
        return
    if action == "remove_target":
        if not is_admin(event):
            await event.answer("Admin only", alert=True); return
        await event.answer()
        await event.edit("ဖျက်လိုသော channel ကိုရွေးပါ။", buttons=target_buttons(data["targets"], b"remove:"))
        return
    if action.startswith("remove:"):
        if not is_admin(event):
            await event.answer("Admin only", alert=True); return
        index = int(action.split(":", 1)[1])
        if 0 <= index < len(data["targets"]):
            removed = data["targets"].pop(index)
            save_data(data)
            await event.edit(f"✅ {removed} ဖျက်ပြီးပါပြီ။", buttons=main_keyboard(event))
        return
    if action.startswith("choose:"):
        index = int(action.split(":", 1)[1])
        if not 0 <= index < len(data["targets"]):
            await event.answer("Channel မတွေ့ပါ", alert=True); return
        target = data["targets"][index]
        data["selected_targets"][str(event.chat_id)] = target
        data["pending"][str(event.chat_id)] = {"action": "await_media", "target": target}
        save_data(data)
        await event.answer()
        await event.edit(f"✅ Target: {target}\n\nအခု Movie ပုံပို့ပါ။ ပုံ caption ထဲမှာ video link ထည့်ပါ။")
        return


@client.on(events.NewMessage(func=lambda e: bool(e.photo or e.video or e.document)))
async def media_received(event):
    data = load_data()
    key = str(event.chat_id)
    session = data["pending"].get(key)
    if not session or session.get("action") not in {"await_media", "await_video"}:
        return
    if session.get("action") == "await_media" and not event.photo:
        await event.respond("🖼️ အရင် Movie ပုံပို့ပါ။")
        return
    if session.get("action") == "await_video" and not (event.video or event.document):
        return
    if event.photo:
        session["photo_path"] = await event.download_media(file=str(MEDIA_DIR / f"{event.chat_id}_photo"))
        session["original_text"] = event.raw_text or ""
        session["action"] = "await_video"
        data["pending"][key] = session
        save_data(data)
        await event.respond("✅ ပုံရပါပြီ။ အခု video ဖိုင်ပို့ပါ။\nပုံမပါဘဲ link နဲ့ photo တင်ချင်ရင် /skipvideo ပို့ပါ။")
        return
    session["video_path"] = await event.download_media(file=str(MEDIA_DIR / f"{event.chat_id}_video"))
    await publish_session(event, data, key, session)


@client.on(events.NewMessage(pattern=r"^/skipvideo$"))
async def skip_video(event):
    data = load_data(); key = str(event.chat_id); session = data["pending"].get(key)
    if not session or not session.get("photo_path"):
        await event.respond("⚠️ အရင် Movie ပုံပို့ပါ။"); return
    await publish_session(event, data, key, session)


async def publish_session(event, data, key, session):
    target = session.get("target") or data["selected_targets"].get(key)
    photo_path = session.get("photo_path")
    video_path = session.get("video_path")
    if not target or not photo_path:
        await event.respond("❌ Target သို့မဟုတ် ပုံမရှိပါ။"); return
    await event.respond("🤖 Gemini AI က ပုံဖတ်ပြီး ဇာတ်ညွှန်းရေးနေပါတယ်... ခဏစောင့်ပါ။")
    try:
        image_bytes = Path(photo_path).read_bytes()
        mime = mimetypes.guess_type(photo_path)[0] or "image/jpeg"
        links = fixed_links(session.get("original_text", ""))
        caption = await asyncio.to_thread(gemini_caption, image_bytes, mime, session.get("original_text", ""), links, target)
        if video_path and Path(video_path).exists():
            try:
                await client.send_file(target, [photo_path, video_path], caption=[caption, ""], supports_streaming=True)
            except Exception:
                await client.send_file(target, photo_path, caption=caption)
                await client.send_file(target, video_path, supports_streaming=True)
        else:
            await client.send_file(target, photo_path, caption=caption)
        await event.respond(f"✅ အောင်မြင်ပါပြီ။\n📺 {target}\n# ၅ ခုနှင့် link များ ထည့်ပြီးတင်ပြီးပါပြီ။", buttons=main_keyboard(event))
    except Exception as error:
        await event.respond(f"❌ Post မတင်နိုင်ပါ: {str(error)[:400]}", buttons=main_keyboard(event))
    finally:
        cleanup_pending(session)
        data["pending"].pop(key, None)
        save_data(data)


@client.on(events.NewMessage(func=lambda e: bool(e.raw_text and not e.raw_text.startswith("/") and not e.photo and not e.video and not e.document)))
async def text_received(event):
    if not is_admin(event):
        return
    data = load_data(); key = str(event.chat_id); session = data["pending"].get(key)
    if not session:
        return
    if session.get("action") == "add_target":
        channel = normalise_channel(event.raw_text)
        if channel not in data["targets"]:
            data["targets"].append(channel)
        data["pending"].pop(key, None)
        save_data(data)
        await event.respond(f"✅ Channel ထည့်ပြီးပါပြီ: {channel}", buttons=main_keyboard(event))


async def main():
    if not BOT_TOKEN or API_ID <= 0 or not API_HASH:
        raise RuntimeError("API_ID, API_HASH, BOT_TOKEN ကို .env ထဲဖြည့်ပါ")
    if not GEMINI_API_KEY:
        print("⚠️ GEMINI_API_KEY မရှိသေးပါ - image caption AI မအလုပ်လုပ်ပါ")
    print("🤖 Simple Movie Post Bot စတင်ပါပြီ...")
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    print(f"✅ Logged in as: {me.first_name} (@{me.username})")
    print("📌 Target picker + photo/video workflow အသုံးပြုပါမည်။")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
