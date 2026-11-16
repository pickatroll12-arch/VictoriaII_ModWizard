"""Criterios 3, 4 y 5 de la iteración 3 con el corpus real: VSM sobre vanilla (``VIC2_CORPUS``).

Cifras medidas con el corpus local del usuario (fuera del repositorio):

- Errores propios de VSM: exactamente los 7 del criterio 3. CSR, que solo tiene sus
  5 banderas (``gfx/flags/CSR*.tga``, que vanilla no trae) sin registro, historia ni
  textos, sale como ``flag_tag_not_registered`` (info): las banderas solas no rompen
  nada, y registrarlo sin archivo de país sí (revisión adversarial de la iteración 3).
- ``loc_copy_degraded`` da 3 427 claves, no las 3 429 del criterio: las claves de
  ``text.csv`` cuya fila efectiva (la que gana en la localización) es una fila de
  vanilla con letras perdidas como «?». Las filas degradadas son 3 438 (``lines``,
  las que cambia el arreglo), de 3 430 claves distintas (las 79 repetidas del archivo
  dan el resto); de esas, 3 no las gana ``text.csv`` sino un archivo que carga
  antes con su propio texto (``GUNBOAT_WE_ACCEPT_SETUP`` y ``REMOVE_NO_DEMOTION``,
  ``newtext.csv``; ``BOL_2305``, ``housedivided.csv``), así que en partida no se ven
  rotas. La cifra de H15 contaba de otra forma.
- Avisos propios que el criterio no nombra, clasificados: 6 ``semicolon_in_quotes``
  en ``00_VSM_decisions.csv`` (errores reales del usuario, CONTINUAR §7) y 35
  ``party_unknown_policy`` (7 partidos × 5 países con ``social_policy``).
- Registrar SIL destapa dos errores nuevos en sus archivos, que el juego no cargaba
  mientras SIL no estaba registrado: ``graphical_culture = AustrianGC`` (no existe;
  el de vanilla es ``AustriaHungaryGC``) y ``ruling_party = SIL_socialist``, que no
  está en ``common/countries/Silesia.txt``.
"""

import os
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import copy_user_mod, user_mod, vanilla_root  # noqa: E402
from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.index import FactsCache, build_index, extract_bytes  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.project.diffing import changed_lines  # noqa: E402
from vic2studio.core.validate import (BaselineCache, Validator, apply_fix, build_context, compute_baseline,  # noqa: E402
                                      explain, game_only_snapshot, plan_fix)
from vic2studio.core.validate.model import VERDICT_LOSES, VERDICT_MISSING, VERDICT_NOT_LOADED, VERDICT_WINS  # noqa: E402
from vic2studio.core.vfs import LayerKind, VirtualFS  # noqa: E402

DEGRADED_ROWS = 3427   # el criterio dice 3 429: ver el docstring
DEGRADED_LINES = 3438


def full_vsm() -> Path | None:
    """La carpeta VSM del mod completo (no la muestra mínima del repositorio)."""
    mod = user_mod()
    return mod if mod is not None and (mod / "localisation" / "text.csv").is_file() else None


