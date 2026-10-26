"""``project.json`` ⇄ ``ProjectSettings`` (wizard §5.4, §6.4, decisiones 1, 3 y 7 de §24)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.clausewitz import ClausewitzDate  # noqa: E402
from vic2studio.core.modfile import ModDescriptor  # noqa: E402
from vic2studio.core.project import ProjectSettings  # noqa: E402
from vic2studio.core.project.model import EVENT_ID_BLOCK, EVENT_ID_START  # noqa: E402
from vic2studio.core.project.settings import (  # noqa: E402
    default_prefix,
    default_settings,
    load_settings,
    render_settings,
    settings_from_json,
)


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(default_prefix(Path("/games/mod/VSM")), "VSM")
        self.assertEqual(default_prefix(Path("/games/mod/Dark Age-Mod 2")), "DARKAGEMOD2")
        self.assertEqual(default_prefix(Path("/games/mod/ñ")), "MOD")
        descriptor = ModDescriptor(Path("/g/mod/x.mod"), name="X", path="mod/DAM")
        self.assertEqual(default_prefix(Path("/elsewhere/whatever"), descriptor), "DAM")
        settings = default_settings(Path("/g/mod/VSM"))
        self.assertEqual(settings.languages, ("en", "es"))
        self.assertEqual(settings.copy_en_to, ())
        self.assertEqual(settings.id_ranges["event"], (EVENT_ID_START, EVENT_ID_START + EVENT_ID_BLOCK - 1))
        self.assertEqual(settings.id_ranges["event"], (200_000_000, 200_009_999))
        self.assertEqual(settings.working_date, ClausewitzDate(1836, 1, 1))
        self.assertEqual(settings.mode, "simple")
        self.assertTrue(settings.backup_bak)

    def test_reading_does_not_create_and_tolerates_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "VSM"
            path = mod / ".vic2studio" / "project.json"
            self.assertEqual(load_settings(path, mod_root=mod), default_settings(mod))
            self.assertFalse(path.parent.exists())
            path.parent.mkdir(parents=True)
            for bad in (b"{roto", b"[1, 2]", "ñ".encode("latin-1")):
                path.write_bytes(bad)
                self.assertEqual(load_settings(path, mod_root=mod), default_settings(mod))
            path.write_text(json.dumps({
                "prefix": "bad prefix!", "languages": "en", "copy_en_to": ["fr", "de"],
                "id_ranges": {"event": [5, 1], "decision": [10, 20]}, "working_date": "1836.2.30",
                "mode": "expert", "backup_bak": "yes"}), encoding="utf-8")
            settings = load_settings(path, mod_root=mod)
            self.assertEqual(settings.prefix, "VSM")
            self.assertEqual(settings.languages, ("en", "es"))
            self.assertEqual(settings.copy_en_to, ("fr", "de"))
            self.assertEqual(dict(settings.id_ranges), {"event": (200_000_000, 200_009_999), "decision": (10, 20)})
            self.assertEqual(settings.working_date, ClausewitzDate(1836, 1, 1))
            self.assertEqual(settings.mode, "simple")
            self.assertTrue(settings.backup_bak)

    def test_render_round_trip_and_unknown_keys(self):
        settings = ProjectSettings(prefix="TST", languages=("en", "es", "fr"), copy_en_to=("de",),
                                   id_ranges={"event": (300_000_000, 300_009_999)},
                                   working_date=ClausewitzDate(1861, 7, 1), mode="advanced", backup_bak=False)
        data = render_settings(settings)
        self.assertTrue(data.endswith(b"\n"))
        self.assertIn(b'\n  "prefix": "TST"', data, "sangría 2")
        self.assertEqual(json.loads(data)["format"], 1)
        self.assertEqual(settings_from_json(data, mod_root=Path("/m/TST")), settings)
        existing = json.dumps({"mapforge": {"name": "Nuevo"}, "prefix": "OLD"}).encode()
        merged = json.loads(render_settings(settings, existing))
        self.assertEqual(merged["mapforge"], {"name": "Nuevo"})
        self.assertEqual(merged["prefix"], "TST")
        self.assertEqual(list(merged)[:2], ["mapforge", "prefix"], "el orden de las claves existentes se mantiene")
        self.assertEqual(json.loads(render_settings(settings, b"{roto")), json.loads(data))


if __name__ == "__main__":
    unittest.main()
