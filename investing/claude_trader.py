"""Bookkeeping for Claude's daily-trading portfolio in the Paper Portfolio artifact.

The portfolio lives in the artifact database doc picks/claude. A daily run saves it to a
JSON file, runs this script against it, and writes the file back. Commands:

  python3 claude_trader.py PICKS.json fill
      Fill every pending order placed BEFORE the latest close in data.json, at that close.
      Sells fill before buys. Buys are capped by available cash; sells by shares held.
  python3 claude_trader.py PICKS.json status
      Print holdings, cash, total value and the S&P 500 benchmark.
  python3 claude_trader.py PICKS.json order buy SYM --dollars 500 --why "..."
  python3 claude_trader.py PICKS.json order sell SYM --shares all|N --why "..."
      Queue an order for the next close. Enforces the limits in TRADING_RULES.md.
  python3 claude_trader.py PICKS.json add SYM
      Add any US-listed stock or ETF (Nasdaq, NYSE, NYSE American, NYSE Arca, Cboe, OTC) to the
      universe: fetches its price history into data.json and records it in the portfolio doc.
  python3 claude_trader.py PICKS.json journal --note "..."
      Record today's market read (required every run, even when no trades are made).
"""
import argparse, json, sys
from pathlib import Path

START_CASH = 5000.0
MAX_ORDERS_PER_DAY = 3
MAX_POSITION_SHARE = 0.25   # no single stock above 25% of portfolio value after a buy
MIN_TRADE = 100.0
MIN_PRICE = 1.0                 # no sub-$1 stocks
MIN_DOLLAR_VOLUME = 1_000_000   # 20-day average; a closing price must be one you could really trade at

DATA_PATH = Path(__file__).with_name("data.json")
DATA_FILE = json.loads(DATA_PATH.read_text())
DATA = DATA_FILE["series"]
DATES = [d for d, _ in DATA["^GSPC"]["closes"]]
LATEST = DATES[-1]

def price(sym, date):
    best = None
    for d, c in DATA[sym]["closes"]:
        if d <= date: best = c
        else: break
    if best is None: sys.exit(f"no price for {sym} on {date}")
    return best

def load(path):
    raw = json.loads(Path(path).read_text())
    doc = raw.get("data", raw) if isinstance(raw.get("data"), dict) else raw
    for k, v in (("txns", []), ("pending", []), ("journal", []), ("why", {}), ("universe", [])): doc.setdefault(k, v)
    return doc

def save(path, doc):
    Path(path).write_text(json.dumps(doc, indent=1))

def book(doc, upto=LATEST):
    cash, pos, bench = START_CASH, {}, 0.0
    for t in doc["txns"]:
        if t["d"] > upto: break
        amt = t["shares"] * t["price"]; spx = price("^GSPC", t["d"])
        if t["side"] == "buy":
            cash -= amt; pos[t["sym"]] = pos.get(t["sym"], 0) + t["shares"]; bench += amt / spx
        else:
            cash += amt; pos[t["sym"]] -= t["shares"]; bench -= amt / spx
            if pos[t["sym"]] < 1e-9: del pos[t["sym"]]
    return cash, pos, bench

def value(doc, date=LATEST):
    cash, pos, bench = book(doc, date)
    return cash + sum(s * price(k, date) for k, s in pos.items()), cash + bench * price("^GSPC", date), cash, pos

def cmd_fill(doc):
    ready = [o for o in doc["pending"] if o["placed"] < LATEST]
    doc["pending"] = [o for o in doc["pending"] if o["placed"] >= LATEST]
    if not ready: print(f"No orders to fill (latest close {LATEST})."); return
    for o in sorted(ready, key=lambda o: o["side"] != "sell"):
        cash, pos, _ = book(doc); p = price(o["sym"], LATEST)
        if o["side"] == "sell":
            held = pos.get(o["sym"], 0)
            sh = held if o.get("shares") == "all" else min(float(o["shares"]), held)
            if sh <= 0: print(f"SKIP sell {o['sym']}: none held"); continue
            if held - sh < 1e-6: sh = held
        else:
            dollars = min(float(o["dollars"]), cash)
            if dollars < 1: print(f"SKIP buy {o['sym']}: no cash"); continue
            sh = dollars / p
        doc["txns"].append({"d": LATEST, "sym": o["sym"], "side": o["side"], "shares": round(sh, 6), "price": p, "why": o.get("why", ""), "placed": o["placed"]})
        print(f"FILLED {o['side']} {sh:.4f} {o['sym']} @ {p} on {LATEST}")
    _, pos_after = book(doc)[:2]
    for sym in list(doc["why"]):
        if sym not in pos_after: doc["why"].pop(sym)

