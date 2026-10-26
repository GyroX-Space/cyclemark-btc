"""Send a daily cycle-status message to Telegram after the daily refresh.

Reads the latest published signal record, formats a fixed English message, and
posts it via the Telegram Bot API. Credentials come from environment variables
and are never stored in the repository:

  CYCLEMARK_TELEGRAM_BOT_TOKEN  bot token from @BotFather
  CYCLEMARK_TELEGRAM_CHAT_IDS   comma/space-separated target chats (personal
                                ids or group ids; any group that adds the bot
                                as an admin with post permission can receive)

If either variable is missing the script logs a skip notice and exits 0, so
local runs and servers without Telegram configured are unaffected. Delivery is
attempted per chat: per-chat failures are logged on stderr, and the script
exits 1 only if every chat failed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LATEST_SIGNAL = ROOT / "data" / "signals" / "latest.json"

TAGLINE = "BTC Cycle Intelligence — Know the cycle. Track every signal. Verify the history."
SITE_URL = "https://cyclemarket.predi.org/"

# Display-only banding of the provisional BFS score (0-100). Higher BFS means
# deeper drawdown from the all-time high, i.e. deeper into bottom territory.
# These labels are presentation wording, not validated trading signals.
def bottom_indicator_label(bfs: float) -> str:
    if bfs >= 80:
        return "YES — Deep Value Zone"
    if bfs >= 60:
        return "APPROACHING — Value Zone"
    if bfs >= 40:
        return "NO — Neutral Zone"
    if bfs >= 20:
        return "NO — Elevated Zone"
    return "NO — Euphoria Zone"


def build_message(record: dict) -> str:
    bfs = float(record["bfs"])
    coverage = record["score_coverage"]["configured_weight_coverage_pct"]
    price = record["market_data"]["price"]["price_usd"]
    date = record["date"]
    label = bottom_indicator_label(bfs)
    return (
        f"Cycle Bottom Indicator: {label}\n"
        f"(BFS {bfs:.2f}/100, provisional, {coverage}% configured-weight coverage)\n"
        f"BTC: ${price:,.2f} | {date} UTC\n"
        f"\n"
        f"{TAGLINE}\n"
        f"{SITE_URL}"
    )


def send_message(token: str, chat_id: str, text: str, *, timeout: float = 15.0) -> dict:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_chat_ids(raw: str) -> list[str]:
    """Split a comma/space-separated chat id list, dropping empty entries."""
    return [c for c in raw.replace(",", " ").split() if c]


def main() -> int:
    token = os.environ.get("CYCLEMARK_TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = parse_chat_ids(os.environ.get("CYCLEMARK_TELEGRAM_CHAT_IDS", ""))
    if not token or not chat_ids:
        print("Telegram credentials not set; skipping notification.", file=sys.stderr)
        return 0

    record = json.loads(LATEST_SIGNAL.read_text(encoding="utf-8"))
    message = build_message(record)
    print(message)

    delivered = 0
    for chat_id in chat_ids:
        try:
            result = send_message(token, chat_id, message)
        except (HTTPError, URLError, OSError) as exc:
            print(f"Telegram send to {chat_id} failed: {exc}", file=sys.stderr)
            continue
        if not result.get("ok"):
            print(f"Telegram API rejected chat {chat_id}: {result}", file=sys.stderr)
            continue
        print(f"Telegram message delivered to chat {chat_id}.")
        delivered += 1

    if delivered == 0:
        print(f"Telegram notification failed for all {len(chat_ids)} chat(s).", file=sys.stderr)
        return 1
    if delivered < len(chat_ids):
        print(f"Delivered to {delivered}/{len(chat_ids)} chats; see stderr for failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
