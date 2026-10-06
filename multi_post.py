"""multi_post.py
Multi-platform post runner.
- Reads posts from posts.json (each post can provide per-platform text/media)
- Uses environment variables for API keys (.env)
- Provides a quick CLI to send a single post now or run a simple worker that sends scheduled posts
- Telegram adapter implemented; other platform adapters are stubbed with instructions

Run examples (Termux):
- pip install -r requirements.txt (or pip install python-dotenv requests)
- cp .env.example .env and fill credentials
- python multi_post.py send-now --id 1             # send post with id 1 immediately
- python multi_post.py worker --loop-interval 30   # run worker, checks posts.json every 30s

This script is intentionally simple so you can test in Termux.
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import requests
from dotenv import load_dotenv

# Load .env from repo root
root = Path(__file__).parent
load_dotenv(root / '.env')

LOG = logging.getLogger('multi_post')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

POSTS_FILE = root / 'posts.json'
SENT_MARK_KEY = 'sent_at'

# Adapters are functions named send_<platform>(post, cfg)

# Telegram adapter (implemented)
def send_telegram(post: Dict, cfg: Dict):
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN not set in .env')
    chat_list = os.getenv('TELEGRAM_CHANNELS', '')
    # chat_list can be comma-separated channels; if CHANNEL specified in post use that
    target_chs = []
    if 'target' in post and post['target'].get('telegram'):
        target_chs = [post['target']['telegram']]
    elif chat_list:
        target_chs = [c.strip() for c in chat_list.split(',') if c.strip()]
    else:
        raise RuntimeError('No telegram channel configured. Set TELEGRAM_CHANNELS or post.target.telegram')

    text = post.get('texts', {}).get('telegram') or post.get('text')
    if not text:
        LOG.warning('No telegram text for post id %s', post.get('id'))
        return {'ok': False, 'error': 'no_text'}

    results = []
    for ch in target_chs:
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        payload = {'chat_id': ch, 'text': text, 'parse_mode': 'HTML'}
        LOG.info('Sending to telegram %s...', ch)
        resp = requests.post(url, data=payload, timeout=15)
        try:
            resp.raise_for_status()
            results.append({'channel': ch, 'status': 'ok', 'response': resp.json()})
            LOG.info('Sent to %s', ch)
        except Exception as e:
            LOG.exception('Failed to send to %s: %s', ch, e)
            results.append({'channel': ch, 'status': 'error', 'error': str(e), 'response_text': resp.text})
    return {'ok': True, 'results': results}

# X (Twitter) adapter - STUB: implement using your X app credentials
def send_x(post: Dict, cfg: Dict):
    # Example: use OAuth1.0a / Twitter API v2 with user context to create tweets
    # Fill in implementation depending on the access method you have
    LOG.info('X adapter called for post id %s - NOT IMPLEMENTED', post.get('id'))
    return {'ok': False, 'error': 'not_implemented'}

# Facebook adapter - STUB
def send_facebook(post: Dict, cfg: Dict):
    # Posting to Facebook Pages: use Graph API with PAGE_ACCESS_TOKEN and page id
    LOG.info('Facebook adapter called for post id %s - NOT IMPLEMENTED', post.get('id'))
    return {'ok': False, 'error': 'not_implemented'}

# Threads adapter - STUB
def send_threads(post: Dict, cfg: Dict):
    # As of authoring, Threads API access details vary; implement when you have an access path
    LOG.info('Threads adapter called for post id %s - NOT IMPLEMENTED', post.get('id'))
    return {'ok': False, 'error': 'not_implemented'}

ADAPTERS = {
    'telegram': send_telegram,
    'x': send_x,
    'facebook': send_facebook,
    'threads': send_threads,
}


def load_posts() -> Dict:
    if not POSTS_FILE.exists():
        LOG.info('posts.json not found, creating empty file')
        POSTS_FILE.write_text('[]')
    with open(POSTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_posts(posts):
    with open(POSTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def send_post(post):
    cfg = {}  # future: pass in config values
    results = {}
    for platform, adapter in ADAPTERS.items():
        # send if the post provides a text for that platform or if platform is telegram (global text)
        text_for = post.get('texts', {}).get(platform) or post.get('texts') is None and post.get('text')
        if text_for or platform == 'telegram' and post.get('texts', {}).get('telegram'):
            try:
                r = adapter(post, cfg)
            except Exception as e:
                r = {'ok': False, 'error': str(e)}
        else:
            r = {'ok': False, 'skipped': True}
        results[platform] = r
    return results


def find_post(posts, post_id):
    for p in posts:
        if p.get('id') == post_id:
            return p
    return None


def run_send_now(post_id: int):
    posts = load_posts()
    post = find_post(posts, post_id)
    if not post:
        LOG.error('No post with id %s', post_id)
        return
    LOG.info('Sending post id %s', post_id)
    res = send_post(post)
    LOG.info('Results: %s', res)
    post[SENT_MARK_KEY] = datetime.now(timezone.utc).isoformat()
    save_posts(posts)


def run_worker(loop_interval: int):
    LOG.info('Starting worker, checking %s every %s seconds', POSTS_FILE, loop_interval)
    while True:
        try:
            posts = load_posts()
            now = datetime.now(timezone.utc)
            changed = False
            for p in posts:
                if p.get(SENT_MARK_KEY):
                    continue
                sched = p.get('schedule')
                if not sched:
                    continue
                try:
                    sched_dt = datetime.fromisoformat(sched)
                except Exception:
                    LOG.warning('Invalid schedule format for post id %s: %s', p.get('id'), sched)
                    continue
                if sched_dt <= now:
                    LOG.info('Scheduling send for post id %s', p.get('id'))
                    res = send_post(p)
                    LOG.info('Send results: %s', res)
                    p[SENT_MARK_KEY] = datetime.now(timezone.utc).isoformat()
                    changed = True
            if changed:
                save_posts(posts)
        except Exception as e:
            LOG.exception('Worker loop error: %s', e)
        time.sleep(loop_interval)


def main():
    parser = argparse.ArgumentParser(description='Multi-platform auto post bot runner')
    sub = parser.add_subparsers(dest='cmd')

    p_send = sub.add_parser('send-now')
    p_send.add_argument('--id', '-i', type=int, required=True, help='Post id to send now')

    p_worker = sub.add_parser('worker')
    p_worker.add_argument('--loop-interval', '-l', type=int, default=30, help='Loop interval seconds')

    p_list = sub.add_parser('list')

    args = parser.parse_args()
    if args.cmd == 'send-now':
        run_send_now(args.id)
    elif args.cmd == 'worker':
        run_worker(args.loop_interval)
    elif args.cmd == 'list':
        posts = load_posts()
        print(json.dumps(posts, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
