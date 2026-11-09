# Börsen-Briefing

Eine Webseite, die jeden Handelstag automatisch neu gerechnet wird – ohne Claude und ohne Anmeldung. Jeder mit dem Link kann sie öffnen und auf dem Handy wie eine App zum Home-Bildschirm hinzufügen.

**Was drinsteht:** DAX, Dow Jones, S&P 500 und Nasdaq, die stärksten und schwächsten DAX-Werte, anstehende Quartalszahlen und der **Rechner-Top-5**: Alle 40 DAX-Werte plus 8 große US-Tech-Aktien bekommen Punkte (max. 100). Für die fünf besten werden je 10.000 zufällige Kursverläufe über 20 Handelstage simuliert.

## So läuft es

- GitHub startet Mo–Fr um 22:35 Uhr (Winterzeit) das Programm `scripts/update.py`.
- Es lädt Kurse und Analystendaten von Yahoo Finance, rechnet Punkte und Simulation und speichert alles in `docs/data/`.
- Danach wird die Webseite aus dem Ordner `docs/` neu veröffentlicht.
- An Börsenfeiertagen gibt es keinen neuen Tag, dann passiert nichts.

## Punkte im Rechner (max. 100)

| Teil | Punkte | Was zählt |
|---|---|---|
| Kurspotenzial | 30 | Abstand zum Ø-Kursziel der Analysten (ab +50 % volle Punkte) |
| Analysten | 20 | Anteil der Kaufempfehlungen (ab 100 % volle Punkte, unter 50 % keine) |
| Tag | 10 | Tagesveränderung (−5 % = 0, +5 % = 10) |
| Trend | 15 | Kurs über der 200-Tage-Linie |
| Termin | 15 | Quartalszahlen in den nächsten 7 Handelstagen |
| Momentum | 10 | Entwicklung der letzten 20 Handelstage (−10 % = 0, +10 % = 10) |

Ausgeschlossen werden Aktien mit zu wenig Analystendaten, ohne aktuellen Kurs oder mit einem Tagesverlust von 10 % oder mehr.

**Simulation:** Tagesrenditen mit der Schwankung der letzten 250 Handelstage und einem Trend in Richtung Ø-Kursziel (höchstens ±50 % pro Jahr). Sie zeigt eine Spanne möglicher Kurse, keine sichere Vorhersage.

## Selbst anpassen

- **Aktien ändern:** `config.json` bearbeiten (Yahoo-Kürzel, z. B. `SAP.DE`, `NVDA`).
- **Sofort neu rechnen:** Reiter **Actions** → **Börsen-Briefing aktualisieren** → **Run workflow**.
- **Uhrzeit ändern:** in `.github/workflows/update.yml` die Zeile `cron` (Zeit in UTC).

## Zugang, Bereiche und Rechner

- Die Seite öffnet sich erst nach Eingabe des Zugangscodes und bleibt danach 15 Minuten offen. Der Reiter **🔒 Gesperrter Bereich** braucht zusätzlich einen PIN (ebenfalls 15 Minuten).
- **Alle Aktien:** alle Werte der Seite mit aktuellem Kurs, Dividende, Risiko (Schwankung) und Branche, sortier- und filterbar, mit Favoriten (gespeichert im Browser).
- **Rechner:** Dividenden- und Sparrechner mit Kurve, „Meine Aktien“ mit Prognose (Monte Carlo) und „Was wäre, wenn“ mit echten Monatskursen seit 2000 (`long.json`).
- **Aktuelle Kurse:** `.github/workflows/live.yml` holt Mo–Fr alle 30 Minuten verzögerte Kurse von Yahoo nach `docs/data/live.json` und veröffentlicht die Seite neu (die Datei wird nicht ins Repository geschrieben).
- Die Heft-Inhalte liegen nur verschlüsselt in `docs/data/hefte.enc.json` (Schlüssel aus Zugangscode und PIN). Kurse, Dividenden und das Briefing sind öffentliche Marktdaten und liegen unverschlüsselt im Repository.
- Neue Ausgabe einpflegen: `python scripts/lock.py inhalt.json --pin "<CODE>|<PIN>"`; der Klartext gehört nicht ins Repository. Neue Kürzel zusätzlich in `docs/data/stocks.json` (Name, Branche) eintragen.

## Falls es mal nicht läuft

- GitHub schaltet zeitgesteuerte Abläufe ab, wenn ein öffentliches Repository 60 Tage lang ruht. Dann im Reiter **Actions** den Ablauf wieder einschalten.
- Yahoo begrenzt manchmal die Abfragen. Dann fehlen einzelne Analystendaten, das Programm nimmt die zuletzt bekannten.

Keine Anlageberatung. Daten können fehlen, verspätet oder fehlerhaft sein.
