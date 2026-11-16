"""Guerras de inicio y diplomacia (``core.domain.war``, wizard §14.8, iteración 6, criterio 6).

Una guerra nueva se escribe con la forma de las de vanilla (nombre, bloque de inicio con bandos y objetivos y,
si acaba, bloque de salidas) y ``read_war`` la relee igual; crearla es un paso de deshacer y el plan no cambia
nada. Las relaciones se añaden y quitan sin tocar el resto del archivo. Con el corpus, las 5 guerras y los 4
archivos de diplomacia de vanilla hacen ida y vuelta byte a byte y se leen.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import vanilla_root  # noqa: E402
from test_country_create import open_context, text  # noqa: E402

from vic2studio.core.domain import war as cw  # noqa: E402
from vic2studio.core.project.codecs import ClausewitzCodec, parse_bytes  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

SPEC = cw.WarSpec("Guerra del Estrecho", "1836.1.1", ("AAA", "CCC"), ("BBB",),
                  (cw.WarGoal("conquer_land", "AAA", "BBB", state_province_id=3),
                   cw.WarGoal("free_people", "CCC", "BBB", country="CCC")), end="1840.6.1")


class WarTextTests(unittest.TestCase):
    def test_new_war_has_the_vanilla_shape(self):
        data = cw.war_text(SPEC)
        self.assertTrue(data.endswith(b"\r\n"))
        lines = data.decode("cp1252").split("\r\n")
        self.assertEqual(lines[:3], ['name = "Guerra del Estrecho"', "", "1836.1.1 = {"])
        self.assertEqual(lines[3:6], ["\tadd_attacker = AAA", "\tadd_attacker = CCC", "\tadd_defender = BBB"])
        self.assertIn("\twar_goal = {", lines)
        self.assertIn("\t\tstate_province_id = 3", lines)
        self.assertIn("\t\tcountry = CCC", lines)
        self.assertIn("1840.6.1 = {", lines)
        self.assertIn("\trem_defender = BBB", lines)

    def test_read_war_reads_back_what_war_text_writes(self):
        model = cw.read_war(parse_bytes(cw.war_text(SPEC)).document)
        self.assertEqual(model.name, SPEC.name)
        self.assertEqual((model.start, model.end), ("1836.1.1", "1840.6.1"))
        self.assertEqual(model.attackers, ["AAA", "CCC"])
        self.assertEqual(model.defenders, ["BBB"])
        self.assertEqual([(g.casus_belli, g.actor, g.receiver, g.state_province_id, g.country) for g in model.goals],
                         [("conquer_land", "AAA", "BBB", 3, None), ("free_people", "CCC", "BBB", None, "CCC")])
        self.assertTrue(model.active_at("1838.1.1"))
        self.assertFalse(model.active_at("1841.1.1"))
        self.assertFalse(model.active_at("1830.1.1"))

    def test_check_war(self):
        cases = {"no_name": SPEC.__class__("", "1836.1.1", ("AAA",), ("BBB",)),
                 "no_date": SPEC.__class__("X", "1836.13.1", ("AAA",), ("BBB",)),
                 "no_sides": SPEC.__class__("X", "1836.1.1", ("AAA",), ()),
                 "same_side": SPEC.__class__("X", "1836.1.1", ("AAA",), ("aaa",)),
                 "dates_order": SPEC.__class__("X", "1836.1.1", ("AAA",), ("BBB",), end="1830.1.1")}
        for code, spec in cases.items():
            with self.subTest(code=code):
                with self.assertRaises(cw.WarError) as raised:
                    cw.check_war(spec)
                self.assertEqual(raised.exception.code, code)
        cw.check_war(SPEC)

    def test_goal_needs_follows_the_peace_options(self):
        ctx = open_context(self)
        self.assertEqual(cw.goal_needs(ctx.index, "conquer_land"), (True, True))     # po_transfer_provinces
        self.assertEqual(cw.goal_needs(ctx.index, "free_people"), (False, True))     # po_release_puppet
        self.assertEqual(cw.goal_needs(ctx.index, "humble_rival"), (False, False))
        self.assertEqual(cw.goal_needs(ctx.index, None), (False, False))


class CreateWarTests(unittest.TestCase):
    def test_plan_changes_nothing_and_creation_is_one_undo_step(self):
        ctx = open_context(self)
        plan = cw.plan_war(ctx, SPEC)
        self.assertEqual([str(c.rel) for c in plan.changes], ["history/wars/TESTMOD_Guerra del Estrecho.txt"])
        self.assertEqual([h for h in ctx.ws.documents() if h.dirty], [])
        rel = cw.create_war(ctx, SPEC)
        self.assertEqual(str(rel), "history/wars/TESTMOD_Guerra del Estrecho.txt")
        self.assertIn(rel, [r for r, _model in cw.wars(ctx)])
        with self.assertRaises(cw.WarError) as raised:
            cw.create_war(ctx, SPEC)
        self.assertEqual(raised.exception.code, "file_exists")
        ctx.ws.undo()
        self.assertNotIn(rel, [r for r, _model in cw.wars(ctx)])


class RelationTests(unittest.TestCase):
    def test_add_and_remove_keep_the_rest_of_the_file(self):
        ctx = open_context(self)
        rel = "history/diplomacy/Alliances.txt"
        before = text(ctx, rel)
        self.assertEqual([(r.type, r.first, r.second) for r in cw.relations(ctx)], [("alliance", "AAA", "CCC")])
        cw.add_relation(ctx, "alliance", "BBB", "CCC", "1836.1.1")
        after = text(ctx, rel)
        self.assertTrue(after.startswith(before), "lo que había queda byte a byte")
        self.assertIn('start_date = "1836.1.1"', after)
        with self.assertRaises(cw.WarError) as raised:
            cw.add_relation(ctx, "alliance", "BBB", "CCC", "1836.1.1")
        self.assertEqual(raised.exception.code, "relation_exists")
        with self.assertRaises(cw.WarError) as raised:
            cw.add_relation(ctx, "alliance", "BBB", "bbb", "1836.1.1")
        self.assertEqual(raised.exception.code, "relation_same")
        with self.assertRaises(cw.WarError) as raised:
            cw.add_relation(ctx, "vassal", "AAA", "BBB", "1836.1.1", "1830.1.1")
        self.assertEqual(raised.exception.code, "dates_order")
        added = [r for r in cw.relations(ctx, "BBB")]
        self.assertEqual(len(added), 1)
        cw.remove_relation(ctx, added[0])
        self.assertEqual(text(ctx, rel), before)

    def test_a_new_type_goes_to_its_vanilla_file(self):
        ctx = open_context(self)
        rel = cw.add_relation(ctx, "vassal", "AAA", "BBB", "1836.1.1")
        self.assertEqual(rel, VPath.of("history/diplomacy/PuppetStates.txt"))
        self.assertEqual([r.type for r in cw.relations(ctx, "BBB")], ["vassal"])


class VanillaTests(unittest.TestCase):
    def test_vanilla_wars_and_diplomacy_round_trip_and_read(self):
        game = vanilla_root()
        if game is None:
            self.skipTest("sin el juego base (VIC2_CORPUS)")
        codec = ClausewitzCodec()
        wars = sorted((game / "history" / "wars").glob("*.txt"))
        diplomacy = sorted((game / "history" / "diplomacy").glob("*.txt"))
        self.assertEqual((len(wars), len(diplomacy)), (5, 4))
        for path in wars + diplomacy:
            with self.subTest(archivo=path.name):
                data = path.read_bytes()
                model, _diagnostics = codec.load(data, VPath.of(path.name))
                self.assertEqual(codec.snapshot(model), data, "ida y vuelta byte a byte")
        for path in wars:
            model = cw.read_war(parse_bytes(path.read_bytes()).document, path.stem)
            with self.subTest(guerra=path.name):
                self.assertIsNotNone(model.start)
                self.assertTrue(model.attackers and model.defenders)
                self.assertTrue(model.goals)
        relations = 0
        for path in diplomacy:
            document = parse_bytes(path.read_bytes()).document
            relations += sum(1 for e in document.entries if e.key is not None
                             and e.key.text.lower() in cw.RELATION_TYPES)
        self.assertGreater(relations, 10)


if __name__ == "__main__":
    unittest.main()
