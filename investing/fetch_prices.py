"""Fetch ~1 year of daily closes for the S&P 500 and a stock universe from Yahoo Finance.
Writes investing/data.json, which the Paper Portfolio artifact loads."""
import json, sys, time, urllib.request
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

def fetch(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)["chart"]["result"][0]
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

import urllib.parse
def main():
    data = {"updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": "Yahoo Finance daily closes", "series": {}}
    for sym, name in [INDEX] + list(STOCKS.items()):
        try:
            data["series"][sym] = {"name": name, "closes": fetch(sym)}
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
