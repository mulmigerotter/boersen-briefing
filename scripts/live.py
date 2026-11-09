"""Aktuelle Kurse (von Yahoo verzögert) für alle Aktien und Indizes -> docs/data/live.json.

Läuft während der Handelszeiten alle 30 Minuten (.github/workflows/live.yml) und bei jedem
Tageslauf. Die Datei wird nur mit veröffentlicht, nicht ins Repository geschrieben.
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update as u  # noqa: E402


def main():
    import pandas as pd
    import yfinance as yf

    stocks = u.all_stock_symbols()
    idx = [i["symbol"] for i in u.CONFIG["indices"]]
    fx_syms = sorted(set(u.FX.values()))
    syms = idx + stocks + fx_syms
    data = yf.download(syms, period="5d", interval="1d", auto_adjust=False,
                       group_by="ticker", progress=False, threads=True)
    q, fx = {}, {}
    for s in syms:
        try:
            col = data[s]["Close"] if isinstance(data.columns, pd.MultiIndex) else data["Close"]
            col = col.dropna()
            if len(col) < 2:
                continue
            last, prev = float(col.iloc[-1]), float(col.iloc[-2])
            day = pd.Timestamp(col.index[-1]).date().isoformat()
        except Exception:
            continue
        if s in fx_syms:
            cur = next(c for c, v in u.FX.items() if v == s)
            fx[cur] = round(last, 6)
        else:
            rnd = 4 if last < 20 else 2
            q[s] = [round(last, rnd), round(prev, rnd), day]
    out = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "fx": fx,
           "cur": {s: u.currency_of(s) for s in stocks}, "q": q}
    u.DATA.mkdir(parents=True, exist_ok=True)
    (u.DATA / "live.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"live.json: {len(q)} Kurse, {len(fx)} Wechselkurse")


if __name__ == "__main__":
    main()
