# ------------------------------------------------------------
# vp_10e_plan.py
# ------------------------------------------------------------
#!/usr/bin/env python3
"""Hilfs-Modul zum Laden und Vorfiltern des Vertretungsplans."""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import List
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv   #  NEU

__all__ = [
    "lade_plan",
    "parse_xml",
    "filtered_xml",
    "mine",  # Alias auf keep()
]

# .env laden (wird beim Bot-Start schon getan, aber hier zur
# Stand-Alone-Nutzung noch einmal, falls noch nicht geschehen)
load_dotenv()

# ------------------------------------------------------------------
# ▸ Zugangsdaten **ausschließlich** aus der .env-Datei lesen
#    (keine Fallback-Defaults mehr!)
# ------------------------------------------------------------------
USERNAME: str | None   = os.getenv("VP_USER")
PASSWORD: str | None   = os.getenv("VP_PASS")
BASE_URL: str | None   = os.getenv("VP_BASE_URL")

# Sofort meckern, falls etwas fehlt
if not (USERNAME and PASSWORD and BASE_URL):
    raise RuntimeError(
        "Bitte VP_USER, VP_PASS und VP_BASE_URL in der .env Datei setzen."
    )

#BASE_URL = "http://localhost:8765"


# Eigene Kurse (FACH, LEHRER)
MY_COURSES: set[tuple[str, str]] = {
    ("GEO1", "MÖW"),
    ("ETH3", "MADA"),
    ("INF1", "BOSSE"),
    ("KUN2", "KUGJ"),
    ("KUN4", "RAUE"),
    ("RUS1", "MÖW"),
    ("WIL1", "WETZ"),
    ("BIO", "GRUSS"),
    ("CHE", "GRUSS"),
    ("DEU", "PETH"),
    ("ENG", "SKAL"),
    ("MAT", "FELD"),
    ("SPO", "SCHJ"),
    ("GES", "NEU"),
    ("PHY", "VOGEL"),
}

MY_KURSE: set[str] = {k for k, _ in MY_COURSES}
MY_LEHRER: set[str] = {l for _, l in MY_COURSES}
SUBJECTS:  set[str] = {f for f, _ in MY_COURSES}

# Nur Kurskürzel für die Info-Suche verwenden. Dadurch werden Einträge wie
# "KUN5 RAUE" nicht versehentlich berücksichtigt, nur weil der Lehrername
# vorkommt.
INFO_RE = re.compile("|".join(re.escape(x) for x in MY_KURSE), re.IGNORECASE)


# ---------------------------------------------------------------------------
# I/O-Funktionen
# ---------------------------------------------------------------------------

def lade_plan(day: dt.date) -> bytes:
    """Lädt den XML-Plan für das angegebene Datum und gibt die rohen Bytes zurück."""

    url = f"{BASE_URL}/PlanKl{day:%Y%m%d}.xml"
    r = requests.get(url, auth=(USERNAME, PASSWORD), timeout=10)
    r.raise_for_status()
    return r.content


def parse_xml(xml_bytes: bytes, klasse: str = "10E") -> List[dict]:
    """Parst die XML-Bytes und liefert eine Liste von Dicts pro Stunde."""

    root = ET.fromstring(xml_bytes)
    kl = next(
        (
            k
            for k in root.findall(".//Kl")
            if (k.findtext("Kurz") or "").strip().upper() == klasse.upper()
        ),
        None,
    )
    if kl is None:
        return []

    pl = kl.find("Pl") or ET.Element("tmp")

    def g(e: ET.Element, tag: str):
        return (e.findtext(tag) or "").strip() or None

    rows: list[dict] = []
    for s in pl.findall("Std"):
        st     = int(g(s, "St") or 0)
        beginn = g(s, "Beginn")
        ende   = g(s, "Ende")
        fach_orig = g(s, "Fa")
        fach      = fach_orig
        kurs   = g(s, "Ku2")
        lehrer = g(s, "Le")
        raum   = g(s, "Ra")
        info   = g(s, "If")
        # Wenn Info vorhanden, aber Lehrer fehlt, gilt die Stunde oft als
        # Selbststudium. Wird kein Raum angegeben oder beginnt die Info mit
        # "selbst", werten wir das ebenfalls als Ausfall. Dann wird das
        # Fach auf "---" gesetzt und das Originalfach im Kursfeld geparkt.
        if info and not lehrer and (not raum or info.lower().startswith("selbst")):
            fach = "---"
            if not kurs:
                kurs = fach_orig
        rows.append({
            "stunde": st,
            "beginn": beginn,
            "ende":   ende,
            "fach":   fach,
            "kurs":   kurs,
            "lehrer": lehrer,
            "raum":   raum,
            "info":   info,
        })
    return rows


def filtered_xml(xml_bytes: bytes, klasse: str = "10E") -> str | None:
    """Gibt den XML-Block der Klasse gefiltert auf relevante Stunden zurück."""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    kl = next(
        (k for k in root.findall(".//Kl") if (k.findtext("Kurz") or "").strip().upper() == klasse.upper()),
        None,
    )
    if kl is None:
        return None

    pl = kl.find("Pl")
    if pl is None:
        return None

    rows = parse_xml(xml_bytes, klasse)
    std_nodes = pl.findall("Std")
    for row, node in list(zip(rows, std_nodes)):
        if not mine(row):
            pl.remove(node)

    return ET.tostring(kl, encoding="unicode")


# ---------------------------------------------------------------------------
# Filterfunktion (wird vom Bot überschrieben, falls gewünscht)
# ---------------------------------------------------------------------------

def keep(e: dict) -> bool:
    """True, wenn die Stunde für den Schüler relevant ist."""

    fach = (e["fach"] or "").upper()
    kurs = (e["kurs"] or "").upper()
    leh = (e["lehrer"] or "").upper()
    info = e["info"] or ""

    # reguläre Stunde: Fach+Lehrer müssen passen **oder** Kurs steht in MY_KURSE
    # reguläre Stunde: Fach+Lehrer-Kombi **oder** Kurs in unserer Kursliste
    if (fach, leh) in MY_COURSES or kurs in MY_KURSE:
        return True

    # Ausfall-Zeile: fach == '---'
    if fach == "---":
        return bool(
            kurs in MY_KURSE
            or kurs in SUBJECTS      # z. B. "DEU"
            or INFO_RE.search(info)
        )

    return False

# Alias, damit der Bot das Filterobjekt nach Belieben austauschen kann
mine = keep
