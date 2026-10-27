"""Lo que ya implementa el contrato de la iteración 3: registros, ``Problem`` y ``LocalisationDB.from_entries``."""

import pickle
import sys
import unittest
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.csvloc import LocalisationDB  # noqa: E402
from vic2studio.core.csvloc.serialization import parse_csv  # noqa: E402
from vic2studio.core.index import model as index_model  # noqa: E402
from vic2studio.core.validate import registry  # noqa: E402
from vic2studio.core.validate.model import Problem, ValidationReport  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402


def csv(name: str, text: str):
    file = parse_csv(text)
    file.path = Path("/x/localisation") / name
    return file


class FromEntriesTests(unittest.TestCase):
    def test_files_load_in_game_order_whatever_the_input_order(self):
        text = csv("text.csv", "KEY;from text;x\n")
        mod = csv("00_VSM_overrides.csv", "KEY;from mod;x\n")
        db = LocalisationDB.from_entries([text, mod], dirs=["/x/localisation"])
        self.assertEqual([f.path.name for f in db.files], ["00_VSM_overrides.csv", "text.csv"])
        self.assertEqual(db.lookup("KEY"), "from mod")
        self.assertEqual(db.origin("KEY"), 0)


class RegistryTests(unittest.TestCase):
    def tearDown(self):
        registry.RULES.pop("contract_probe", None)
        index_model.EXTRACTORS[:] = [s for s in index_model.EXTRACTORS if not s.name.endswith("probe_extractor")]

    def test_make_problem_takes_severity_and_fixes_from_the_rule(self):
        @registry.rule("contract_probe", Severity.WARNING, fixes=("register_tag",))
        def probe(ctx):
            return ()

        problem = registry.make_problem("contract_probe", VPath.of("common/countries.txt"), 3, tag="SIL")
        self.assertIs(problem.severity, Severity.WARNING)
        self.assertEqual(problem.fixes, ("register_tag",))
        with self.assertRaises(ValueError):
            registry.rule("contract_probe", Severity.ERROR)(probe)

    def test_extractor_registry_matches_by_glob(self):
        @index_model.extractor("history/provinces/**/*.txt", version=1)
        def probe_extractor(rel, data, layer):
            return (), ()

        rel = VPath.of("history/provinces/europe/549 - Berlin.txt")
        self.assertIn("test_contract_it3.probe_extractor", [s.name for s in index_model.extractors_for(rel)])
        self.assertEqual(index_model.fold("Berlín"), "berlin")


class ProblemTests(unittest.TestCase):
    def test_pickle_and_fingerprint_without_position(self):
        a = Problem("tag_not_registered", Severity.ERROR, VPath.of("history/countries/SIL - Silesia.txt"), 3,
                    entity=("tag", "SIL"), args=MappingProxyType({"tag": "SIL"}))
        b = Problem("tag_not_registered", Severity.ERROR, VPath.of("history/countries/SIL - Silesia.txt"), 9,
                    entity=("tag", "SIL"), args=MappingProxyType({"tag": "SIL"}))
        self.assertEqual(pickle.loads(pickle.dumps(a)), a)
        self.assertIsInstance(pickle.loads(pickle.dumps(a)).args, MappingProxyType)
        self.assertEqual(a.fingerprint(), b.fingerprint())

    def test_report_hides_inherited_by_default(self):
        own = Problem("x", Severity.ERROR, None)
        inherited = Problem("y", Severity.WARNING, None, inherited=True)
        report = ValidationReport((own, inherited))
        self.assertEqual(report.visible(), [own])
        self.assertEqual(report.count(inherited=True), 2)
        self.assertEqual(report.inherited_count(), 1)


if __name__ == "__main__":
    unittest.main()
