"""Creación de países (receta ``new_country``, wizard §14.2, iteración 6): criterios 1 a 4 sobre el minijuego.

1. El plan (``plan_new_country``) no cambia nada y nombra exactamente los archivos que la creación toca: el registro
   (una línea más, delante del comentario de ``dynamic_tags``), el archivo de país, la historia, el OOB, las 5
   banderas, la localización y las historias de las provincias reasignadas. Todo en una transacción que un solo
   deshacer revierte.
2. ``check_tag`` rechaza un TAG usado, dinámico, de dispositivo de Windows, de palabra de guion, reservado o de
   patrón inválido, y ``suggest_tags`` propone libres.
3. Las banderas que escribe son TGA de 93×64 y 32 bits con origen abajo a la izquierda que Pillow relee.
4. «Copiar partidos de…» renombra los partidos con el prefijo del TAG nuevo.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

import _minigame as mg  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from vic2studio.core.domain import country as cc  # noqa: E402
from vic2studio.core.domain.nation import Countries  # noqa: E402
from vic2studio.core.domain.tags import (  # noqa: E402
    REASON_DYNAMIC, REASON_PATTERN, REASON_RESERVED, REASON_SCRIPT_WORD, REASON_TAKEN, REASON_WINDOWS_DEVICE,
    check_tag, suggest_tags, taken_tags,
)
from vic2studio.core.gfx.flags import FLAG_SIZE, FLAG_SUFFIXES, make_flag_set  # noqa: E402
from vic2studio.core.index import build_index  # noqa: E402
from vic2studio.core.locsync import LocSync  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.rules.game import GameRules  # noqa: E402
from vic2studio.core.schema import Entities  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402


def open_context(case: unittest.TestCase) -> cc.DomainContext:
    """El minijuego del mapa (sin la historia duplicada) abierto, con índice, reglas, textos y entidades."""
    isolate_appdirs(case)
    game = mg.build_map_minigame(clean=True)
    case.addCleanup(game.cleanup)
    project = Project.open(game.game_root, game.mod_root)
    case.addCleanup(project.close, discard=True)
    snapshot = project.vfs.snapshot()
    index = build_index(snapshot, None)
    loc = LocSync(project.ws, project.vfs, prefix=project.settings.prefix)
    return cc.DomainContext(project.ws, project.vfs, index, loc, Entities(project.ws, index, loc),
                            GameRules.from_snapshot(snapshot), project.settings)


def text(ctx, rel) -> str:
    handle = ctx.ws.open(VPath.of(rel))
    return codec_for(handle.kind).snapshot(handle.model).decode("cp1252")


def spec_for(ctx, **changes) -> cc.NewCountrySpec:
    flags = make_flag_set({suffix: Image.new("RGB", (120, 80), (200, 30, 30)) for suffix in FLAG_SUFFIXES})
    values = dict(tag="SOM", name={"en": "Somalia", "es": "Somalia"}, adjective={"en": "Somali", "es": "somalí"},
                  color=(10, 200, 30), primary_culture="alander", religion="catholic", government="monarchy",
                  parties=cc.party_template("SOM", ctx.index), ruling_party="SOM_conservative",
                  upper_house={"conservative": 100}, flags=flags, provinces=(2, 3), capital=2,
                  armies=(cc.ArmySpec("Army of Somalia", 2, (cc.RegimentSpec("1st", "infantry", 2),)),))
    values.update(changes)
    return cc.NewCountrySpec(**values)


class CreateCountryTests(unittest.TestCase):
    def test_plan_names_exactly_what_creation_touches_and_one_undo_reverts_it(self):
        ctx = open_context(self)
        spec = spec_for(ctx)
        plan = cc.plan_new_country(ctx, spec)
        self.assertEqual([h for h in ctx.ws.documents() if h.dirty], [], "el plan no deja nada cambiado")
        planned = {str(change.rel) for change in plan.changes}
        registry_before = text(ctx, "common/countries.txt")
        with ctx.ws.transaction(cc.UNDO_NEW_COUNTRY, tag=spec.tag, name=spec.display_name()) as txn:
            cc.build_new_country(ctx, spec)
            touched = {str(rel) for rel in txn.touched()}
        self.assertEqual(touched, planned)
        for rel in ("common/countries/Somalia.txt", "history/countries/SOM - Somalia.txt",
                    "history/units/SOM_oob.txt", *(f"gfx/flags/SOM{s}.tga" for s in FLAG_SUFFIXES),
                    "history/provinces/south/2  Llanura.txt"):
            self.assertIn(rel, touched)
        registry = text(ctx, "common/countries.txt")
        self.assertEqual(registry.count("\n"), registry_before.count("\n") + 1, "una línea más en el registro")
        lines = registry.splitlines()
        new = lines.index('SOM = "countries/Somalia.txt"')
        self.assertLess(new, next(i for i, line in enumerate(lines) if line.startswith("## Dominios")))
        history = text(ctx, "history/countries/SOM - Somalia.txt")
        for line in ("capital = 2", "primary_culture = alander", "ruling_party = SOM_conservative",
                     'oob = "SOM_oob.txt"'):
            self.assertIn(line, history)
        countries = Countries(ctx.entities, ctx.rules)
        self.assertEqual(ctx.loc.text("SOM", "es"), "Somalia")
        self.assertEqual(ctx.loc.text("SOM_ADJ", "en"), "Somali")
        province = text(ctx, "history/provinces/south/2  Llanura.txt")
        self.assertIn("owner = SOM", province)
        self.assertIn("add_core = SOM", province)
        self.assertIsNotNone(countries)
        ctx.ws.undo()
        self.assertEqual(text(ctx, "common/countries.txt"), registry_before)
        handle = ctx.ws.peek(VPath.of("history/countries/SOM - Somalia.txt"))
        self.assertTrue(handle is None or handle.deleted, "un solo deshacer quita la historia nueva")
        self.assertNotIn("owner = SOM", text(ctx, "history/provinces/south/2  Llanura.txt"))

    def test_bad_specs_change_nothing(self):
        ctx = open_context(self)
        for spec, code in ((spec_for(ctx, tag="AAA"), "tag"), (spec_for(ctx, name={}), "no_name"),
                           (spec_for(ctx, ruling_party="NOPE"), "bad_party"),
                           (spec_for(ctx, capital=7, provinces=(2, 3)), "capital")):
            with self.subTest(code=code):
                with self.assertRaises(cc.CountryError) as raised:
                    cc.create_new_country(ctx, spec)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual([h for h in ctx.ws.documents() if h.dirty], [])


class TagTests(unittest.TestCase):
    def test_rejections_and_suggestions(self):
        taken = {"PRU", "AAA"}
        cases = {"PRU": REASON_TAKEN, "D07": REASON_DYNAMIC, "CON": REASON_WINDOWS_DEVICE, "AND": REASON_SCRIPT_WORD,
                 "REB": REASON_RESERVED, "12A": REASON_PATTERN, "ab": REASON_PATTERN, "ABCD": REASON_PATTERN}
        for tag, reason in cases.items():
            with self.subTest(tag=tag):
                result = check_tag(tag, taken)
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, reason)
        self.assertTrue(check_tag("SOM", taken).ok)
        suggestions = suggest_tags("Somalia", taken)
        self.assertEqual(len(suggestions), 3)
        self.assertEqual(suggestions[0], "SOM")
        self.assertTrue(all(check_tag(tag, taken).ok for tag in suggestions))
        self.assertNotIn("PRU", suggest_tags("Prussia", taken))

    def test_taken_tags_come_from_the_registry(self):
        ctx = open_context(self)
        taken = taken_tags(ctx.index)
        self.assertEqual(check_tag("AAA", taken).reason, REASON_TAKEN)
        self.assertTrue(check_tag("SOM", taken).ok)


class FlagTests(unittest.TestCase):
    def test_written_flags_are_93x64_32_bit_bottom_left_and_readable(self):
        ctx = open_context(self)
        cc.create_new_country(ctx, spec_for(ctx))
        for suffix in FLAG_SUFFIXES:
            handle = ctx.ws.peek(VPath.of(f"gfx/flags/SOM{suffix}.tga"))
            data = bytes(handle.model)
            self.assertEqual(data[2], 2, "TGA de color verdadero sin comprimir")
            self.assertEqual(int.from_bytes(data[12:14], "little"), FLAG_SIZE[0])
            self.assertEqual(int.from_bytes(data[14:16], "little"), FLAG_SIZE[1])
            self.assertEqual(data[16], 32)
            self.assertEqual(data[17] & 0x20, 0, "origen abajo a la izquierda")
            image = Image.open(io.BytesIO(data))
            self.assertEqual(image.size, FLAG_SIZE)
            self.assertEqual(image.convert("RGBA").getpixel((40, 30))[:3], (200, 30, 30))


class PartyTests(unittest.TestCase):
    def test_copy_parties_renames_with_the_new_prefix(self):
        ctx = open_context(self)
        copied = cc.copy_parties(ctx, "AAA", "SOM")
        self.assertTrue(copied)
        self.assertTrue(all(party.name.startswith("SOM_") for party in copied), [p.name for p in copied])
        self.assertEqual(cc.renamed_party("PRU_conservative", "PRU", "SOM"), "SOM_conservative")
        self.assertEqual(cc.renamed_party("liberal_party", "PRU", "SOM"), "SOM_liberal_party")   # sin prefijo, se le pone
        template = cc.party_template("SOM", ctx.index)
        self.assertEqual({p.ideology for p in template}, {p.name.split("_", 1)[1] for p in template})


if __name__ == "__main__":
    unittest.main()


class NationFacadeTests(unittest.TestCase):
    """Lo que la ficha nacional añade a la fachada: culturas aceptadas, campos del archivo de país y partidos."""

    def test_cultures_file_values_and_parties(self):
        ctx = open_context(self)
        countries = Countries(ctx.entities, ctx.rules)
        date = ctx.rules.bookmarks[0]
        with ctx.ws.transaction("t"):
            self.assertEqual(countries.set_cultures("AAA", ["borlander"], date), ["borlander"])
            self.assertTrue(countries.set_file_value("AAA", "color", (1, 2, 3)))
            self.assertFalse(countries.set_file_value("AAA", "color", (1, 2, 3)))
            countries.add_party("AAA", "Nuevo Partido", "liberal", policies={"trade_policy": "free_trade"})
        self.assertEqual(countries.cultures("AAA", date), ["borlander"])
        self.assertEqual(countries.file_value("AAA", "color"), (1, 2, 3))
        country = text(ctx, "common/countries/Aland.txt")
        self.assertIn('name = "Nuevo Partido"', country)
        self.assertIn("color = { 1 2 3 }", country)
        with ctx.ws.transaction("t2"):
            self.assertEqual(countries.remove_party("AAA", 0), "AAA_conservative")
        self.assertNotIn("AAA_conservative", text(ctx, "common/countries/Aland.txt"))
        with ctx.ws.transaction("t3"):
            countries.set_cultures("AAA", [], date)
        self.assertEqual(countries.cultures("AAA", date), [])
