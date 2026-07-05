#!/usr/bin/env python3
"""
Beispiel: HISinOne Noten API in ein eigenes Skript einbauen.

Zeigt, wie man den Notenspiegel abruft und das zurueckgegebene dict
weiterverarbeitet. Ausfuehren aus dem Projektordner:

    python examples/beispiel.py

Die Zugangsdaten werden aus der .env im Projekt-Hauptordner gelesen.
"""

import sys
import time
from pathlib import Path

# Damit "import hisinone_noten" funktioniert, wenn das Beispiel aus dem
# examples/-Unterordner laeuft: den Projekt-Hauptordner auf den Suchpfad legen.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hisinone_noten import (  # noqa: E402
    HISinOneClient, HISinOneError, HISinOneAuthError)


def komma_float(wert: str) -> float:
    """'2,5' -> 2.5 ; leere Strings -> 0.0"""
    return float(wert.replace(",", ".")) if wert else 0.0


def noten_mit_wiederholung(versuche: int = 5, pause: int = 10) -> dict:
    """Ruft den Notenspiegel ab und faengt die sporadische "leere Seite" des
    QIS-Portals ab: bei einem HISinOneError kurz warten und erneut versuchen.
    Falsche Zugangsdaten (HISinOneAuthError) brechen sofort ab - da hilft kein
    Retry."""
    client = HISinOneClient.from_env()
    for i in range(1, versuche + 1):
        try:
            return client.get_grades()
        except HISinOneAuthError:
            raise
        except HISinOneError as e:
            if i == versuche:
                raise
            print(f"Versuch {i} fehlgeschlagen ({e}).", file=sys.stderr)
            print(f"Warte {pause}s und versuche es erneut ...", file=sys.stderr)
            time.sleep(pause)


def main() -> int:
    # 1) Abrufen (Zugangsdaten aus .env), mit automatischer Wiederholung bei
    #    der sporadischen "leere Seite"-Zicke des QIS-Portals.
    try:
        daten = noten_mit_wiederholung()
    except HISinOneAuthError:
        print("Benutzername oder Passwort stimmt nicht.", file=sys.stderr)
        return 1
    except HISinOneError as e:
        print("Abruf endgueltig fehlgeschlagen:", e, file=sys.stderr)
        return 1

    # 2) Stammdaten + Zusammenfassung
    s = daten["student"]
    z = daten["zusammenfassung"]
    print(f"Student:      {s['name']} (Matrikel {s['matrikelnummer']})")
    print(f"Studiengang:  {daten['studiengang']}")
    print(f"Durchschnitt: {z['durchschnitt']}  |  Credits: {z['credits']}")
    print("-" * 60)

    # 3) Nur echte Pruefungsleistungen (Art == 'PL')
    pl = [p for p in daten["pruefungen"] if p["art"] == "PL"]

    bestanden = [p for p in pl if p["status"] == "BE"]
    nicht_best = [p for p in pl if p["status"] == "NB"]
    offen = [p for p in pl if p["status"] == "AN"]

    print(f"Bestanden:        {len(bestanden)}")
    for p in bestanden:
        print(f"  + {p['text']:35} {p['note'] or '(o. Note)':>9}  {p['semester']}")

    print(f"Nicht bestanden:  {len(nicht_best)}")
    for p in nicht_best:
        print(f"  - {p['text']:35} {p['note']:>9}  Versuch {p['versuch']}")

    print(f"Angemeldet/offen: {len(offen)}")
    for p in offen:
        print(f"  ? {p['text']:35} {'':>9}  {p['semester']}")

    # 4) Eigener, credits-gewichteter Schnitt ueber die benoteten Bestandenen
    benotet = [p for p in bestanden if p["note"]]
    summe_cp = sum(komma_float(p["credits"]) for p in benotet)
    if summe_cp:
        schnitt = sum(komma_float(p["note"]) * komma_float(p["credits"])
                      for p in benotet) / summe_cp
        print("-" * 60)
        print(f"Eigener gewichteter Schnitt: {schnitt:.2f}  ({summe_cp:.1f} CP benotet)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
