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

__all__ = [
    "lade_plan",
    "parse_xml",
    "mine",  # Alias auf keep()
]

USERNAME: str = os.getenv("VP_USER", "REMOVED")
PASSWORD: str = os.getenv("VP_PASS", "REMOVED")
# Für Produktion ggf. per .env überschreiben
BASE_URL: str = os.getenv(
    "VP_BASE_URL", "REMOVED"
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
INFO_RE = re.compile(
    "|".join(re.escape(x) for x in MY_KURSE | MY_LEHRER), re.IGNORECASE
)


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
        rows.append(
            {
                "stunde": int(g(s, "St") or 0),
                "beginn": g(s, "Beginn"),
                "ende": g(s, "Ende"),
                "fach": g(s, "Fa"),
                "kurs": g(s, "Ku2"),
                "lehrer": g(s, "Le"),
                "raum": g(s, "Ra"),
                "info": g(s, "If"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Filterfunktion (wird vom Bot überschrieben, falls gewünscht)
# ---------------------------------------------------------------------------

def keep(e: dict) -> bool:
    """True, wenn die Stunde für den Schüler relevant ist."""

    fach = (e["fach"] or "").upper()
    kurs = (e["kurs"] or "").upper()
    leh = (e["lehrer"] or "").upper()
    info = e["info"] or ""

    if (fach, leh) in MY_COURSES:
        return True
    # Eintrag '---' signalisiert Ausfall; Info-Feld enthält oft Kurs oder Lehrer
    return fach == "---" and (kurs in MY_KURSE or INFO_RE.search(info))


# Alias, damit der Bot das Filterobjekt nach Belieben austauschen kann
mine = keep