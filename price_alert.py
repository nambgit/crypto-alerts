import json
import os
import sys
from datetime import datetime, timezone
import urllib.request
import urllib.error
import urllib.parse
import time

CONFIG_PATH = "config.json"
STATE_PATH = "state.json"
SIMPLE_URL = "https://api.coingecko.com/api/v3/simple/price"
HISTORY_URL = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
QUICKCHART_URL = "https://quickchart.io/chart/create"
UA = "discord-price-alert (https://github.com, 1.0)"

PALETTE = [
    "rgb(247,147,26)",   # BTC orange
    "rgb(98,126,234)",   # ETH blue
    "rgb(0,200,150)",    # SOL teal
    "rgb(243,186,47)",
    "rgb(231,76,60)",
]


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def http_get_json(url, timeout=30, retries=3):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 and attempt < retries:
                time.sleep(3 * (attempt + 1))  # bi gioi han nhip -> cho roi thu lai
                continue
            raise
    raise last


def fetch_prices(coin_ids, vs_currency):
    params = (
        f"?ids={','.join(coin_ids)}"
        f"&vs_currencies={vs_currency}"
        f"&include_24hr_change=true"
    )
    return http_get_json(SIMPLE_URL + params)


def fetch_history(coin_id, vs_currency, days):
    url = HISTORY_URL.format(id=coin_id) + f"?vs_currency={vs_currency}&days={days}"
    return http_get_json(url).get("prices", [])  # [[ts_ms, price], ...]


def fetch_markets(vs_currency, top_n):
    per_page = min(int(top_n), 250)
    url = (
        f"{MARKETS_URL}?vs_currency={vs_currency}&order=market_cap_desc"
        f"&per_page={per_page}&page=1&price_change_percentage=24h"
    )
    return http_get_json(url)


def send_discord(webhook_url, content=None, embeds=None):
    payload = {}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=20):
            pass
    except urllib.error.HTTPError as e:
        print(f"Discord webhook error: {e.code} {e.read().decode()}", file=sys.stderr)
        raise


def fmt_price(p):
    return f"{p:,.2f}" if p >= 1 else f"{p:,.6f}"


# ---------- Chart 5m da-coin (normalized theo % de cung 1 truc) ----------

