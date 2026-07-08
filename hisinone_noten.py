#!/usr/bin/env python3
"""
HISinOne Noten API
==================

Ruft den Notenspiegel einer HISinOne/QIS-Installation (getestet mit der
Hochschule Hannover) ab und gibt ihn als strukturiertes JSON zurueck --
Stammdaten, Zusammenfassung (Durchschnitt / Credits) und alle Pruefungen mit
saemtlichen Tabellenspalten.

Es wird ausschliesslich die offizielle Web-Oberflaeche verwendet (keine private
API), mit den eigenen Zugangsdaten. Diese liegen in einer ``.env`` (siehe
``.env.example``) und gehoeren NICHT ins Repository.

Hintergrund der Login-Kette
---------------------------
Moderne HISinOne-Installationen zeigen die Noten teils gar nicht mehr im neuen
Frontend, sondern nur im Legacy-QIS (hier ``icms``). Der Weg dorthin:

1. Login im modernen HISinOne (``campusmanagement``): Startseite holen
   (liefert ``ajax-token`` + Session-Cookie), dann POST auf
   ``rds?state=user&type=1&category=auth.login`` mit ``asdf``/``fdsa``.
2. SSO-Bruecke ``rds?state=redirect&sso=qis&myre=...`` -- der ``Location``-
   Header enthaelt einen Einmal-Token fuer das Legacy-QIS.
3. Token *sauber* einloesen: ``icms/rds?state=user&type=1&token=<TOKEN>``.
   Wichtig: nur den Token uebernehmen, nicht den ``re=``-Anhang aus dem
   Location-Header (der enthaelt ein doppeltes ``type=8`` und wuerde den
   Token-Login aushebeln).
4. Ueber das POS-Menue die ``asi`` (Anwendungs-Session-Id) einsammeln.
5. Notenspiegel-Baum initialisieren (``tree.vm``) und die Liste (``list.vm``)
   abrufen. Die Seite ist UTF-8 kodiert (wichtig fuer Umlaute in der Legende).

Benutzung
---------
    python hisinone_noten.py                 # JSON nach stdout
    python hisinone_noten.py -o noten.json   # in Datei
    python hisinone_noten.py --compact       # einzeilig

Als Bibliothek:
    from hisinone_noten import HISinOneClient
    daten = HISinOneClient.from_env().get_grades()
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import html as htmlmod
from pathlib import Path

import requests

# Spalten-Codes fuer "Art" (siehe Legende im Notenspiegel):
#   GE = Modul, PL = Teilmodul, MB/MM = Modul Bachelor-/Masterarbeit,
#   AA = Abschlussarbeit. Nur solche Zeilen sind einzelne Pruefungen.
ART_CODES = {"GE", "PL", "MB", "MM", "AA"}

DEFAULT_BASE_URL = "https://campusmanagement.hs-hannover.de"
DEFAULT_ICMS_URL = "https://icms.hs-hannover.de/qisserver"
DEFAULT_NODE_ID = "auswahlBaum%7Cabschluss%3Aabschl%3D84%2Cstgnr%3D1"
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")


# ---------------------------------------------------------------------------
# .env laden (ohne Zusatzabhaengigkeit)
# ---------------------------------------------------------------------------

def load_env(path: str | os.PathLike | None = None) -> None:
    """Liest eine einfache ``KEY=VALUE``-.env in ``os.environ`` (setdefault).
    Kommentare (#) und Leerzeilen werden ignoriert, Anfuehrungszeichen
    entfernt. Fehlt die Datei, passiert nichts."""
    p = Path(path) if path else Path(__file__).with_name(".env")
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)


class HISinOneError(RuntimeError):
    """Fehler beim Login oder Abruf des Notenspiegels."""


class HISinOneAuthError(HISinOneError):
    """Zugangsdaten falsch/abgelaufen. Wird NICHT wiederholt (Retry sinnlos)."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class HISinOneClient:
    def __init__(self, username: str, password: str,
                 base_url: str = DEFAULT_BASE_URL,
                 icms_url: str = DEFAULT_ICMS_URL,
                 node_id: str = DEFAULT_NODE_ID,
                 user_agent: str = DEFAULT_UA,
                 timeout: int = 25):
        if not username or not password:
            raise HISinOneError("Benutzername/Passwort fehlen (.env pruefen).")
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.qis_base = self.base_url + "/qisserver"
        self.icms_url = icms_url.rstrip("/")
        self.node_id = node_id
        self.user_agent = user_agent
        self.timeout = timeout

    @classmethod
    def from_env(cls, env_path: str | os.PathLike | None = None) -> "HISinOneClient":
        load_env(env_path)
        return cls(
            username=os.environ.get("HISINONE_USERNAME", ""),
            password=os.environ.get("HISINONE_PASSWORD", ""),
            base_url=os.environ.get("HISINONE_BASE_URL", DEFAULT_BASE_URL),
            icms_url=os.environ.get("HISINONE_ICMS_URL", DEFAULT_ICMS_URL),
            node_id=os.environ.get("HISINONE_NODE_ID", DEFAULT_NODE_ID),
            user_agent=os.environ.get("HISINONE_USER_AGENT", DEFAULT_UA),
        )

    # -- interne Helfer -----------------------------------------------------

    @staticmethod
    def _find_ajax_token(html: str) -> str:
        for m in re.finditer(r"<input\b[^>]*>", html):
            if "ajax-token" in m.group(0):
                v = re.search(r'value="([^"]*)"', m.group(0))
                if v:
                    return v.group(1)
        return ""

    def _new_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        return s

    def _fetch_once(self) -> str:
        s = self._new_session()

        # 1) Login (modernes HISinOne) - nur EINMAL. Falsche Zugangsdaten ->
        # HISinOneAuthError (kein Retry).
        start = s.get(f"{self.qis_base}/pages/cs/sys/portal/hisinoneStartPage.faces",
                      timeout=self.timeout)
        login = s.post(
            f"{self.qis_base}/rds?state=user&type=1&category=auth.login",
            data={"userInfo": "", "ajax-token": self._find_ajax_token(start.text),
                  "asdf": self.username, "fdsa": self.password, "submit": ""},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Origin": self.base_url,
                     "Referer": f"{self.qis_base}/pages/cs/sys/portal/hisinoneStartPage.faces"},
            timeout=self.timeout)
        if "abmelden" not in login.text.lower():
            raise HISinOneAuthError("Login fehlgeschlagen (Zugangsdaten falsch/abgelaufen?).")

        # 2) SSO-Handoff ins Legacy-QIS + Notenspiegel. Nur EIN Versuch pro
        # Login: schnelles Nachfassen (mehrere SSO-Handoffs) scheint die
        # serverseitige QIS-Session eher zu verwirren als zu helfen. Die
        # Wiederholung uebernimmt die aeussere Ebene mit frischer Session.
        return self._qis_notenspiegel(s)

    def _qis_notenspiegel(self, s: requests.Session) -> str:
        """SSO-Handoff ins Legacy-QIS + Notenspiegel holen. Setzt einen bereits
        im modernen HISinOne eingeloggten Session-Cookie voraus."""
        # SSO-Bruecke -> frischer Einmal-Token aus dem Location-Header
        br = s.get(f"{self.qis_base}/rds?state=redirect&sso=qis"
                   "&myre=state%3Duser%26type%3D8%26topitem%3Dfunctions%26breadCrumbSource%3Dportal",
                   timeout=self.timeout, allow_redirects=False)
        tok = re.search(r"token=([^&]+)", br.headers.get("Location", ""))
        if not tok:
            raise HISinOneError(f"SSO-Bruecke lieferte keinen Token (HTTP {br.status_code}).")

        # Token SAUBER einloesen (ohne re=-Ballast)
        s.get(f"{self.icms_url}/rds?state=user&type=1&token={tok.group(1)}",
              timeout=self.timeout, headers={"Referer": f"{self.base_url}/"})

        # Portal + POS-Menue -> asi
        r8 = s.get(f"{self.icms_url}/rds?state=user&type=8&topitem=functions"
                   "&breadCrumbSource=portal&chco=y", timeout=self.timeout,
                   headers={"Referer": f"{self.base_url}/"})
        rb = s.get(f"{self.icms_url}/rds?state=change&type=1&moduleParameter=studyPOSMenu"
                   "&nextdir=change&next=menu.vm&subdir=applications&xml=menu&purge=y"
                   "&navigationPosition=functions%2CstudyPOSMenu&breadcrumb=studyPOSMenu"
                   "&topitem=functions&subitem=studyPOSMenu", timeout=self.timeout,
                   headers={"Referer": f"{self.icms_url}/rds?state=user&type=8"
                            "&topitem=functions&breadCrumbSource=portal&chco=y"})
        menu = r8.text + rb.text
        m = (re.search(r"state=notenspiegelStudent[^\"']*asi=([0-9A-Za-z]{6,})", menu)
             or re.search(r"asi=([0-9A-Za-z]{6,})", menu))
        if not m:
            raise HISinOneError("Keine asi nach SSO-Login (Token-Einloesung fehlgeschlagen?).")
        asi = m.group(1)

        # Baum initialisieren (sonst liefert die Liste leer) + Liste holen
        s.get(f"{self.icms_url}/rds?state=notenspiegelStudent&next=tree.vm"
              f"&nextdir=qispos/notenspiegel/student&menuid=notenspiegelStudent"
              f"&breadcrumb=notenspiegel&breadCrumbSource=menu&asi={asi}",
              timeout=self.timeout,
              headers={"Referer": f"{self.icms_url}/rds?state=user&type=8"
                       "&topitem=functions&breadCrumbSource=portal&chco=y"})
        lst = s.get(f"{self.icms_url}/rds?state=notenspiegelStudent&next=list.vm"
                    f"&nextdir=qispos/notenspiegel/student&createInfos=Y&struct=auswahlBaum"
                    f"&nodeID={self.node_id}&expand=0&asi={asi}", timeout=self.timeout,
                    headers={"Referer": f"{self.icms_url}/rds?state=notenspiegelStudent"
                             f"&next=tree.vm&asi={asi}"})
        lst.encoding = "utf-8"  # QIS-Seite ist UTF-8 (Umlaute in der Legende)
        low = lst.text.lower()
        if "notenspiegel" in low or "<table" in low:
            return lst.text
        raise HISinOneError("Notenspiegel-Seite unerwartet leer/ungueltig.")

    def fetch_notenspiegel_html(self, attempts: int = 3) -> str:
        """Bis zu `attempts` Versuche, jeder mit frischer Session + Login und
        wachsender Pause dazwischen. Der QIS-Notenspiegel ist sporadisch nicht
        erreichbar (liefert dann eine leere/Gast-Seite); schnelles Nachfassen
        hilft dann wenig, mit etwas Abstand meist schon."""
        last: Exception | None = None
        for i in range(1, attempts + 1):
            try:
                return self._fetch_once()
            except HISinOneAuthError:
                raise  # falsche Zugangsdaten -> sofort abbrechen, kein Retry
            except Exception as e:  # noqa: BLE001 - bewusst breit fuer Retry
                last = e
                if i < attempts:
                    time.sleep(3 * i)  # 3s, 6s, ... Abstand statt Haemmern
        raise HISinOneError(
            f"Notenspiegel konnte nach {attempts} Versuchen nicht geladen werden "
            f"({last}). Das QIS-Portal hat gerade eine leere Seite geliefert - "
            f"das passiert sporadisch. Bitte in ein paar Sekunden erneut starten.")

    def get_grades(self, attempts: int = 3) -> dict:
        """Ruft den Notenspiegel ab und gibt ihn als strukturiertes dict zurueck."""
        html = self.fetch_notenspiegel_html(attempts=attempts)
        return parse_notenspiegel(html)


