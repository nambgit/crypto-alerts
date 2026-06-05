import os
import sys

# Tai dung cac ham da co trong price_alert.py (cung thu muc repo)
from price_alert import (
    fetch_news, send_discord, make_embed, load_json, save_json,
    parse_color, DEFAULT_SECTION_COLORS, DEFAULT_SECTION_EMOJIS,
)

CONFIG_PATH = "config.json"
NEWS_STATE_PATH = "news_state.json"
SEEN_LIMIT = 300  # nho toi da bao nhieu link da dang, tranh phinh to


def main():
    webhook = os.environ.get("DISCORD_NEWS_WEBHOOK_URL")
    if not webhook:
        print("Thieu bien moi truong DISCORD_NEWS_WEBHOOK_URL", file=sys.stderr)
        sys.exit(1)

    config = load_json(CONFIG_PATH, {})
    news = config.get("news", {})
    if not news.get("enabled"):
        print("News dang tat (news.enabled = false)")
        return

    feeds = news.get("feeds", [])
    count = int(news.get("count", 6))
    sc = config.get("section_colors", {})
    se = config.get("section_emojis", {})
    color = parse_color(sc.get("news"), DEFAULT_SECTION_COLORS["news"])
    square = se.get("news") or DEFAULT_SECTION_EMOJIS["news"]

    # Lay nhieu hon count mot chut de con loc ra tin moi
    items = fetch_news(feeds, max(count * 4, 30))

    state = load_json(NEWS_STATE_PATH, {"seen": []})
    seen_list = state.get("seen", [])
    seen = set(seen_list)

    fresh = [it for it in items if it["link"] not in seen][:count]
    changed = False

    if fresh:
        lines = []
        for it in fresh:
            t = it["title"]
            if len(t) > 110:
                t = t[:107] + "..."
            when = f"  <t:{int(it['dt'].timestamp())}:R>" if it.get("dt") else ""
            src_txt = f"  \u00b7 *{it['src']}*" if it.get("src") else ""
            lines.append(f"\u2022 [{t}]({it['link']}){src_txt}{when}")
        embed = make_embed(f"{square} \U0001F4F0  MARKET NEWS", color, lines, footer="Crypto market news")
        send_discord(webhook, embeds=[embed])

        seen_list += [it["link"] for it in fresh]
        state["seen"] = seen_list[-SEEN_LIMIT:]
        changed = True
        print(f"Sent {len(fresh)} news item(s)")
    else:
        print("Khong co tin moi")

    if changed:
        save_json(NEWS_STATE_PATH, state)

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"state_changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()