@unittest.skipUnless(vanilla_root() and full_vsm(), "requiere el corpus completo (VIC2_CORPUS)")
class VsmValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = Path(tempfile.mkdtemp(prefix="vic2studio-validate-corpus-"))
        cls.env = {k: os.environ.get(k) for k in ("VIC2STUDIO_DATA_DIR", "VIC2STUDIO_CACHE_DIR")}
        os.environ["VIC2STUDIO_DATA_DIR"] = str(cls.temp / "data")
        os.environ["VIC2STUDIO_CACHE_DIR"] = str(cls.temp / "cache")
        mod = full_vsm()
        cls.mod_stat = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in mod.rglob("*") if p.is_file()}
        vfs = VirtualFS(vanilla_root(), mod, descriptor=mod.with_suffix(".mod"))
        vfs.scan()
        cls.snapshot = vfs.snapshot()
        game = game_only_snapshot(cls.snapshot)
        cls.baseline = compute_baseline(build_context(game, build_index(game, FactsCache()), game_only=True))
        BaselineCache().store(cls.snapshot, cls.baseline)
        cls.index = build_index(cls.snapshot, FactsCache())
        cls.ctx = build_context(cls.snapshot, cls.index)
        cls.report = Validator(cls.ctx, baseline=cls.baseline).validate()

    @classmethod
    def tearDownClass(cls):
        for key, value in cls.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(cls.temp, ignore_errors=True)

    def own(self, severity):
        return [p for p in self.report.problems if not p.inherited and p.severity is severity]

    def test_criterion_3_errors_are_exactly_the_known_ones(self):
        errors = sorted((p.code, str(p.rel)) for p in self.own(Severity.ERROR))
        self.assertEqual(errors, [
            ("nationalvalue_unknown", "history/countries/GEL - Geledi.txt"),
            ("nationalvalue_unknown", "history/countries/MAJ - Majeerteen.txt"),
            ("nationalvalue_unknown", "history/countries/SOM - Somalia.txt"),
            ("nationalvalue_unknown", "history/countries/WRL - Warsangali.txt"),
            ("tag_not_registered", "history/countries/SIL - Silesia.txt"),
            ("unclosed_block", "decisions/somaliland_shago.txt"),
            ("unclosed_block", "decisions/zulu_expancionshago.txt"),
        ])
        self.assertTrue(all(p.args["name"] == "nv_tradition" for p in self.own(Severity.ERROR)
                            if p.code == "nationalvalue_unknown"))
        [csr] = [p for p in self.own(Severity.INFO) if p.code == "flag_tag_not_registered"]
        self.assertEqual((csr.args["tag"], csr.args["flags"], str(csr.rel)), ("CSR", 5, "gfx/flags/CSR.tga"))

    def test_criterion_3_warnings(self):
        warnings = self.own(Severity.WARNING)
        by_code = Counter(p.code for p in warnings)
        self.assertEqual(set(by_code), {"ruling_party_ideology_not_allowed", "party_unknown_policy",
                                        "government_election_without_duration", "loc_copy_degraded",
                                        "semicolon_in_quotes", "ruling_party_inactive"},
                         "cualquier otro aviso hay que clasificarlo")
        # Iteración 6: el partido gobernante de Somalia (socialista) no está activo hasta 1848 y la partida
        # empieza en 1836. Es un fallo real del mod: el juego lo cambia por otro partido al cargar.
        [inactive] = [p for p in warnings if p.code == "ruling_party_inactive"]
        self.assertEqual((inactive.args["tag"], inactive.args["party"], inactive.args["start"]),
                         ("SOM", "SOM_socialist", "1848.1.1"))
        [ruling] = [p for p in warnings if p.code == "ruling_party_ideology_not_allowed"]
        self.assertEqual((ruling.args["party"], ruling.args["government"]), ("SOM_socialist", "absolute_monarchy"))
        # Criterio 4 de la iteración 6: el aviso trae su arreglo, con un partido de Somalia activo y admitido.
        self.assertEqual(ruling.fixes, ("set_ruling_party",))
        self.assertTrue(ruling.args["suggestion"].startswith("SOM_"), ruling.args)
        self.assertEqual(inactive.fixes, ("set_ruling_party",))
        self.assertEqual({p.args["policy"] for p in warnings if p.code == "party_unknown_policy"}, {"social_policy"})
        self.assertEqual(by_code["party_unknown_policy"], 35)
        [election] = [p for p in warnings if p.code == "government_election_without_duration"]
        self.assertEqual(election.args["government"], "absolute_monarchy")
        [degraded] = [p for p in warnings if p.code == "loc_copy_degraded"]
        self.assertEqual((str(degraded.rel), degraded.args["rows"], degraded.args["lines"]),
                         ("localisation/text.csv", DEGRADED_ROWS, DEGRADED_LINES))
        self.assertEqual(by_code["semicolon_in_quotes"], 6)
        self.assertEqual({str(p.rel) for p in warnings if p.code == "semicolon_in_quotes"},
                         {"localisation/00_VSM_decisions.csv"})

    def test_criterion_4_vanilla_problems_are_inherited_and_hidden(self):
        inherited = [p for p in self.report.problems if p.inherited]
        by_code = Counter(p.code for p in inherited)
        self.assertEqual(by_code["ruling_party_ideology_not_allowed"], 13)
        self.assertEqual(Counter(p.args["name"] for p in inherited if p.code == "duplicate_field"), {"civilized": 50})
        self.assertEqual(by_code["bmp_color_unmapped"], 27)
        self.assertEqual(sorted(p.args["province"] for p in inherited if p.code == "province_history_duplicate"),
                         ["1396", "1397"])
        self.assertIn(("non_game_encoding", "history/units/1861/HAI_oob.txt"),
                      {(p.code, str(p.rel)) for p in inherited})
        self.assertEqual([p.args["event"] for p in inherited if p.code == "event_ref_missing"], ["11108"])
        self.assertEqual([p.args["cb"] for p in inherited if p.code == "peace_order_unknown"], ["annex"])
        visible = self.report.visible()
        self.assertFalse(any(p.inherited for p in visible), "ocultos por defecto")
        self.assertEqual(len(self.report.visible(inherited=True)), len(self.report.problems))
        self.assertTrue(self.report.baseline_ready)
        self.assertEqual(BaselineCache().load(self.snapshot), self.baseline)

    def test_reading_and_validating_wrote_nothing_in_vsm(self):
        mod = full_vsm()
        now = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in mod.rglob("*") if p.is_file()}
        self.assertEqual(now, self.mod_stat)

    def test_criterion_5_explainers(self):
        [sil] = [p for p in self.report.problems if p.code == "tag_not_registered" and p.args["tag"] == "SIL"]
        explanation = explain(sil, self.ctx)
        steps = [(str(s.rel), s.verdict) for s in explanation.steps]
        self.assertEqual(steps[0], ("common/countries.txt", VERDICT_MISSING))
        self.assertIn(("common/countries/Silesia.txt", VERDICT_NOT_LOADED), steps)
        self.assertIn(("history/countries/SIL - Silesia.txt", VERDICT_NOT_LOADED), steps)
        self.assertIn(("gfx/flags/SIL.tga", VERDICT_NOT_LOADED), steps)
        provinces = [rel for rel, verdict in steps if rel.startswith("history/provinces/")]
        self.assertEqual([Path(rel).name.split(" ")[0] for rel in provinces], ["682", "683", "684", "685"])
        self.assertIn("682, 683, 684, 685", explanation.outcome("es"))
        [degraded] = [p for p in self.report.problems if p.code == "loc_copy_degraded"]
        explanation = explain(degraded, self.ctx)
        self.assertEqual([(s.layer, str(s.rel), s.verdict) for s in explanation.steps],
                         [("mod", "localisation/text.csv", VERDICT_WINS),
                          ("game", "localisation/text.csv", VERDICT_LOSES)])
        self.assertIn("text.csv", explanation.outcome("es"))
        self.assertIn("?", explanation.args["example"])


