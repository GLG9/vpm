import os
import sys
import pathlib
import datetime as dt

# ensure required env vars exist before importing module
os.environ.setdefault('VP_USER', 'user')
os.environ.setdefault('VP_PASS', 'pass')
os.environ.setdefault('VP_BASE_URL', 'https://example.com')
os.environ.setdefault('DISCORD_TOKEN', 'token')
os.environ.setdefault('PLAN_CHANNEL_ID', '1')

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import vp_10e_plan as vp
import bot_with_plan_monitor as bot
import xml.etree.ElementTree as ET

def test_parse_xml_basic():
    xml = b"""<?xml version='1.0' encoding='utf-8'?>\n"""
    xml += b"<root>\n"
    xml += b"  <Kl>\n"
    xml += b"    <Kurz>10E</Kurz>\n"
    xml += b"    <Pl>\n"
    xml += b"      <Std>\n"
    xml += b"        <St>1</St>\n"
    xml += b"        <Beginn>7:15</Beginn>\n"
    xml += b"        <Ende>08:00</Ende>\n"
    xml += b"        <Fa>MAT</Fa>\n"
    xml += b"        <Ku2></Ku2>\n"
    xml += b"        <Le>FELD</Le>\n"
    xml += b"        <Ra>114</Ra>\n"
    xml += b"        <If></If>\n"
    xml += b"      </Std>\n"
    xml += b"      <Std>\n"
    xml += b"        <St>2</St>\n"
    xml += b"        <Beginn></Beginn>\n"
    xml += b"        <Ende></Ende>\n"
    xml += b"        <Fa>INF1</Fa>\n"
    xml += b"        <Ku2>INF1</Ku2>\n"
    xml += b"        <Le></Le>\n"
    xml += b"        <Ra></Ra>\n"
    xml += b"        <If>selbst.</If>\n"
    xml += b"      </Std>\n"
    xml += b"    </Pl>\n"
    xml += b"  </Kl>\n"
    xml += b"</root>\n"
    rows = vp.parse_xml(xml)
    assert rows == [
        {
            "stunde": 1,
            "beginn": "7:15",
            "ende": "08:00",
            "fach": "MAT",
            "kurs": None,
            "lehrer": "FELD",
            "raum": "114",
            "info": None,
        },
        {
            "stunde": 2,
            "beginn": None,
            "ende": None,
            "fach": "---",
            "kurs": "INF1",
            "lehrer": None,
            "raum": None,
            "info": "selbst.",
        },
    ]

def test_keep_filtering():
    entry_relevant = {
        "stunde": 1,
        "beginn": None,
        "ende": None,
        "fach": "GEO1",
        "kurs": None,
        "lehrer": "M\u00d6W",
        "raum": None,
        "info": None,
    }
    entry_irrelevant = {
        "stunde": 1,
        "beginn": None,
        "ende": None,
        "fach": "MUS",
        "kurs": None,
        "lehrer": "HANS",
        "raum": None,
        "info": None,
    }
    assert vp.keep(entry_relevant) is True
    assert vp.keep(entry_irrelevant) is False

def test_lade_plan_builds_url(monkeypatch):
    called = {}
    def fake_get(url, auth=None, timeout=10):
        called['url'] = url
        called['auth'] = auth
        class R:
            def raise_for_status(self):
                pass
            @property
            def content(self):
                return b'data'
        return R()
    monkeypatch.setattr(vp, 'USERNAME', 'user')
    monkeypatch.setattr(vp, 'PASSWORD', 'pass')
    monkeypatch.setattr(vp, 'BASE_URL', 'https://example.com')
    monkeypatch.setattr(vp.requests, 'get', fake_get)
    day = dt.date(2025,5,21)
    result = vp.lade_plan(day)
    assert result == b'data'
    assert called['url'] == 'https://example.com/PlanKl20250521.xml'
    assert called['auth'] == ('user', 'pass')

def test_canon_and_room_change():
    assert bot._canon('  Cafe\u0301  test  ') == 'Caf\u00e9 test'
    old = {"stunde": 1, "fach": "MAT", "kurs": None, "lehrer": "FELD", "raum": "115"}
    new = {"stunde": 1, "fach": "MAT", "kurs": None, "lehrer": "FELD", "raum": "114"}
    assert bot.room_change(old, new) == 'Raum\u00e4nderung: Stunde 1 MAT 115 \u2192 114'
    assert bot.room_change(old, old) is None


def test_filtered_xml():
    xml = b"""<?xml version='1.0' encoding='utf-8'?>\n"""
    xml += b"<root>\n"
    xml += b"  <Kl>\n"
    xml += b"    <Kurz>10E</Kurz>\n"
    xml += b"    <Pl>\n"
    xml += b"      <Std><St>1</St><Fa>MAT</Fa><Le>FELD</Le></Std>\n"
    xml += b"      <Std><St>2</St><Fa>MUS</Fa><Le>HANS</Le></Std>\n"
    xml += b"      <Std><St>3</St><Fa>INF1</Fa><Ku2>INF1</Ku2><If>selbst.</If></Std>\n"
    xml += b"    </Pl>\n"
    xml += b"  </Kl>\n"
    xml += b"</root>\n"

    result = vp.filtered_xml(xml)
    assert result is not None
    kl = ET.fromstring(result)
    stds = kl.findall('.//Std')
    assert len(stds) == 2  # MUS sollte entfernt sein
