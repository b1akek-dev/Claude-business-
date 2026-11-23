"""Fetch ~1 year of daily closes for the S&P 500 and a stock universe from Yahoo Finance.
Writes investing/data.json, which the Paper Portfolio artifact loads.

  python3 fetch_prices.py [--extra PICKS.json]
--extra adds every symbol Claude's portfolio has ever held, queued or added to its universe."""
import argparse, json, sys, time, urllib.parse, urllib.request
from pathlib import Path

INDEX = ("^GSPC", "S&P 500")
STOCKS = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom",
    "BRK-B": "Berkshire Hathaway", "JPM": "JPMorgan Chase", "V": "Visa", "MA": "Mastercard",
    "LLY": "Eli Lilly", "UNH": "UnitedHealth", "JNJ": "Johnson & Johnson", "PFE": "Pfizer",
    "XOM": "Exxon Mobil", "CVX": "Chevron", "WMT": "Walmart", "COST": "Costco",
    "KO": "Coca-Cola", "PEP": "PepsiCo", "MCD": "McDonald's", "NKE": "Nike",
    "DIS": "Disney", "NFLX": "Netflix", "AMD": "AMD", "INTC": "Intel",
    "ORCL": "Oracle", "CRM": "Salesforce", "BA": "Boeing", "HD": "Home Depot",
    "PLTR": "Palantir", "UBER": "Uber", "SPY": "SPDR S&P 500 ETF", "QQQ": "Invesco QQQ (Nasdaq-100)",
}

US_EXCHANGES = {"NMS": "Nasdaq", "NGM": "Nasdaq", "NCM": "Nasdaq", "NYQ": "NYSE", "ASE": "NYSE American",
                "PCX": "NYSE Arca", "BTS": "Cboe BZX", "PNK": "OTC", "OQB": "OTC", "OQX": "OTC", "OBB": "OTC", "OEM": "OTC"}
TRADABLE_TYPES = {"EQUITY", "ETF"}

def fetch_raw(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)["chart"]["result"]
    except urllib.error.HTTPError as e:
        raise ValueError(f"{sym}: no data from Yahoo (HTTP {e.code}); check the ticker") from None
    if not res:
        raise ValueError(f"{sym}: no data from Yahoo; check the ticker")
    return res[0]

def fetch(sym, raw=None):
    res = raw or fetch_raw(sym)
    ts, closes = res["timestamp"], res["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = time.strftime("%Y-%m-%d", time.gmtime(t + res["meta"].get("gmtoffset", 0)))
        if out and out[-1][0] == d:
            out[-1][1] = round(c, 2)
        else:
            out.append([d, round(c, 2)])
    return out

def lookup(sym):
    """Fetch and validate one US-listed stock or ETF. Returns (name, closes, info) or raises ValueError."""
    res = fetch_raw(sym); m = res["meta"]
    if m.get("currency") != "USD" or m.get("exchangeName") not in US_EXCHANGES:
        raise ValueError(f"{sym}: listed on {m.get('fullExchangeName')} in {m.get('currency')}, not a US exchange")
    if m.get("instrumentType") not in TRADABLE_TYPES:
        raise ValueError(f"{sym}: a {m.get('instrumentType')}, not a stock or ETF")
    closes = fetch(sym, res)
    q = res["indicators"]["quote"][0]
    vols = [(c or 0) * (v or 0) for c, v in zip(q["close"], q["volume"])][-20:]
    info = {"exchange": US_EXCHANGES[m["exchangeName"]], "type": m["instrumentType"], "avg_dollar_volume": sum(vols) / max(1, len(vols))}
    return m.get("longName") or m.get("shortName") or sym, closes, info

def extra_symbols(path):
    raw = json.loads(Path(path).read_text()); doc = raw["data"] if isinstance(raw.get("data"), dict) else raw
    syms = set(doc.get("universe", [])) | {t["sym"] for t in doc.get("txns", [])} | {o["sym"] for o in doc.get("pending", [])}
    return sorted(syms - set(STOCKS) - {INDEX[0]})

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--extra"); a = ap.parse_args()
    extras = extra_symbols(a.extra) if a.extra else []
    data = {"updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": "Yahoo Finance daily closes", "series": {}}
    for sym, name in [INDEX] + list(STOCKS.items()) + [(s, None) for s in extras]:
        try:
            if name is None:
                name, closes, _ = lookup(sym)
            else:
                closes = fetch(sym)
            data["series"][sym] = {"name": name, "closes": closes}
        except Exception as e:
            print(f"skip {sym}: {e}", file=sys.stderr)
        time.sleep(0.3)
    if "^GSPC" not in data["series"]:
        sys.exit("S&P 500 fetch failed; not overwriting data.json")
    out = Path(__file__).with_name("data.json")
    out.write_text(json.dumps(data, separators=(",", ":")))
    print(f"wrote {out} with {len(data['series'])} series, last date {data['series']['^GSPC']['closes'][-1][0]}")

if __name__ == "__main__":
    main()