@unittest.skipUnless(vanilla_root() and full_vsm(), "requiere el corpus completo (VIC2_CORPUS)")
class RegisterSilTests(unittest.TestCase):
    """Criterio 5: «Registrar SIL» (diff de 1 línea antes de dynamic_tags), revalidar y Ctrl+Z, sin guardar."""

    def setUp(self):
        from _layers import isolate_appdirs

        isolate_appdirs(self)

    def test_register_sil(self):
        mod = copy_user_mod(self, "common", "history")   # nunca el VSM real: abrirlo deja ahí su cerrojo
        project = Project.open(vanilla_root(), mod)
        self.addCleanup(project.close, discard=True)
        snap = project.vfs.snapshot()
        index = build_index(snap, FactsCache())
        report = Validator(build_context(snap, index)).validate(codes={"tag_not_registered"})
        [problem] = report.problems
        history = project.ws.history()
        plan = plan_fix("register_tag", problem, project)
        self.assertEqual(project.ws.history(), history)
        self.assertEqual(project.ws.dirty(), [])
        [change] = plan.changes
        self.assertEqual((str(change.rel), change.action), ("common/countries.txt", "modify"))
        added = [line for line in change.diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
        self.assertEqual(added, ['+SIL = "countries/Silesia.txt"'])
        apply_fix("register_tag", problem, project)
        handle = project.ws.peek("common/countries.txt")
        before = (mod / "common" / "countries.txt").read_bytes()
        after = codec_for(handle.kind).snapshot(handle.model)
        self.assertEqual(changed_lines(before, after), (1, 0))
        lines = after.decode("cp1252").split("\r\n")
        position = lines.index('SIL = "countries/Silesia.txt"')
        self.assertTrue(lines[position - 1].startswith("WRL"), "tras el último TAG del usuario")
        self.assertEqual(lines[position + 1:position + 6],
                         ["", "", "#Shago mod america", "", "##HoD Dominions"], "delante de los comentarios")
        self.assertTrue(lines[position + 6].startswith("dynamic_tags"))
        overrides = {h.rel: codec_for(h.kind).snapshot(h.model) for h in project.ws.dirty()}
        index.apply([f for rel, data in overrides.items() for f in extract_bytes(rel, data, LayerKind.MOD)])
        report = Validator(build_context(snap, index, overrides)).validate(
            codes={"tag_not_registered", "graphical_culture_unknown", "ruling_party_not_of_country"})
        found = sorted((p.code, dict(p.args).get("name") or dict(p.args).get("party")) for p in report.problems)
        self.assertEqual(found, [("graphical_culture_unknown", "AustrianGC"),
                                 ("ruling_party_not_of_country", "SIL_socialist")],
                         "el error se va; registrar SIL destapa dos errores reales de sus archivos")
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [])
        self.assertEqual(project.ws.history(), history)


if __name__ == "__main__":
    unittest.main()