# ---------------------------------------------------------------------------
# HTML-Parsing (nur Standardbibliothek)
# ---------------------------------------------------------------------------

def _row_cells(row_html: str) -> list[str]:
    out = []
    for m in re.finditer(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, re.S | re.I):
        txt = htmlmod.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
        out.append(re.sub(r"\s+", " ", txt).strip())
    return out


def _tables(html: str) -> list[str]:
    return re.findall(r"(?is)<table\b.*?</table>", html)


def _rows(table_html: str) -> list[list[str]]:
    return [_row_cells(r) for r in re.findall(r"(?is)<tr\b.*?</tr>", table_html)]


def parse_notenspiegel(html: str) -> dict:
    """Zerlegt das Notenspiegel-HTML in ein strukturiertes dict."""
    student: dict[str, str] = {}
    studiengang = ""
    durchschnitt = ""
    credits = ""
    pruefungen: list[dict] = []
    _seen_pruefungen: set[tuple] = set()  # exakte Doubletten filtern
    konten: list[dict] = []
    legende: dict[str, str] = {}

    for table in _tables(html):
        rows = _rows(table)
        flat = " ".join(c for row in rows for c in row)

        # Stammdaten-Tabelle (Key/Value, enthaelt "Matrikelnummer")
        if "Matrikelnummer" in flat and all(len(r) <= 2 for r in rows if r):
            for r in rows:
                if len(r) == 2:
                    student[_norm_label(r[0])] = r[1]
            continue

        # Legende (Erlaeuterungen der Codes)
        if "Erl" in flat and "AN - angemeldet" in flat:
            for r in rows:
                for cell in r:
                    mm = re.match(r"^([A-Z]{2,4}|SoSe|WiSe)\s*-\s*(.+)$", cell)
                    if mm:
                        legende[mm.group(1)] = mm.group(2).strip()
            continue

        # Noten-Tabelle
        if re.search(r"\d,\d", flat) or " PL " in f" {flat} ":
            for r in rows:
                if len(r) == 1:
                    if "Studiengang:" in r[0]:
                        sm = re.search(r"Studiengang:\s*(.+)$", r[0])
                        studiengang = (sm.group(1) if sm else r[0]).strip()
                    continue
                if len(r) < 9:
                    continue
                nr = r[0]
                art = r[2] if len(r) > 2 else ""
                if not re.fullmatch(r"\d+", nr or ""):
                    continue  # Kopfzeile o. ae.
                if art in ART_CODES:
                    eintrag = {
                        "pruefungsnummer": r[0],
                        "text": r[1],
                        "art": r[2],
                        "note": r[3],
                        "status": r[4],
                        "vermerk": r[5],
                        "credits": r[6],
                        "versuch": r[7],
                        "semester": r[8],
                        "pruefungsdatum": r[9] if len(r) > 9 else "",
                        "abgabe": r[10] if len(r) > 10 else "",
                    }
                    # Der Notenspiegel listet PL-Zeilen in zwei Bloecken
                    # (Studienabschnitt-Zusammenfassung + Detailplan). Exakte
                    # Doubletten ueberspringen, echte Mehrfachversuche behalten.
                    sig = tuple(eintrag.values())
                    if sig in _seen_pruefungen:
                        continue
                    _seen_pruefungen.add(sig)
                    pruefungen.append(eintrag)
                else:
                    # Konto-/Summenzeile (z. B. "1. Studienabschnitt", "Abschluss ..")
                    # Feste Spalten: [2]=Durchschnitt, [5]=Credits, [6]=Semester
                    grade = r[2] if re.fullmatch(r"\d,\d", r[2]) else ""
                    cp = r[5] if len(r) > 5 else ""
                    konto = {"nummer": nr, "text": r[1], "durchschnitt": grade,
                             "credits": cp, "semester": r[6] if len(r) > 6 else ""}
                    konten.append(konto)
                    if "studienabschnitt" in r[1].lower() and grade and not durchschnitt:
                        durchschnitt = grade
                        credits = cp

    # Fallback: erstes Konto mit Durchschnitt
    if not durchschnitt:
        for k in konten:
            if k["durchschnitt"]:
                durchschnitt, credits = k["durchschnitt"], k["credits"]
                break

    return {
        "abgerufen_am": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "student": {
            "name": student.get("name", ""),
            "angestrebter_abschluss": student.get("angestrebter_abschluss", ""),
            "matrikelnummer": student.get("matrikelnummer", ""),
        },
        "studiengang": studiengang,
        "zusammenfassung": {
            "durchschnitt": durchschnitt,
            "credits": credits,
        },
        "pruefungen": pruefungen,
        "konten": konten,
        "legende": legende,
    }


def _norm_label(label: str) -> str:
    """Macht aus einem Tabellen-Label einen schlanken JSON-Key."""
    lab = label.lower()
    lab = (lab.replace("(angestrebter) abschluss", "angestrebter_abschluss")
              .replace("geburtsdatum und -ort", "geburtsdatum"))
    lab = re.sub(r"[^a-z0-9]+", "_", lab).strip("_")
    return lab


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HISinOne Notenspiegel als JSON abrufen.")
    ap.add_argument("-o", "--output", help="JSON in diese Datei schreiben statt stdout")
    ap.add_argument("--compact", action="store_true", help="Kompaktes (einzeiliges) JSON")
    ap.add_argument("--env", help="Pfad zur .env (Standard: neben dem Skript)")
    ap.add_argument("--attempts", type=int, default=3, help="Abruf-Versuche (Standard 3)")
    args = ap.parse_args(argv)

    try:
        client = HISinOneClient.from_env(args.env)
        data = client.get_grades(attempts=args.attempts)
    except HISinOneError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1

    indent = None if args.compact else 2
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"{len(data['pruefungen'])} Pruefungen -> {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