def cmd_status(doc):
    v, bv, cash, pos = value(doc)
    print(f"Latest close {LATEST}. Value ${v:,.2f}  S&P same-cash ${bv:,.2f}  edge ${v-bv:+,.2f}  cash ${cash:,.2f}")
    for k, s in sorted(pos.items(), key=lambda kv: -kv[1] * price(kv[0], LATEST)):
        mv = s * price(k, LATEST); print(f"  {k:6} {s:10.4f} sh  ${mv:9,.2f}  {mv/v*100:5.1f}%")
    for o in doc["pending"]: print(f"  PENDING {o}")

def cmd_order(doc, a):
    sym = a.sym.upper()
    if sym not in DATA or sym == "^GSPC": sys.exit(f"{sym} is not in the universe yet; run: add {sym}")
    if not a.why or len(a.why) < 20: sys.exit("--why must explain the news-based reason (20+ chars)")
    today = [o for o in doc["pending"] if o["placed"] == LATEST]
    if len(today) >= MAX_ORDERS_PER_DAY: sys.exit(f"limit: {MAX_ORDERS_PER_DAY} orders per day")
    if any(o["sym"] == sym for o in today): sys.exit(f"already have an order for {sym} today")
    v, _, cash, pos = value(doc)
    sells = sum((pos.get(o["sym"], 0) if o.get("shares") == "all" else float(o["shares"])) * price(o["sym"], LATEST) for o in today if o["side"] == "sell")
    buys = sum(float(o["dollars"]) for o in today if o["side"] == "buy")
    if a.side == "buy":
        if a.dollars is None or a.dollars < MIN_TRADE: sys.exit(f"buy needs --dollars >= {MIN_TRADE}")
        if a.dollars > cash + sells - buys + 0.01: sys.exit(f"not enough cash: ${cash + sells - buys:,.2f} available incl. today's sells")
        held = pos.get(sym, 0) * price(sym, LATEST)
        if held + a.dollars > MAX_POSITION_SHARE * v: sys.exit(f"limit: {sym} would exceed {MAX_POSITION_SHARE:.0%} of the portfolio")
        doc["pending"].append({"placed": LATEST, "side": "buy", "sym": sym, "dollars": round(a.dollars, 2), "why": a.why})
    else:
        if sym not in pos: sys.exit(f"you don't hold {sym}")
        sh = a.shares if a.shares == "all" else float(a.shares)
        doc["pending"].append({"placed": LATEST, "side": "sell", "sym": sym, "shares": sh, "why": a.why})
    print(f"QUEUED {a.side} {sym} for the next close after {LATEST}")

def cmd_add(doc, sym):
    sym = sym.upper().replace(".", "-")
    sys.path.insert(0, str(Path(__file__).parent)); import fetch_prices
    try:
        name, closes, info = fetch_prices.lookup(sym)
    except ValueError as e:
        sys.exit(str(e))
    if closes[-1][0] != LATEST: sys.exit(f"{sym}: last close {closes[-1][0]} doesn't match the index ({LATEST}); halted or delisted?")
    if closes[-1][1] < MIN_PRICE: sys.exit(f"{sym}: price ${closes[-1][1]} is under ${MIN_PRICE:.0f}")
    if info["avg_dollar_volume"] < MIN_DOLLAR_VOLUME: sys.exit(f"{sym}: trades only ${info['avg_dollar_volume']:,.0f}/day; too thin to trust a closing price")
    DATA[sym] = {"name": name, "closes": closes}
    DATA_PATH.write_text(json.dumps(DATA_FILE, separators=(",", ":")))
    if sym not in doc["universe"]: doc["universe"].append(sym)
    print(f"ADDED {sym} ({name}, {info['type']} on {info['exchange']}), last close ${closes[-1][1]} on {closes[-1][0]}")

def cmd_journal(doc, note):
    doc["journal"] = [j for j in doc["journal"] if j["d"] != LATEST] + [{"d": LATEST, "note": note}]
    doc["journal"] = doc["journal"][-60:]
    print("journal saved")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("file"); sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("fill"); sp.add_parser("status")
    o = sp.add_parser("order"); o.add_argument("side", choices=["buy", "sell"]); o.add_argument("sym")
    o.add_argument("--dollars", type=float); o.add_argument("--shares", default="all"); o.add_argument("--why", required=True)
    ad = sp.add_parser("add"); ad.add_argument("sym")
    j = sp.add_parser("journal"); j.add_argument("--note", required=True)
    a = ap.parse_args(); doc = load(a.file)
    {"fill": lambda: cmd_fill(doc), "status": lambda: cmd_status(doc), "order": lambda: cmd_order(doc, a), "journal": lambda: cmd_journal(doc, a.note), "add": lambda: cmd_add(doc, a.sym)}[a.cmd]()
    if a.cmd != "status": save(a.file, doc)
