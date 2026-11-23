"""Eilmeldungen für den Börsen-Markt -> docs/data/alerts.json (+ optional Handy-Push über ntfy.sh).

Läuft direkt nach scripts/live.py (live.yml, alle 30 Min zu Handelszeiten). Gemeldet werden:
  * Indizes mit Tagesbewegung >= INDEX_PCT, Aktien der Seite mit >= STOCK_PCT
  * Schlagzeilen (Google News RSS) zu Notenbanken, Zinsentscheiden, Crash usw. der letzten 3 Stunden
Schon gemeldetes wird nicht erneut gemeldet: der letzte Stand wird von der Seite selbst geladen.
"""
import datetime as dt
import email.utils
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update as u  # noqa: E402

SITE = "https://mulmigerotter.github.io/boersen-briefing/"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "bb-5aad97eea640")  # Thema für die ntfy-App (Handy-Push)
INDEX_PCT, STOCK_PCT = 2.0, 8.0
KEEP_DAYS, MAX_ITEMS, MAX_NEWS_PER_RUN = 7, 40, 3
QUERIES = ["EZB Zinsentscheid", "Fed Zinsentscheid", "Börse Crash Kurssturz", "DAX Rekord Absturz",
           "Notenbank überraschend Zinsen", "Wall Street Ausverkauf", "Handelsstopp Börse"]
# Kategorien der Schlagzeilen: zinsen = Notenbanken/Zinsen, crash = Kurseinbrüche/Krisen, rekord = Rekorde/Zölle
CATS = {
    "zinsen": re.compile(r"zinsentscheid|leitzins|zinssenk|zinserh|notenbank|\bezb\b|\bfed\b", re.I),
    "crash": re.compile(r"crash|kurssturz|ausverkauf|börsenbeben|handelsstopp|rezession|absturz|einbruch", re.I),
    "rekord": re.compile(r"rekordhoch|zollstreit", re.I),
}
NOW = dt.datetime.now(dt.timezone.utc)


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "boersen-briefing/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_old():
    try:
        return json.loads(get(SITE + "data/alerts.json?t=" + str(int(NOW.timestamp()))))
    except Exception:
        p = u.DATA / "alerts.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"items": []}


def price_alerts(live):
    out, names = [], {}
    try:
        names = json.loads((u.DATA / "stocks.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    idx = {i["symbol"]: i.get("name", i["symbol"]) for i in u.CONFIG["indices"]}
    for sym, v in live.get("q", {}).items():
        try:
            last, prev, day = v
            pct = (last / prev - 1) * 100
        except Exception:
            continue
        if sym in idx and abs(pct) >= INDEX_PCT:
            kind, name, lim = "index", idx[sym], INDEX_PCT
        elif sym not in idx and abs(pct) >= STOCK_PCT:
            nm = names.get(sym)
            kind, name, lim = "aktie", (nm["name"] if isinstance(nm, dict) and nm.get("name") else sym), STOCK_PCT
        else:
            continue
        up = pct > 0
        out.append({"id": f"{kind}:{sym}:{day}:{'up' if up else 'down'}", "kind": kind, "cat": kind, "ts": iso(NOW),
                    "title": f"{'📈' if up else '📉'} {name}: {pct:+.1f} % am {day[8:10]}.{day[5:7]}.",
                    "sym": sym if kind == "aktie" else ""})
    return out


def news_alerts(seen):
    items = []
    for q in QUERIES:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": q + " when:3h", "hl": "de", "gl": "DE", "ceid": "DE:de"})
        try:
            root = ET.fromstring(get(url))
        except Exception:
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            try:
                ts = email.utils.parsedate_to_datetime(it.findtext("pubDate"))
            except Exception:
                continue
            cat = next((c for c, rx in CATS.items() if rx.search(title)), None)
            if (NOW - ts).total_seconds() > 3 * 3600 or not cat:
                continue
            nid = "news:" + hashlib.sha1(re.sub(r"\W+", "", title.lower())[:60].encode()).hexdigest()[:12]
            if nid in seen or any(x["id"] == nid for x in items):
                continue
            items.append({"id": nid, "kind": "news", "cat": cat, "ts": iso(ts), "title": "📰 " + title, "url": link})
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:MAX_NEWS_PER_RUN]


def push(it):
    if not NTFY_TOPIC:
        return
    try:
        # pro Kategorie ein eigenes Thema: in der ntfy-App nur die gewünschten abonnieren
        req = urllib.request.Request(f"https://ntfy.sh/{NTFY_TOPIC}-{it.get('cat') or it['kind']}", data=it["title"].encode("utf-8"),
                                     headers={"Title": "Börsen-Meldung".encode("utf-8").decode("latin-1"),
                                              "Click": it.get("url") or SITE}, method="POST")
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print("ntfy-Fehler:", e)


def main():
    live = json.loads((u.DATA / "live.json").read_text(encoding="utf-8"))
    old = load_old()
    cutoff = iso(NOW - dt.timedelta(days=KEEP_DAYS))
    kept = [x for x in old.get("items", []) if x.get("ts", "") >= cutoff]
    seen = {x["id"] for x in kept}
    new = [a for a in price_alerts(live) if a["id"] not in seen] + news_alerts(seen)
    for it in new:
        push(it)
    items = sorted(new + kept, key=lambda x: x["ts"], reverse=True)[:MAX_ITEMS]
    out = {"updated": iso(NOW), "items": items}
    (u.DATA / "alerts.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"alerts.json: {len(new)} neu, {len(items)} gesamt")


if __name__ == "__main__":
    main()
