# Telegram Movie Post Bot

This repository's active entry point is `bot.py`. It is a simple Telethon bot for posting a movie **photo + video** to a channel selected with buttons.

## Current features

- Burmese Telegram buttons.
- Any Telegram user can use the safe movie-post flow.
- Only the three configured admins can add/remove target channels and view status.
- Admin adds target channels once; users choose a target channel with a button.
- User sends a movie photo, then the video file. A photo-only post is also supported with `/skipvideo`.
- Gemini Vision reads the poster and generates movie title, year, genre, a Burmese synopsis, and exactly five hashtags.
- A video URL in the photo caption is preserved; `FIXED_VIDEO_LINK` is always added as the second link.
- The bot sends the photo with the generated caption and the video to the selected target channel.
- No Channel A/B/C code, round-robin forwarding, source monitoring, or forwarding-mode buttons are used by the active bot.

## Admins

| Username | Telegram ID |
|---|---:|
| `@waiyanphyo99` | `6081621017` |
| `@waiyan7861` | `6940887457` |
| `@Bingopop1991` | `6432487408` |

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
nano .env
```

Required environment variables:

```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.0-flash
SESSION_NAME=auto_post_bot_session
DATA_FILE=bot_data.json
AI_TIMEOUT=45
FIXED_VIDEO_LINK=https://t.me/addlist/YuaibAle-uEwMWQ9
```

`API_ID` and `API_HASH` must come from the same app at [my.telegram.org](https://my.telegram.org). `BOT_TOKEN` comes from `@BotFather`. Keep all secrets private.

## Telegram workflow

1. Admin sends `/start`.
2. Admin taps `⚙️ Channel စီမံရန်` → `➕ Channel ထည့်ရန်` and sends a channel username such as `@mychannel`.
3. Add the bot to that channel as an administrator with permission to post media.
4. Any user sends `/start` and taps `🎬 Movie Post`.
5. The user selects a target channel.
6. The user sends the movie poster photo. Put one video URL in the photo caption if needed.
7. The user sends the video file. The bot calls Gemini Vision, builds the Burmese caption, adds exactly five hashtags and the fixed second link, then posts to the chosen channel.
8. For a photo-only post, send `/skipvideo` after the photo.

The result is formatted like:

```text
🎬 Title: The House of Magic [2013]

💬 မြန်မာလို ဇာတ်ညွှန်းအသစ်...

🗓 Year: 2013
🎭 Genre: Animation
📺 Channel: @mychannel

#TheHouseOfMagic #Animation #MyanmarMovie #Movie #Telegram

👇 Video Link
🔗 https://your-video-link.example
🔗 https://t.me/addlist/YuaibAle-uEwMWQ9
```

## Run

```bash
python3 bot.py
```

Only run one copy of the bot for a given `SESSION_NAME`. Running multiple copies causes Telethon errors such as `wrong session ID` or `database is locked`. On Termux, stop an old process before starting a new one:

```bash
pkill -f 'python.*bot.py' || true
cd ~/projects/telegram-auto-post-bot
. .venv/bin/activate
python3 bot.py
```

For phone-off operation, run the same project on a persistent VPS or cloud worker instead of Termux.

## Permissions and limitations

The bot can post only to channels where it has legitimate permission. It cannot access private channels merely from a link, bypass Telegram permissions, or remove other people's watermarks. The repository does not contain real API keys or session files.
