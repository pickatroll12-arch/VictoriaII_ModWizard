"""Arreglo «Poner <partido> como partido gobernante» (iteración 6, criterio 4: con VSM, SOM_socialist da el aviso
con su arreglo). Lo ofrecen ``ruling_party_ideology_not_allowed`` y ``ruling_party_inactive``: cambia solo el token
del partido por el primero del país activo en la fecha de inicio y admitido por su gobierno.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _minigame import GAME_FILES  # noqa: E402
from test_validate_it4_y1 import FixTestCase, project_problems  # noqa: E402

from vic2studio.core.validate import FIXES, apply_fix, plan_fix  # noqa: E402
from vic2studio.core.validate.fixes import FixError  # noqa: E402
from vic2studio.core.validate.model import ACTION_MODIFY  # noqa: E402

ALAND = "common/countries/Aland.txt"
AAA = "history/countries/AAA - Aland.txt"
LIBERAL = ("\r\nparty = {\r\n\tname = \"AAA_liberal\"\r\n\tstart_date = 1800.1.1\r\n\tend_date = 2000.1.1\r\n"
           "\tideology = liberal\r\n\teconomic_policy = laissez_faire\r\n\ttrade_policy = free_trade\r\n"
           "\treligious_policy = pluralism\r\n\tcitizenship_policy = full_citizenship\r\n"
           "\twar_policy = anti_military\r\n}\r\n")
SOCIALIST = LIBERAL.replace("AAA_liberal", "AAA_socialist").replace("ideology = liberal", "ideology = socialist")


def history(extra: str, government: str = "monarchy") -> str:
    return (f"capital = 1\r\nprimary_culture = alander\r\ngovernment = {government}\r\n"
            f"ruling_party = {extra} # elegido a mano\r\n")


class RulingPartyFixTests(FixTestCase):
    def fix(self, project, code: str):
        [problem] = project_problems(project, code)
        self.assertEqual(problem.fixes, ("set_ruling_party",))
        plan = plan_fix("set_ruling_party", problem, project)
        apply_fix("set_ruling_party", problem, project, expected=plan)
        self.assertEqual(project.ws.history()[0][0], "undo.fix_set_ruling_party")
        self.assertEqual(project_problems(project, code), [], "revalidar quita el problema")
        return plan, problem

    def test_an_ideology_the_government_does_not_allow(self):
        # council solo admite socialistas: AAA_conservative no vale y AAA_socialist sí.
        game, project = self.open(mod_files={ALAND: GAME_FILES[ALAND] + LIBERAL + SOCIALIST,
                                             AAA: history("AAA_conservative", "council")})
        plan, problem = self.fix(project, "ruling_party_ideology_not_allowed")
        self.assertEqual(problem.args["suggestion"], "AAA_socialist")
        [change] = plan.changes
        self.assertEqual((str(change.rel), change.action), (AAA, ACTION_MODIFY))
        self.assertIn("-ruling_party = AAA_conservative # elegido a mano", change.diff)
        self.assertIn("+ruling_party = AAA_socialist # elegido a mano", change.diff)
        spec = FIXES["set_ruling_party"]
        self.assertFalse(spec.safe, "cambia un valor elegido por el usuario: pide confirmación")
        self.assertEqual(spec.label(problem, "es"),
                         "Poner AAA_socialist como partido gobernante de AAA (en vez de AAA_conservative)")
        self.assertEqual(spec.label(problem, "en"),
                         "Make AAA_socialist the ruling party of AAA (instead of AAA_conservative)")
        project.ws.undo()
        self.assertEqual(len(project_problems(project, "ruling_party_ideology_not_allowed")), 1)

    def test_a_party_not_active_at_the_start_date(self):
        aland = GAME_FILES[ALAND].replace("end_date = 2000.1.1", "end_date = 1835.1.1") + LIBERAL
        game, project = self.open(mod_files={ALAND: aland, AAA: history("AAA_conservative")})
        plan, problem = self.fix(project, "ruling_party_inactive")
        self.assertEqual(problem.args["suggestion"], "AAA_liberal")
        self.assertIn("+ruling_party = AAA_liberal # elegido a mano", plan.changes[0].diff)

    def test_without_a_valid_party_the_fix_says_so(self):
        game, project = self.open(mod_files={AAA: history("AAA_conservative", "council")})
        [problem] = project_problems(project, "ruling_party_ideology_not_allowed")
        self.assertEqual(problem.args["suggestion"], "", "el país no tiene ningún partido que el consejo admita")
        with self.assertRaises(FixError) as raised:
            plan_fix("set_ruling_party", problem, project)
        self.assertEqual(raised.exception.code, "not_applicable")


if __name__ == "__main__":
    unittest.main()
