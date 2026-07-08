#!/usr/bin/env python3
"""
Beispiel: HISinOne Noten API in ein eigenes Skript einbauen.

Zeigt, wie man den Notenspiegel abruft, das zurueckgegebene dict
weiterverarbeitet und die Status-/Modul-Kuerzel ausschreibt. Ausfuehren aus
dem Projektordner:

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

# Windows-Konsole auf UTF-8 (fuer Umlaute in der Legende)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# Vollstaendige Legende der Kuerzel (aus den "Erlaeuterungen" im Notenspiegel).
# Dient als Fallback - die API liefert unter daten["legende"] die tatsaechlich
# auf der Seite gefundenen Kuerzel ohnehin dynamisch mit.
STATUS_LEGENDE = {
    "AN": "angemeldet",
    "BE": "bestanden",
    "NB": "nicht bestanden",
    "EN": "endgültig nicht bestanden",
    "AB": "abgemeldet",
    "KR": "Krankmeldung",
    "GR": "genehmigter Rücktritt",
    "NGR": "nicht genehmigter Rücktritt",
    "NE": "nicht erschienen",
    "RT": "abgemeldet über Online-Selbstbedienung",
    "ME": "mündl. Ergänzungsprüfung",
    "VZ": "Verzicht auf Wiederholung",
    "TA": "Täuschungsversuch",
    "PV": "Konto/Modul nicht vollständig",
    "FAE": "fristgerechte Arbeitsabgabe erfolgt",
}
ART_LEGENDE = {
    "GE": "Modul",
    "PL": "Teilmodul",
    "MB": "Modul Bachelorarbeit",
    "MM": "Modul Masterarbeit",
    "AA": "Abschlussarbeit (Bachelor od. Master)",
}
SEMESTER_LEGENDE = {
    "SoSe": "Sommersemester",
    "WiSe": "Wintersemester",
}


def komma_float(wert: str) -> float:
    """'2,5' -> 2.5 ; leere Strings -> 0.0"""
    return float(wert.replace(",", ".")) if wert else 0.0


def bedeutung(code: str, daten: dict) -> str:
    """Schreibt ein Kuerzel aus: bevorzugt die vom Notenspiegel gelieferte
    daten['legende'], sonst die eingebauten Referenz-Tabellen oben."""
    leg = daten.get("legende", {})
    return (leg.get(code) or STATUS_LEGENDE.get(code)
            or ART_LEGENDE.get(code) or SEMESTER_LEGENDE.get(code) or code)


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

    # 3) Nur echte Pruefungsleistungen (Art == 'PL'), nach Status gruppiert -
    #    das Kuerzel wird jeweils ausgeschrieben.
    pl = [p for p in daten["pruefungen"] if p["art"] == "PL"]
    gruppen: dict[str, list] = {}
    for p in pl:
        gruppen.setdefault(p["status"], []).append(p)

    print(f"Prüfungen ({ART_LEGENDE['PL']}) nach Status:")
    for status in sorted(gruppen):
        items = gruppen[status]
        print(f"\n  {status} = {bedeutung(status, daten)}  ({len(items)})")
        for p in items:
            note = p["note"] or "-"
            print(f"    {p['text']:35} {note:>5}  Versuch {p['versuch']}  {p['semester']}")

    # 4) Eigener, credits-gewichteter Schnitt ueber die benoteten Bestandenen
    benotet = [p for p in gruppen.get("BE", []) if p["note"]]
    summe_cp = sum(komma_float(p["credits"]) for p in benotet)
    if summe_cp:
        schnitt = sum(komma_float(p["note"]) * komma_float(p["credits"])
                      for p in benotet) / summe_cp
        print("\n" + "-" * 60)
        print(f"Eigener gewichteter Schnitt: {schnitt:.2f}  ({summe_cp:.1f} CP benotet)")

    # 5) Legende: die im Notenspiegel gefundenen Kuerzel (aus dem JSON-Feld
    #    'legende'); faellt das mal leer aus, die eingebaute Referenz zeigen.
    print("\n" + "-" * 60)
    print("Legende (Kürzel im Notenspiegel):")
    legende = daten.get("legende") or {**STATUS_LEGENDE, **ART_LEGENDE, **SEMESTER_LEGENDE}
    for code in sorted(legende):
        print(f"  {code:4} = {legende[code]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
