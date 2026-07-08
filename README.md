# HISinOne Noten API

Ruft den **Notenspiegel** einer [HISinOne](https://www.his.de/)/QIS-Installation ab
und gibt ihn als sauberes **JSON** zurück – Stammdaten, Durchschnitt, Credits und
alle Prüfungen mit sämtlichen Tabellenspalten.

**Nur mit der Hochschule Hannover getestet** (`campusmanagement.hs-hannover.de`).
Da HISinOne/QIS an vielen Hochschulen im Einsatz ist, funktioniert es dort
**vielleicht** ebenfalls (ggf. nach Anpassung der URLs in der `.env`) – das ist
aber **nicht garantiert**.

> **Inoffiziell.** Dieses Projekt nutzt ausschließlich die normale Web-Oberfläche
> mit **deinen eigenen** Zugangsdaten – es gibt keine öffentliche API der
> Hochschule. Nutzung auf eigene Verantwortung, nur für den eigenen Account.

## Features

- Vollständiger Login inkl. der SSO-Übergabe vom modernen HISinOne ins Legacy-QIS
  (wo die Noten an der HS Hannover tatsächlich liegen).
- Ausgabe als strukturiertes JSON – als **CLI** oder als **Python-Bibliothek**.
- Zugangsdaten in einer `.env` (per `.gitignore` vom Repo ausgeschlossen).
- Nur eine Abhängigkeit: `requests`. HTML-Parsing komplett mit der Standardbibliothek.
- Robust gegen die zickige QIS-SSO durch automatische Wiederholversuche.

---

## Projektstatus & Mitwirken

> **Hinweis: Dieses Projekt ist KI-generiert.** Der Code wurde mit Hilfe eines
> KI-Assistenten erstellt. Er funktioniert im getesteten Umfang, kann aber
> **Fehler, unsaubere Stellen oder unbedachte Randfälle** enthalten. Wer damit
> weiterarbeitet, sollte den Code vor produktivem Einsatz selbst prüfen.

- **Getestet:** ausschließlich an der **Hochschule Hannover**. Andere
  HISinOne-Hochschulen können funktionieren, sind aber nicht getestet und
  **nicht garantiert**.
- **Wartung:** Ich werde an diesem Projekt **nicht aktiv weiterarbeiten** – es
  ist als „funktioniert bei mir"-Stand gedacht.
- **Forks willkommen!** Wer es für die eigene Hochschule anpassen oder
  erweitern möchte, darf das Projekt gerne **forken** und frei weiterentwickeln
  (die MIT-Lizenz erlaubt das ausdrücklich). Pull Requests werden vermutlich
  nicht zeitnah bearbeitet – ein eigener Fork ist daher der sicherste Weg.

---

## Sporadische Fehler & wie man sie abfängt

Das QIS-Portal liefert **gelegentlich eine leere bzw. Gast-Seite** zurück,
obwohl der Login korrekt war. Das Skript versucht es intern bereits mehrmals mit
wachsendem Abstand; klappt es trotzdem nicht, bricht es mit einem
`HISinOneError` ab (Meldung: *„… Bitte in ein paar Sekunden erneut starten."*).

Das ist **kein Fehler im Skript**, sondern ein sporadisches Verhalten des
Servers – aggressives Nachfassen hilft nicht, ein neuer Anlauf kurz später
dagegen fast immer.

**Auf der CLI:** einfach den Befehl noch einmal ausführen.

**Im eigenen Skript** fängst du es ab, indem du bei einem `HISinOneError` kurz
wartest und erneut abrufst – bei falschen Zugangsdaten (`HISinOneAuthError`)
dagegen sofort abbrichst, weil ein Retry da zwecklos ist:

```python
import time
from hisinone_noten import HISinOneClient, HISinOneError, HISinOneAuthError

def noten_mit_wiederholung(versuche=5, pause=10):
    client = HISinOneClient.from_env()
    for i in range(1, versuche + 1):
        try:
            return client.get_grades()
        except HISinOneAuthError:
            raise                      # falsches Passwort -> nicht wiederholen
        except HISinOneError as e:
            if i == versuche:
                raise                  # nach dem letzten Versuch aufgeben
            print(f"Versuch {i} fehlgeschlagen ({e}). Warte {pause}s ...")
            time.sleep(pause)

daten = noten_mit_wiederholung()
print(daten["zusammenfassung"])
```

So läuft dein Programm auch dann durch, wenn das Portal beim ersten Anlauf zickt.
Genau dieses Muster steckt auch im mitgelieferten
[`examples/beispiel.py`](examples/beispiel.py).

---

## Voraussetzungen

- **Python 3.8** oder neuer
- **pip** (für die eine Abhängigkeit `requests`)
- Ein gültiger Hochschul-Account (Benutzerkennung + Passwort)

Python-Version prüfen:

```bash
python --version
```

---

## Einrichtung (Schritt für Schritt)

**1. Projekt holen**

```bash
git clone https://github.com/Dirtez03/hisinone-noten-api.git
cd hisinone-noten-api
```

(Oder einfach die Datei `hisinone_noten.py` in dein Projekt kopieren.)

**2. Abhängigkeit installieren**

```bash
pip install -r requirements.txt
```

**3. Zugangsdaten hinterlegen**

Kopiere die Vorlage und trage deine Daten ein:

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Dann `.env` öffnen und ausfüllen:

```ini
HISINONE_USERNAME=deine-benutzerkennung
HISINONE_PASSWORD=dein-passwort
```

Die `.env` steht in `.gitignore` und wird **nie** mit hochgeladen.

**4. Testen**

```bash
python hisinone_noten.py
```

Wenn alles passt, erscheint dein Notenspiegel als JSON.

### Andere Hochschule / anderer Studiengang?

Die Standardwerte in der `.env` gelten für die HS Hannover. Zwei Dinge lassen
sich anpassen:

- **`HISINONE_BASE_URL` / `HISINONE_ICMS_URL`** – die HISinOne- bzw. QIS-Adresse
  deiner Hochschule.
- **`HISINONE_NODE_ID`** – der Knoten deines Studiengangs im Notenspiegel-Baum.
  Den findest du, indem du den Notenspiegel im Browser öffnest und in der URL
  den Parameter `nodeID=...` kopierst (URL-kodiert übernehmen). Standard ist
  `abschl=84` (Bachelor), `stgnr=1`.

---

## Benutzung als CLI

```bash
python hisinone_noten.py                 # JSON nach stdout
python hisinone_noten.py -o noten.json   # in Datei schreiben
python hisinone_noten.py --compact       # einzeiliges JSON
python hisinone_noten.py --env pfad/zu/.env   # andere .env verwenden
```

Beispiel: nur den Durchschnitt herausziehen (mit [`jq`](https://jqlang.github.io/jq/)):

```bash
python hisinone_noten.py | jq '.zusammenfassung'
```

---

## In eigene Skripte einbauen

Das Herzstück ist die Klasse `HISinOneClient`. `get_grades()` liefert ein ganz
normales Python-`dict` (dieselbe Struktur wie das JSON), das du frei
weiterverarbeiten kannst.

### 1. Schnellstart (Zugangsdaten aus `.env`)

```python
from hisinone_noten import HISinOneClient

daten = HISinOneClient.from_env().get_grades()

print(daten["student"]["name"])
print("Durchschnitt:", daten["zusammenfassung"]["durchschnitt"])

for p in daten["pruefungen"]:
    print(f"{p['text']:35} {p['note'] or '-':>4}  {p['status']}")
```

### 2. Zugangsdaten direkt übergeben (ohne `.env`)

Praktisch, wenn die Daten woanders herkommen (z. B. aus deiner eigenen Config
oder Umgebungsvariablen):

```python
from hisinone_noten import HISinOneClient

client = HISinOneClient(username="deine-kennung", password="dein-passwort")
daten = client.get_grades()
```

### 3. Fehler sauber behandeln

Alle erwartbaren Fehler (falsches Passwort, Server nicht erreichbar, Login-Kette
gescheitert) kommen als `HISinOneError`:

```python
from hisinone_noten import HISinOneClient, HISinOneError

try:
    daten = HISinOneClient.from_env().get_grades()
except HISinOneError as e:
    print("Abruf fehlgeschlagen:", e)
    # z. B. Benachrichtigung schicken, Retry planen, ...
    raise SystemExit(1)
```

Möchtest du **falsche Zugangsdaten** gesondert behandeln, gibt es dafür die
Unterklasse `HISinOneAuthError` (bricht sofort ab, wird nicht wiederholt):

```python
from hisinone_noten import HISinOneClient, HISinOneError, HISinOneAuthError

try:
    daten = HISinOneClient.from_env().get_grades()
except HISinOneAuthError:
    print("Benutzername oder Passwort stimmt nicht.")
except HISinOneError as e:
    print("Vorübergehendes Problem:", e)
```

### 4. Nur die bestandenen Prüfungen / eigene Auswertung

```python
daten = HISinOneClient.from_env().get_grades()

# nur echte Prüfungsleistungen (Art == "PL"), bestanden mit Note
bestanden = [
    p for p in daten["pruefungen"]
    if p["art"] == "PL" and p["status"] == "BE" and p["note"]
]

# Notendurchschnitt selbst über gewichtete Credits rechnen
def note(p): return float(p["note"].replace(",", "."))
def cp(p):   return float((p["credits"] or "0").replace(",", "."))

gewichtet = sum(note(p) * cp(p) for p in bestanden)
summe_cp  = sum(cp(p) for p in bestanden)
print("Eigener Schnitt:", round(gewichtet / summe_cp, 2) if summe_cp else "-")
```

### 5. Als JSON-String / in eine Datei / an eine Web-App

```python
import json
from hisinone_noten import HISinOneClient

daten = HISinOneClient.from_env().get_grades()

# JSON-String (z. B. als HTTP-Antwort in Flask/FastAPI zurückgeben)
text = json.dumps(daten, ensure_ascii=False, indent=2)

# in eine Datei
with open("noten.json", "w", encoding="utf-8") as f:
    f.write(text)
```

Ein komplettes, lauffähiges Beispiel liegt in
[`examples/beispiel.py`](examples/beispiel.py).

> **Tipp zur Performance:** Jeder `get_grades()`-Aufruf macht den kompletten
> Login neu. Wenn du die Daten mehrfach brauchst, ruf **einmal** ab und
> verarbeite das zurückgegebene `dict` weiter – nicht in einer Schleife pollen.

---

## JSON-Struktur (Beispiel, Werte anonymisiert)

```json
{
  "abgerufen_am": "2026-07-05T15:58:49+0200",
  "student": {
    "name": "Max Mustermann",
    "angestrebter_abschluss": "[84] Bachelor",
    "matrikelnummer": "1234567"
  },
  "studiengang": "[622] Elektrotechnik und Informationstechnik",
  "zusammenfassung": {
    "durchschnitt": "2,1",
    "credits": "15"
  },
  "pruefungen": [
    {
      "pruefungsnummer": "140701",
      "text": "Gleichstromtechnik",
      "art": "PL",
      "note": "3,0",
      "status": "BE",
      "vermerk": "",
      "credits": "5",
      "versuch": "1",
      "semester": "WiSe 25/26",
      "pruefungsdatum": "",
      "abgabe": ""
    }
  ],
  "konten": [
    {"nummer": "1000", "text": "1. Studienabschnitt", "durchschnitt": "2,1", "credits": "15", "semester": "Sommersemester 26"}
  ],
  "legende": {
    "BE": "bestanden",
    "NB": "nicht bestanden",
    "AN": "angemeldet",
    "GE": "Modul",
    "PL": "Teilmodul"
  }
}
```

| Feld | Bedeutung |
|------|-----------|
| `student` | Name, angestrebter Abschluss, Matrikelnummer |
| `studiengang` | Studiengang inkl. interner Nummer |
| `zusammenfassung` | Notendurchschnitt und bislang erreichte Credits |
| `pruefungen` | jede Zeile der Notentabelle mit **allen** Spalten (Prüfungsnummer, Text, Art, Note, Status, Vermerk, Credits, Versuch, Semester, Prüfungsdatum, Abgabe) |
| `konten` | Summen-/Konto-Zeilen (z. B. „1. Studienabschnitt") |
| `legende` | Erklärung aller Status- und Art-Kürzel |

**Hinweis:** Alle Werte sind **Strings genau wie auf der Seite** – Noten und
Credits im deutschen Format (`"2,1"`). Für Rechnungen `,` → `.` ersetzen und in
`float` wandeln (siehe Beispiel 4). Eine Prüfung kann mehrfach vorkommen
(z. B. `AN` = angemeldet und später der Versuch mit Note).

---

## Abkürzungen (Statuscodes & Modultypen)

Quelle: die „Erläuterungen" im HISinOne/QIS-Notenspiegel. Genau diese Kürzel
stehen in den Feldern `status` und `art` – und werden zusätzlich unter
`legende` direkt im JSON mitgeliefert.

**Prüfungsstatus (Feld `status`)**

| Code | Bedeutung |
|------|-----------|
| `AN` | angemeldet |
| `BE` | bestanden |
| `NB` | nicht bestanden |
| `EN` | endgültig nicht bestanden |
| `AB` | abgemeldet |
| `KR` | Krankmeldung |
| `GR` | genehmigter Rücktritt |
| `NGR` | nicht genehmigter Rücktritt |
| `NE` | nicht erschienen |
| `RT` | abgemeldet über Online-Selbstbedienung |
| `ME` | mündl. Ergänzungsprüfung |
| `VZ` | Verzicht auf Wiederholung |
| `TA` | Täuschungsversuch |
| `PV` | Konto/Modul nicht vollständig |
| `FAE` | fristgerechte Arbeitsabgabe erfolgt |

**Modultyp (Feld `art`)**

| Code | Bedeutung |
|------|-----------|
| `GE` | Modul |
| `PL` | Teilmodul |
| `MB` | Modul Bachelorarbeit |
| `MM` | Modul Masterarbeit |
| `AA` | Abschlussarbeit (Bachelor od. Master) |

**Semester**

| Code | Bedeutung |
|------|-----------|
| `SoSe` | Sommersemester |
| `WiSe` | Wintersemester |

---

## Wie es funktioniert

Moderne HISinOne-Installationen zeigen die Noten teils nicht mehr im neuen
Frontend, sondern nur im Legacy-QIS. Der Ablauf:

1. **Login** im modernen HISinOne (`asdf`/`fdsa` + `ajax-token`).
2. **SSO-Brücke** `rds?state=redirect&sso=qis` liefert einen Einmal-Token.
3. Token **sauber** im Legacy-QIS einlösen (ohne den `re=`-Anhang, der sonst per
   doppeltem `type=8` den Token-Login aushebelt).
4. Über das POS-Menü die `asi`-Session-Id einsammeln.
5. Notenspiegel-Baum initialisieren und die Liste abrufen (Latin-1).

Details stehen im Docstring von [`hisinone_noten.py`](hisinone_noten.py).

---

## Sicherheit

- Die echte `.env` mit deinen Zugangsdaten wird durch `.gitignore` vom Repository
  ausgeschlossen. **Committe sie niemals.**
- Mit Benutzername + Passwort hängt dein kompletter Hochschul-Account dran – geh
  entsprechend sorgsam damit um.

## Lizenz

MIT – siehe [LICENSE](LICENSE).