def get_multi_chart_url(chart_coins, coins_map, vs_currency, lookback_hours):
    try:
        cutoff_ms = (datetime.now(timezone.utc).timestamp() - lookback_hours * 3600) * 1000
        series = {}
        for idx, cid in enumerate(chart_coins):
            if idx > 0:
                time.sleep(1.2)  # gian nhip cho diu API
            hist = fetch_history(cid, vs_currency, 1)  # days=1 -> ~5 phut
            hist = [p for p in hist if p[0] >= cutoff_ms]
            if hist:
                series[cid] = hist
        if not series:
            return None

        k = min(len(h) for h in series.values())
        k = min(k, 120)
        if k < 2:
            return None

        labels, datasets = None, []
        for idx, (cid, hist) in enumerate(series.items()):
            pts = hist[-k:]
            base = pts[0][1]
            vals = [round((p[1] / base - 1) * 100, 2) for p in pts]
            if labels is None:
                labels = [
                    datetime.fromtimestamp(p[0] / 1000, timezone.utc).strftime("%H:%M")
                    for p in pts
                ]
            color = PALETTE[idx % len(PALETTE)]
            datasets.append({
                "label": coins_map.get(cid, cid).upper(),
                "data": vals,
                "borderColor": color,
                "backgroundColor": color,
                "fill": False,
                "pointRadius": 0,
                "borderWidth": 2,
            })

        chart = {
            "type": "line",
            "data": {"labels": labels, "datasets": datasets},
            "options": {
                "plugins": {
                    "legend": {"display": True},
                    "title": {"display": True, "text": f"Last {lookback_hours}h - % change (5m)"},
                },
                "scales": {"x": {"ticks": {"maxTicksLimit": 6}}},
            },
        }
        spec = {"chart": chart, "width": 640, "height": 320, "backgroundColor": "white"}
        # Uu tien POST de lay link ngan
        try:
            req = urllib.request.Request(
                QUICKCHART_URL,
                data=json.dumps(spec).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": UA},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                url = json.load(resp).get("url")
                if url:
                    return url
        except Exception as e:
            print(f"QuickChart POST failed, fallback to GET: {e}", file=sys.stderr)
        # Du phong: nhung config thang vao URL GET (chi dung neu khong qua dai)
        get_url = (
            "https://quickchart.io/chart?w=640&h=320&bkg=white&c="
            + urllib.parse.quote(json.dumps(chart))
        )
        if len(get_url) > 2000:
            print("Chart GET url too long, bo qua anh", file=sys.stderr)
            return None
        return get_url
    except Exception as e:
        print(f"Chart error: {e}", file=sys.stderr)
        return None


# ---------- Bao cao (mot dong moi coin, hop mobile) ----------

UP = "\U0001F53A"    # tam giac len (tang)
DOWN = "\U0001F53B"  # tam giac xuong (giam)
COIN = "\U0001FA99"  # icon mac dinh

DEFAULT_ICONS = {
    "BTC": "\U0001F7E0", "ETH": "\U0001F537", "SOL": "\U0001F7E3",
    "BNB": "\U0001F7E1", "ADA": "\U0001F535", "OKB": "\u26AB",
    "BGB": "\U0001F7E2",
}

DEFAULT_SECTION_COLORS = {
    "current": 0xF7931A, "update": 0x5865F2,
    "gainers": 0x57F287, "losers": 0xED4245,
}

# O vuong mau dat truoc tieu de, khop voi mau vien (co the ghi de trong config)
DEFAULT_SECTION_EMOJIS = {
    "current": "🟧",  # vuong cam
    "update": "🟦",   # vuong xanh duong
    "gainers": "🟩",  # vuong xanh la
    "losers": "🟥",   # vuong do
}


def parse_color(value, default):
    if value is None:
        return default
    try:
        return int(str(value).lstrip("#"), 16)
    except Exception:
        return default


def icon_for(symbol, icons):
    s = symbol.upper()
    return icons.get(s) or DEFAULT_ICONS.get(s, COIN)


def pct_cell(chg):
    if chg is None:
        return "-"
    arrow = UP if chg >= 0 else DOWN
    return f"{arrow} {chg:+.2f}%"


def make_embed(title, color, lines, chart_url=None, footer=None):
    embed = {
        "title": title,
        "color": color,
        "description": "\n".join(lines) if lines else "No data",
    }
    if chart_url:
        embed["image"] = {"url": chart_url}
    if footer:
        embed["footer"] = {"text": footer}
    return embed


def coin_line(sym, price, chg, cur, icons, rank=None):
    icon = icon_for(sym, icons)
    prefix = f"`{rank}.` " if rank else ""
    return f"{prefix}{icon} **{sym}**  `{fmt_price(price)} {cur}`  {pct_cell(chg)}"


def build_report_embeds(config, prices):
    vs = config.get("vs_currency", "usd")
    cur = vs.upper()
    coins = config.get("coins", {})
    chart_coins = config.get("chart_coins", [])
    lookback = config.get("chart_lookback_hours", 4)
    movers_universe = config.get("movers_universe_top_n", 250)
    movers_count = int(config.get("movers_count", 10))
    icons = config.get("icons", {})
    sc = config.get("section_colors", {})
    se = config.get("section_emojis", {})
    def sq(key):
        return se.get(key) or DEFAULT_SECTION_EMOJIS[key]
    col_current = parse_color(sc.get("current"), DEFAULT_SECTION_COLORS["current"])
    col_update = parse_color(sc.get("update"), DEFAULT_SECTION_COLORS["update"])
    col_gainers = parse_color(sc.get("gainers"), DEFAULT_SECTION_COLORS["gainers"])
    col_losers = parse_color(sc.get("losers"), DEFAULT_SECTION_COLORS["losers"])
    embeds = []

    # --- Phan 1: CURRENT PRICES (kem chart) ---
    lines = []
    for cid in chart_coins:
        if cid in prices:
            sym = coins.get(cid, cid).upper()
            lines.append(coin_line(sym, prices[cid][vs], prices[cid].get(f"{vs}_24h_change"), cur, icons))
    chart_url = get_multi_chart_url(chart_coins, coins, vs, lookback)
    embeds.append(make_embed(f"{sq('current')} \U0001F4CA  CURRENT PRICES", col_current, lines, chart_url=chart_url))

    # --- Phan 2: UPDATE PRICES ---
    lines = []
    for cid, symbol in coins.items():
        if cid in prices:
            sym = symbol.upper()
            lines.append(coin_line(sym, prices[cid][vs], prices[cid].get(f"{vs}_24h_change"), cur, icons))
    embeds.append(make_embed(f"{sq('update')} \U0001F4B0  UPDATE PRICES", col_update, lines))

    # --- Phan 3 & 4: Top gainers / losers ---
    try:
        markets = fetch_markets(vs, movers_universe)
        valid = [m for m in markets if m.get("price_change_percentage_24h") is not None]
        gainers = sorted(valid, key=lambda m: m["price_change_percentage_24h"], reverse=True)[:movers_count]
        losers = sorted(valid, key=lambda m: m["price_change_percentage_24h"])[:movers_count]

        def mover_lines(items):
            out = []
            for i, m in enumerate(items, 1):
                out.append(coin_line(
                    m["symbol"].upper(),
                    m.get("current_price", 0) or 0,
                    m["price_change_percentage_24h"],
                    cur, icons, rank=i,
                ))
            return out

        embeds.append(make_embed(f"{sq('gainers')} \U0001F4C8  TOP {movers_count} GAINERS (24h)", col_gainers, mover_lines(gainers)))
        embeds.append(make_embed(f"{sq('losers')} \U0001F4C9  TOP {movers_count} LOSERS (24h)", col_losers, mover_lines(losers), footer="Data: CoinGecko"))
    except Exception as e:
        print(f"Movers error: {e}", file=sys.stderr)

    return embeds


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("Thieu bien moi truong DISCORD_WEBHOOK_URL", file=sys.stderr)
        sys.exit(1)

    config = load_json(CONFIG_PATH, {})
    coins = config.get("coins", {})
    if not coins:
        print("Chua cau hinh coin nao trong config.json", file=sys.stderr)
        sys.exit(0)

    vs = config.get("vs_currency", "usd")
    prices = fetch_prices(list(coins.keys()), vs)
    state = load_json(STATE_PATH, {"last_report": None})
    changed = False

    report = config.get("report", {})
    if report.get("enabled"):
        interval_h = float(report.get("interval_hours", 6))
        now = datetime.now(timezone.utc)
        last = state.get("last_report")
        due = True
        if last:
            due = (now - datetime.fromisoformat(last)).total_seconds() >= interval_h * 3600 - 30
        if due:
            embeds = build_report_embeds(config, prices)
            header = f"\U0001F4F0 **Crypto Market Update** \u2022 <t:{int(now.timestamp())}:f>"
            send_discord(webhook_url, content=header, embeds=embeds)
            state["last_report"] = now.isoformat()
            changed = True
            print("Report sent")

    if changed:
        save_json(STATE_PATH, state)

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"state_changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()