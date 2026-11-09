"""Börsen-Briefing: holt jeden Handelstag Kurse und Analystendaten, rechnet die
Top-5 mit Monte-Carlo-Simulation und schreibt die Daten für die Webseite.

Aufruf (GitHub Actions macht das automatisch):
    python scripts/update.py            # normaler Tageslauf
    python scripts/update.py --force    # Tag neu rechnen, auch wenn es ihn schon gibt
    python scripts/update.py --demo     # Testlauf mit Zufallsdaten, ohne Internet
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA = ROOT / "docs" / "data"
DAYS_DIR = DATA / "days"
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
SYM = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}


# ---------------------------------------------------------------- Hilfen
def clip(x, lo, hi):
    return max(lo, min(hi, x))


def log(msg):
    print(msg, flush=True)


def de(v, dec=2):
    """Zahl im deutschen Format: 25820.36 -> 25.820,36"""
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v, dec=1):
    """Prozent mit Vorzeichen: 1.234 -> +1,2 %"""
    sign = "+" if v >= 0 else "−"
    return f"{sign}{de(abs(v), dec)} %"


def money(v, cur="EUR"):
    return f"{de(v)} {SYM.get(cur, cur)}"


def num(v):
    try:
        v = float(v)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def short_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{WEEKDAYS[d.weekday()]} {d:%d.%m.}"


# ---------------------------------------------------------------- Daten holen
def fetch_history(symbols):
    """Schlusskurse der letzten ~15 Monate: {symbol: [(date, close), ...]}"""
    import pandas as pd
    import yfinance as yf

    out = {}

    def take(sym, col):
        col = col.dropna()
        if len(col) >= 30:
            out[sym] = [(pd.Timestamp(i).date(), float(v)) for i, v in col.items()]

    try:
        data = yf.download(symbols, period="15mo", interval="1d", auto_adjust=True,
                           group_by="ticker", progress=False, threads=True)
        for s in symbols:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    lv0 = data.columns.get_level_values(0)
                    col = data[s]["Close"] if s in lv0 else data["Close"][s]
                else:
                    col = data["Close"]
                take(s, col)
            except Exception:
                pass
    except Exception as e:
        log(f"Sammel-Download fehlgeschlagen: {e}")

    for s in [s for s in symbols if s not in out]:
        for attempt in range(2):
            try:
                h = yf.Ticker(s).history(period="15mo", interval="1d", auto_adjust=True)
                take(s, h["Close"])
                break
            except Exception as e:
                log(f"Kurse für {s} fehlgeschlagen ({e}), neuer Versuch …")
                time.sleep(3)
        time.sleep(0.5)
    log(f"Kursdaten für {len(out)} von {len(symbols)} Werten geladen")
    return out


def fetch_meta(sym, today):
    """Analystendaten und Termine eines Werts (alles optional)."""
    import yfinance as yf

    t = yf.Ticker(sym)
    m = {"updated": today.isoformat()}
    try:
        info = t.info or {}
    except Exception as e:
        log(f"  info {sym}: {e}")
        info = {}
    m["target"] = num(info.get("targetMeanPrice"))
    m["n_analysts"] = int(num(info.get("numberOfAnalystOpinions")) or 0)
    rec_mean = num(info.get("recommendationMean"))
    if info.get("currency"):
        m["currency"] = info["currency"]
    try:
        rec = t.recommendations
        if rec is not None and len(rec):
            if "period" in rec.columns and (rec["period"] == "0m").any():
                row = rec[rec["period"] == "0m"].iloc[0]
            else:
                row = rec.iloc[0]
            keys = ["strongBuy", "buy", "hold", "sell", "strongSell"]
            counts = {k: int(num(row.get(k)) or 0) for k in keys}
            total = sum(counts.values())
            if total:
                m["buy_share"] = (counts["strongBuy"] + counts["buy"]) / total
                m["n_ratings"] = total
    except Exception as e:
        log(f"  Empfehlungen {sym}: {e}")
    if "buy_share" not in m and rec_mean:
        # 1 = Strong Buy … 5 = Sell, grob in einen Kaufanteil umrechnen
        m["buy_share"] = clip((3 - rec_mean) / 2, 0, 1)
        m["buy_share_est"] = True
    try:
        cal = t.calendar
        raw = []
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date") or []
        elif cal is not None and hasattr(cal, "index") and "Earnings Date" in cal.index:
            raw = list(cal.loc["Earnings Date"])
        if not isinstance(raw, (list, tuple)):
            raw = [raw]
        dates = set()
        for d in raw:
            try:
                dates.add((d.date() if hasattr(d, "date") and callable(d.date) else d).isoformat())
            except Exception:
                pass
        m["earnings"] = sorted(dates)
    except Exception as e:
        log(f"  Termine {sym}: {e}")
    return m


def refresh_meta(symbols, today, cache):
    """Analystendaten höchstens alle paar Tage neu holen (schont Yahoo)."""
    max_age = CONFIG["meta_refresh_days"]

    def age(s):
        try:
            return (today - dt.date.fromisoformat(cache[s]["updated"])).days
        except Exception:
            return 999

    todo = sorted([s for s in symbols if age(s) >= max_age], key=age, reverse=True)
    todo = todo[: CONFIG["meta_max_refresh"]]
    log(f"Analystendaten: {len(todo)} Werte werden aktualisiert")
    for s in todo:
        try:
            new = fetch_meta(s, today)
            old = cache.get(s, {})
            for k, v in old.items():  # fehlende Felder vom letzten Mal behalten
                if new.get(k) in (None, [], 0) and v not in (None, [], 0):
                    new[k] = v
            cache[s] = new
        except Exception as e:
            log(f"  {s}: {e}")
        time.sleep(1.0)
    return cache


# ---------------------------------------------------------------- Kennzahlen
def stats(series, day):
    """Kennzahlen aus der Kurshistorie bis einschließlich `day`."""
    s = [(d, c) for d, c in series if d <= day]
    if len(s) < 30:
        return None
    closes = np.array([c for _, c in s])
    last_d, last = s[-1]
    st = {"price": round(float(last), 2), "last_date": last_d.isoformat(),
          "fresh": last_d == day}
    st["day_change"] = float((closes[-1] / closes[-2] - 1) * 100)
    rets = np.diff(np.log(closes[-251:]))
    st["sigma"] = float(rets.std(ddof=1) * math.sqrt(252)) if len(rets) > 20 else None
    if len(closes) >= 200:
        sma = float(closes[-200:].mean())
        st["sma200"] = round(sma, 2)
        st["trend200"] = "über" if last > sma else "unter"
    else:
        st["trend200"] = "unbekannt"
    st["ret20"] = float((closes[-1] / closes[-21] - 1) * 100) if len(closes) > 21 else 0.0
    year = closes[-252:]
    st["hi52"], st["lo52"] = round(float(year.max()), 2), round(float(year.min()), 2)
    return st


def score(x):
    price, target = x["price"], x.get("target")
    pot = (target / price - 1) if (target and price) else 0.0
    buy = x.get("buy_share")
    parts = {
        "potenzial": clip(pot / 0.5, 0, 1) * 30,
        "analysten": clip((buy - 0.5) / 0.5, 0, 1) * 20 if buy is not None else 0.0,
        "tag": clip(((x.get("day_change") or 0) + 5) / 10, 0, 1) * 10,
        "trend": {"über": 15, "unter": 0}.get(x.get("trend200"), 7.5),
        "termin": 15 if x.get("event") else 0,
        "momentum": clip((x.get("ret20", 0) + 10) / 20, 0, 1) * 10,
    }
    parts = {k: round(v, 1) for k, v in parts.items()}
    return round(sum(parts.values()), 1), parts, pot


def simulate(price, sigma, mu, seed, runs, days, df=4):
    """Monte-Carlo: `runs` zufällige Kursverläufe über `days` Handelstage.
    Tagesrenditen t-verteilt (dicke Ränder), Schwankung sigma, Trend mu (pro Jahr)."""
    rng = np.random.default_rng(seed)
    step = 1 / 252
    eps = rng.standard_t(df, size=(runs, days)) * math.sqrt((df - 2) / df)
    steps = (mu - 0.5 * sigma ** 2) * step + sigma * math.sqrt(step) * eps
    logp = np.concatenate([np.zeros((runs, 1)), np.cumsum(steps, axis=1)], axis=1)
    paths = price * np.exp(logp)
    bands = {f"p{p}": [round(float(v), 2) for v in np.percentile(paths, p, axis=0)]
             for p in (10, 25, 50, 75, 90)}
    end = paths[:, -1]
    return bands, round(float((end > price).mean()), 3), round(float((end < 0.9 * price).mean()), 3)


def why_text(x):
    cur, parts = x["currency"], []
    if x.get("target") and x["potential"] > 0:
        n = x.get("n_analysts") or 0
        parts.append(f"Ø-Kursziel {money(x['target'], cur)} ({pct(x['potential'] * 100, 0)})"
                     + (f" von {n} Analysten" if n else ""))
    if x.get("buy_share") is not None and x["buy_share"] >= 0.6:
        parts.append(f"{round(x['buy_share'] * 100)} % Kaufempfehlungen")
    if x.get("event"):
        parts.append(f"Zahlen am {short_date(x['event'])}")
    if x.get("trend200") == "über":
        parts.append("Kurs über der 200-Tage-Linie")
    if x.get("ret20", 0) >= 5:
        parts.append(f"{pct(x['ret20'], 0)} in 20 Tagen")
    text = "; ".join(parts[:3]) if parts else "Solide Werte bei allen Kennzahlen"
    return text if text.endswith(".") else text + "."


def risk_text(x):
    parts, s = [], x.get("sigma") or 0
    if s >= 0.45:
        parts.append(f"Sehr schwankungsanfällig ({round(s * 100)} % pro Jahr)")
    if x.get("trend200") == "unter":
        parts.append("Kurs unter der 200-Tage-Linie")
    if x.get("ret20", 0) <= -10:
        parts.append(f"{pct(x['ret20'], 0)} in 20 Tagen")
    if x.get("event"):
        parts.append("die Zahlen können den Kurs stark bewegen")
    if not parts:
        parts.append("Analysten können ihre Ziele jederzeit senken")
    text = "; ".join(parts[:2])
    text = text[0].upper() + text[1:]
    return text if text.endswith(".") else text + "."


# ---------------------------------------------------------------- Hauptlauf
def build(hist, meta, today, force=False):
    runs, days = CONFIG["runs"], CONFIG["days"]
    idx_cfg = CONFIG["indices"]
    stocks = [dict(s, group="DAX") for s in CONFIG["dax"]] + [dict(s, group="USA") for s in CONFIG["us"]]

    # Handelstag = letzter DAX-Kurs (bei deutschem Feiertag: letzter US-Kurs)
    last_days = [hist[i["symbol"]][-1][0] for i in idx_cfg if i["symbol"] in hist]
    if not last_days:
        raise SystemExit("Keine Indexdaten – Abbruch, nichts wird geändert.")
    day = max([d for d in last_days if d <= today] or last_days)
    date = day.isoformat()

    index_file = DATA / "index.json"
    index = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else {"days": []}
    if not force and any(e["date"] == date for e in index["days"]):
        log(f"{date} gibt es schon (kein neuer Handelstag) – nichts zu tun.")
        return False

    # Indizes
    indices = []
    for i in idx_cfg:
        st = stats(hist.get(i["symbol"], []), day)
        if not st:
            continue
        note = "Schluss" if st["fresh"] else f"Stand {dt.date.fromisoformat(st['last_date']):%d.%m.}"
        indices.append({"name": i["name"], "value": f"{de(st['price'], 0)} Pkt.",
                        "change": round(st["day_change"], 2), "note": note})
    dax = next((i for i in indices if i["name"] == "DAX"), None)

    # Aktien
    rows = []
    horizon = day + dt.timedelta(days=10)  # ~7 Handelstage
    for s in stocks:
        st = stats(hist.get(s["symbol"], []), day)
        if not st:
            continue
        m = meta.get(s["symbol"], {})
        x = dict(s, **st)
        if not x["fresh"]:
            x["day_change"] = None  # kein Kurs von heute: nicht als Gewinner/Verlierer zählen
        x["currency"] = m.get("currency") or ("EUR" if s["group"] == "DAX" else "USD")
        x["target"] = m.get("target")
        x["n_analysts"] = m.get("n_analysts") or m.get("n_ratings") or 0
        x["buy_share"] = m.get("buy_share")
        ev = [d for d in m.get("earnings", []) if day < dt.date.fromisoformat(d) <= horizon]
        x["event"] = ev[0] if ev else None
        sc, parts, pot = score(x)
        x.update(score=sc, parts=parts, potential=pot)
        reason = None
        if not x.get("target") or x["n_analysts"] < 3:
            reason = "zu wenig Analystendaten"
        elif x.get("day_change") is not None and x["day_change"] <= -10:
            reason = "Kurssturz heute – erst Nachrichten prüfen"
        elif not x["fresh"]:
            reason = "kein aktueller Kurs"
        x["excluded"], x["reason"] = reason is not None, reason
        rows.append(x)
    rows.sort(key=lambda r: r["score"], reverse=True)

    # Top 5 mit Simulation
    picks = []
    for r in [r for r in rows if not r["excluded"]][:5]:
        sigma = clip(r["sigma"] or 0.30, 0.08, 1.5)
        mu = clip(math.log(r["target"] / r["price"]), -0.5, 0.5)
        seed = int(hashlib.sha256((date + r["symbol"]).encode()).hexdigest()[:8], 16)
        bands, p_up, p_loss = simulate(r["price"], sigma, mu, seed, runs, days)
        picks.append({
            "rank": len(picks) + 1, "name": r["name"], "symbol": r["symbol"], "currency": r["currency"],
            "price": r["price"], "target": round(r["target"], 2), "score": r["score"], "parts": r["parts"],
            "sigma": round(sigma, 4), "sigmaSource": "berechnet aus 250 Handelstagen",
            "mu": round(mu, 4), "days": days, "runs": runs, "seed": seed,
            "bands": bands, "pUp": p_up, "pLoss10": p_loss,
            "why": why_text(r), "risk": risk_text(r),
        })

    # Gewinner/Verlierer
    dax_rows = [r for r in rows if r["group"] == "DAX" and r.get("day_change") is not None]
    dax_rows.sort(key=lambda r: r["day_change"], reverse=True)
    us_rows = sorted([r for r in rows if r["group"] == "USA" and r.get("day_change") is not None],
                     key=lambda r: r["day_change"], reverse=True)
    top, flop = (dax_rows[0], dax_rows[-1]) if dax_rows else (None, None)
    ups = sum(1 for r in dax_rows if r["day_change"] > 0)
    downs = sum(1 for r in dax_rows if r["day_change"] < 0)

    def move(r):
        return f"{r['name']} {pct(r['day_change'])}"

    # Texte
    if dax:
        c = dax["change"]
        lead = ("DAX kaum verändert" if abs(c) < 0.3 else
                f"DAX {'steigt' if c > 0 else 'fällt'} um {de(abs(c), 1)} %")
        headline = f"{lead} – {top['name']} vorn, {flop['name']} hinten" if top else lead
    else:
        headline = "Börsen-Briefing"
    lines = ["**📊 Das war heute wichtig**"]
    if indices:
        lines.append("- " + " · ".join(f"{i['name']} {i['value']} ({pct(i['change'], 2)})" for i in indices))
    if dax_rows:
        lines.append(f"- Im DAX: {ups} Gewinner, {downs} Verlierer.")
        lines.append("- Stärkste DAX-Werte: " + ", ".join(move(r) for r in dax_rows[:3]))
        lines.append("- Schwächste DAX-Werte: " + ", ".join(move(r) for r in dax_rows[-3:][::-1]))
    if us_rows:
        lines.append(f"- US-Tech: vorn {move(us_rows[0])}, hinten {move(us_rows[-1])}")
    upcoming = sorted([r for r in rows if r.get("event")], key=lambda r: r["event"])
    if upcoming:
        lines += ["", "**📅 Bald Zahlen (nächste 7 Handelstage)**"]
        by_day = {}
        for r in upcoming:
            by_day.setdefault(r["event"], []).append(r["name"])
        for d, names in sorted(by_day.items()):
            lines.append(f"- {short_date(d)}: {', '.join(names)}")
    lines += ["", "**ℹ️ So entsteht diese Seite**",
              "Ein Programm rechnet jeden Handelstag automatisch mit Kursen und Analystendaten "
              "von Yahoo Finance. Gründe für Kursbewegungen kennt es nicht – dafür lohnt ein Blick in die Nachrichten."]

    doc = {
        "date": date, "kind": "tag", "headline": headline,
        "updatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "indices": indices,
        "top": {"name": top["name"], "change": round(top["day_change"], 2),
                "why": f"Schluss {money(top['price'], top['currency'])}"} if top else None,
        "flop": {"name": flop["name"], "change": round(flop["day_change"], 2),
                 "why": f"Schluss {money(flop['price'], flop['currency'])}"} if flop else None,
        "picks5": picks,
        "ranking": [{"name": r["name"], "score": r["score"], "excluded": r["excluded"],
                     "reason": r["reason"]} for r in rows[:15]],
        "rechnerStand": f"Stand: Schlusskurse vom {day:%d.%m.%Y}, {len(rows)} Aktien geprüft",
        "text": "\n".join(lines),
        "sources": [{"title": "Yahoo Finance", "url": "https://finance.yahoo.com/"}],
    }

    DAYS_DIR.mkdir(parents=True, exist_ok=True)
    (DAYS_DIR / f"{date}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    entry = {"date": date, "kind": "tag", "headline": headline, "dax": dax["change"] if dax else None}
    index["days"] = [entry] + [e for e in index["days"] if e["date"] != date]
    index["days"].sort(key=lambda e: e["date"], reverse=True)
    index["days"] = index["days"][: CONFIG["max_archive"]]
    index["updated"] = doc["updatedAt"]
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    log(f"\n{date}: {headline}")
    for r in rows[:10]:
        flag = f"  ({r['reason']})" if r["excluded"] else ""
        log(f"  {r['score']:5.1f}  {r['name']}{flag}")
    for p in picks:
        b = p["bands"]
        log(f"  Top {p['rank']}: {p['name']} {p['price']} → Median {b['p50'][-1]} "
            f"(80 %: {b['p10'][-1]}–{b['p90'][-1]}), Plus in {round(p['pUp'] * 100)} %")
    return True


# ---------------------------------------------------------------- Merkliste (geschützter Bereich)
WATCH_FILE = ROOT / "watch.json"
FX = {"USD": "EURUSD=X", "HKD": "EURHKD=X", "AUD": "EURAUD=X", "GBP": "EURGBP=X", "CHF": "EURCHF=X", "SEK": "EURSEK=X"}


def watch_symbols():
    try:
        return list(json.loads(WATCH_FILE.read_text(encoding="utf-8")).get("watch", []))
    except Exception:
        return []


def currency_of(sym):
    suffix = sym.rsplit(".", 1)[-1].upper() if "." in sym else ""
    return {"DE": "EUR", "F": "EUR", "AS": "EUR", "PA": "EUR", "MI": "EUR", "VI": "EUR",
            "MC": "EUR", "HK": "HKD", "AX": "AUD", "SW": "CHF", "ST": "SEK"}.get(suffix, "USD")


def all_stock_symbols():
    """Alle Aktien der Seite: DAX, US-Werte und die Merkliste aus dem gesperrten Bereich."""
    return list(dict.fromkeys([x["symbol"] for x in CONFIG["dax"] + CONFIG["us"]] + watch_symbols()))


def write_long(today):
    """Monatliche Schlusskurse inkl. Dividenden (auto_adjust) in Euro seit 2000 -> long.json (für „Was wäre wenn“)."""
    import pandas as pd
    import yfinance as yf

    syms = all_stock_symbols()
    fx_syms = sorted({FX[c] for c in map(currency_of, syms) if c in FX})
    data = yf.download(syms + fx_syms, period="max", interval="1mo", auto_adjust=True,
                       group_by="ticker", progress=False, threads=True)

    def series(sym):
        try:
            col = data[sym]["Close"] if isinstance(data.columns, pd.MultiIndex) else data["Close"]
        except Exception:
            return None
        col = col.dropna()
        col = col[col.index >= "2000-01-01"]
        if not len(col):
            return None
        col.index = pd.to_datetime(col.index).to_period("M")
        return col.groupby(level=0).last()

    fx = {c: series(FX[c]) for c in FX if FX[c] in fx_syms}
    out = {}
    for sym in syms:
        ser = series(sym)
        cur = currency_of(sym)
        if ser is None or len(ser) < 2:
            continue
        if cur != "EUR":
            rate = fx.get(cur)
            if rate is None or not len(rate):
                continue
            rate = rate.reindex(ser.index.union(rate.index)).ffill().reindex(ser.index)
            ser = (ser / rate).dropna()
        if len(ser) < 2:
            continue
        sig = lambda v: float(f"{v:.5g}")
        out[sym] = {"s": str(ser.index[0]), "v": [sig(v) for v in ser.values]}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "long.json").write_text(json.dumps({"updated": today.isoformat(), "q": out}, separators=(",", ":")), encoding="utf-8")
    log(f"Langfristige Kurse: {len(out)} von {len(syms)} Aktien")


def watch_fetch_list():
    syms = watch_symbols()
    fx = sorted({FX[c] for c in map(currency_of, syms) if c in FX})
    return syms + fx


def write_quotes(hist):
    """Kurs in Euro, Schwankung und die letzten Schlusskurse für die Merkliste -> quotes.json."""
    out = {}
    for sym in all_stock_symbols():
        ser = hist.get(sym) or []
        cur = currency_of(sym)
        if len(ser) < 22:
            log(f"  Merkliste {sym}: keine Kurse")
            continue
        local_last = ser[-1][1]
        if cur != "EUR":
            fx = hist.get(FX.get(cur, ""), [])
            if not fx:
                log(f"  Merkliste {sym}: kein Wechselkurs {cur}")
                continue
            conv, j, rate = [], 0, None
            for d, v in ser:
                while j < len(fx) and fx[j][0] <= d:
                    rate = fx[j][1]
                    j += 1
                if rate:
                    conv.append((d, v / rate))
            ser = conv
        if len(ser) < 22:
            continue
        closes = np.array([v for _, v in ser])
        rets = np.diff(np.log(closes[-251:]))
        rnd = lambda v: round(float(v), 4 if v < 20 else 2)
        out[sym] = {
            "eur": rnd(closes[-1]), "date": ser[-1][0].isoformat(), "cur": cur,
            "local": rnd(local_last), "sigma": round(float(rets.std(ddof=1) * math.sqrt(252)), 4),
            "n": int(len(rets)), "hist": [[d.isoformat(), rnd(v)] for d, v in ser[-70:]],
        }
    if not out and not watch_symbols():
        return
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "quotes.json").write_text(json.dumps({
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "q": out,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"Merkliste: {len(out)} von {len(watch_symbols())} Werten mit Kursen")


# ---------------------------------------------------------------- Dividenden (Yahoo, Ex-Tage)
DIV_FILE = DATA / "dividends.json"
FREQ = {1: "jährlich", 2: "halbjährlich", 3: "vierteljährlich", 4: "vierteljährlich", 12: "monatlich"}


def summarize_dividends(rows, today):
    """rows: [(date, betrag)] aufsteigend -> kompakte Zusammenfassung für die Webseite."""
    if not rows:
        return {"none": True}
    last12 = [r for r in rows if r[0] > today - dt.timedelta(days=365)]
    n12 = len(last12)
    out = {"n12": n12, "sum12": round(sum(v for _, v in last12), 4),
           "last": [rows[-1][0].isoformat(), round(rows[-1][1], 4)],
           "months": sorted({d.month for d, _ in last12}),
           "hist": [[d.isoformat(), round(v, 4)] for d, v in rows[-8:]]}
    if n12:
        out["freq"] = FREQ.get(n12, "monatlich" if n12 >= 10 else f"{n12}× pro Jahr")
        step = dt.timedelta(days=round(365 / n12))
        nxt = rows[-1][0] + step
        while nxt <= today:
            nxt += step
        out["next"] = nxt.isoformat()
    else:
        out["freq"] = "zuletzt keine"
    return out


def refresh_dividends(symbols, today, cache, max_new=200, max_old=40):
    import pandas as pd
    import yfinance as yf

    def age(sym):
        try:
            return (today - dt.date.fromisoformat(cache[sym]["updated"])).days
        except Exception:
            return 999

    missing = [x for x in symbols if x not in cache][:max_new]
    stale = sorted([x for x in symbols if x in cache and age(x) >= 7], key=age, reverse=True)[:max_old]
    for sym in missing + stale:
        try:
            ser = yf.Ticker(sym).dividends
            rows = []
            if ser is not None and len(ser):
                for idx, v in ser.items():
                    d = pd.Timestamp(idx).date()
                    if d >= today - dt.timedelta(days=3 * 366) and float(v) > 0:
                        rows.append((d, float(v)))
            entry = summarize_dividends(sorted(rows), today)
            entry["cur"] = currency_of(sym)
            entry["updated"] = today.isoformat()
            cache[sym] = entry
        except Exception as e:
            log(f"  Dividende {sym}: {e}")
        time.sleep(0.3)
    log(f"Dividenden: {len(missing)} neu, {len(stale)} aktualisiert")
    return cache


def demo_data(today):
    """Zufallsdaten zum Testen ohne Internet."""
    rng = np.random.default_rng(7)
    syms = [i["symbol"] for i in CONFIG["indices"]] + [s["symbol"] for s in CONFIG["dax"] + CONFIG["us"]] + watch_fetch_list()
    dates, d = [], today - dt.timedelta(days=460)
    while d <= today:
        if d.weekday() < 5:
            dates.append(d)
        d += dt.timedelta(days=1)
    hist, meta = {}, {}
    for s in syms:
        start = 25000 if s.startswith("^") else (float(rng.uniform(1.05, 9)) if s.endswith("=X") else float(rng.uniform(20, 400)))
        vol = float(rng.uniform(0.15, 0.55))
        r = rng.normal(0.0003, vol / math.sqrt(252), len(dates))
        hist[s] = list(zip(dates, start * np.exp(np.cumsum(r))))
        if not s.startswith("^") and not s.endswith("=X"):
            last = hist[s][-1][1]
            meta[s] = {"target": last * float(rng.uniform(0.85, 1.6)), "n_analysts": int(rng.integers(0, 30)),
                       "buy_share": float(rng.uniform(0.2, 1.0)), "updated": today.isoformat(),
                       "earnings": [(today + dt.timedelta(days=int(rng.integers(1, 40)))).isoformat()]}
    return hist, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--today", help="Datum für Tests, z. B. 2026-11-06")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()

    if a.demo:
        hist, meta = demo_data(today)
    else:
        symbols = [i["symbol"] for i in CONFIG["indices"]] + [s["symbol"] for s in CONFIG["dax"] + CONFIG["us"]]
        symbols += [s for s in watch_fetch_list() if s not in symbols]
        symbols += [s for s in sorted({FX[c] for c in map(currency_of, all_stock_symbols()) if c in FX}) if s not in symbols]
        hist = fetch_history(symbols)
        meta_file = DATA / "meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        stock_syms = [s["symbol"] for s in CONFIG["dax"] + CONFIG["us"]]
        meta = refresh_meta(stock_syms, today, meta)
        DATA.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    try:
        write_quotes(hist)
    except Exception as e:  # die Merkliste darf den Tageslauf nie stoppen
        log(f"Merkliste fehlgeschlagen: {e}")
    if not a.demo:
        try:
            write_long(today)
        except Exception as e:
            log(f"Langfristige Kurse fehlgeschlagen: {e}")
        try:
            div = json.loads(DIV_FILE.read_text(encoding="utf-8")) if DIV_FILE.exists() else {}
            div_syms = watch_symbols() + [x["symbol"] for x in CONFIG["dax"] + CONFIG["us"]]
            div = refresh_dividends(list(dict.fromkeys(div_syms)), today, div)
            DIV_FILE.write_text(json.dumps(div, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        except Exception as e:
            log(f"Dividenden fehlgeschlagen: {e}")
    build(hist, meta, today, force=a.force)


if __name__ == "__main__":
    sys.exit(main())
