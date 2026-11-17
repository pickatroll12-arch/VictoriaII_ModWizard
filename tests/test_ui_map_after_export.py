"""El editor de mapa (``MapSession``) tras «Exportar al mod» sin guardar y tras editar a mano ``default.map``: las
reglas (el mar) salen de la vista efectiva, con lo sin guardar, y los hechos del mapa se ponen al día cuando el
índice termina de reindexar lo exportado. Sobre el minijuego del mapa (inventado), con el taller en el mismo
proceso, como ``test_ui_mapforge``."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_entity import WAIT_MS  # noqa: E402
from test_ui_map import MapCase  # noqa: E402
from test_ui_mapforge import ForgeCase  # noqa: E402

from vic2studio.core.map.bmp import read_bmp  # noqa: E402
from vic2studio.core.map.default_map import DefaultMap  # noqa: E402
from vic2studio.core.mapforge import export as ex  # noqa: E402
from vic2studio.ui.session_map import RASTER_READY  # noqa: E402

OLD_SEA = {9, 10, 11, 12}                  # el sea_starts del minijuego del mapa


def map_ready(case, *, rounds: int = 4):
    """Espera a que el editor de mapa termine con todo: ráster listo, índice al día y hechos sin tarea en marcha, del
    tamaño del ráster. Varias vueltas: cuando el índice se pone al día, los hechos pueden rehacerse una vez más."""
    session = case.window.session
    ms = session.map

    def settled():
        return (ms.raster_state == RASTER_READY and ms.raster is not None and not session._index_behind()
                and not ms._facts_runner.is_busy() and ms.facts is not None
                and ms.facts.size == ms.raster.max_id + 1)

    for _ in range(rounds):
        case.assertTrue(_qt.wait_until(settled, WAIT_MS), (ms.raster_state, session._index_behind()))
        _qt.process_events(150)
    case.assertTrue(settled())
    return ms


def facts_sea(ms) -> set[int]:
    facts = ms.facts
    return {pid for pid in range(1, facts.size) if facts.is_sea[pid]}


class MapAfterExportTests(ForgeCase):
    def export(self) -> tuple[int, int]:
        """Genera un mundo pequeño en el taller y lo exporta al mod sin guardar; da la forma del BMP exportado."""
        self.window.show_page("forge")
        self.idle()
        self.small_world()
        self.wiz.go("review")
        self.idle()
        self.assertTrue(self.wiz.review.export_button.isEnabled(), [i.code for i in self.wiz.review.blocking()])
        touched = self.wiz.export()
        self.assertIn("map/provinces.bmp", touched)
        self.assertIn("map/default.map", touched)
        self.window.show_page("map:world")
        ws = self.window.session.project.ws
        return read_bmp(bytes(ws.peek("map/provinces.bmp").model)).pixels.shape[:2]

    def exported_sea(self) -> set[int]:
        """El ``sea_starts`` del ``default.map`` exportado (sin guardar: el documento vivo)."""
        handle = self.window.session.project.ws.peek("map/default.map")
        self.assertTrue(handle.dirty)
        return set(DefaultMap(handle.model.document).sea_starts())

    def assert_owners_match_the_history(self, label: str) -> None:
        """El dueño de cada provincia en los hechos del mapa es el de su historia viva en la fecha de trabajo."""
        session = self.window.session
        ms = map_ready(self)
        facts, provinces, date = ms.facts, ms.provinces, session.working_date
        got = {pid: facts.name("tags", int(facts.owner[pid])) for pid in range(1, facts.size)}
        want = {pid: str(provinces.get(pid, "owner", date).value or "").upper() for pid in range(1, facts.size)}
        self.assertTrue(any(want.values()), f"{label}: el mundo tiene dueños")
        wrong = {pid: (got[pid], want[pid]) for pid in got if got[pid] != want[pid]}
        self.assertEqual(wrong, {}, f"{label}: (en el mapa, en la historia)")

    def test_the_map_editor_knows_the_exported_sea_before_saving(self):
        """Regresión: las reglas del editor de mapa salían solo del disco (``GameRules.from_vfs``). Tras exportar
        sin guardar, el ráster era el nuevo pero el mar, el del ``default.map`` viejo: los hechos pintaban de tierra el
        mar del mundo nuevo, ``Provinces`` (cacheada con esas reglas) dejaba a la brocha poner dueño a provincias de
        mar, y seguía así tras guardar hasta volver a abrir el proyecto."""
        self.open_forge()
        self.window.show_page("map:world")
        session = self.window.session
        ms = map_ready(self)
        old_shape = ms.raster.ids.shape
        self.assertEqual(facts_sea(ms), OLD_SEA)
        # La ficha de la provincia ya usó ``provinces`` (con el mar de antes) antes de exportar.
        self.assertEqual({pid for pid in range(1, ms.raster.max_id + 1) if ms.provinces.is_sea(pid)}, OLD_SEA)
        self.export()
        ms = map_ready(self)
        sea = self.exported_sea()
        count = ms.raster.max_id
        self.assertEqual(count, self.wiz.final.raster.count, "el ráster del mundo exportado")
        self.assertTrue(sea and sea != OLD_SEA and max(sea) <= count, sea)
        self.assertEqual(ms.rules().sea, frozenset(sea), "las reglas tienen el default.map sin guardar")
        self.assertEqual(facts_sea(ms), sea, "los hechos pintan el mar del mundo exportado")
        provinces = ms.provinces
        self.assertEqual({pid for pid in range(1, count + 1) if provinces.is_sea(pid)}, sea,
                         "la brocha sabe qué es mar en el mundo exportado")
        # Un trazo de brocha sobre todo el mapa no pone dueño a ninguna provincia de mar.
        date = session.working_date
        painted = ms.paint(range(1, count + 1), "owner", "CCC")
        self.assertGreater(painted, 0)
        self.assertEqual([pid for pid in sorted(sea) if provinces.get(pid, "owner", date).value is not None], [],
                         "provincias de mar con dueño")
        self.assertEqual([pid for pid in sorted(sea) if ms.facts.owner[pid]], [])
        session.undo()
        # Guardado: sigue sabiendo qué es mar (antes, ``Provinces`` se quedaba con las reglas de antes de exportar).
        report = session.save()
        self.assertTrue(report.ok, report)
        ms = map_ready(self)
        self.assertEqual(facts_sea(ms), sea, "tras guardar")
        self.assertEqual({pid for pid in range(1, count + 1) if ms.provinces.is_sea(pid)}, sea, "tras guardar")
        # Deshecha la exportación vuelve el mar de antes, con el mapa de antes.
        step = session.undo()
        self.assertEqual(step.label, ex.UNDO_EXPORT)
        _qt.process_events(50)
        self.assertTrue(_qt.wait_until(lambda: ms.raster is not None and ms.raster.ids.shape == old_shape, WAIT_MS))
        ms = map_ready(self)
        self.assertEqual(ms.rules().sea, frozenset(OLD_SEA))
        self.assertEqual(facts_sea(ms), OLD_SEA, "deshecha la exportación")
        self.assertEqual({pid for pid in range(1, ms.raster.max_id + 1) if ms.provinces.is_sea(pid)}, OLD_SEA)

    def test_the_owners_on_the_map_are_the_exported_ones_after_export_undo_and_redo(self):
        """Regresión: con el editor de mapa a la vista, exportar (o deshacer y rehacer la exportación) recargaba el
        ráster, que llega pronto (caché), y los hechos se hacían con una copia del índice de antes de la
        reindexación (``REINDEX_DELAY_MS`` después). Nadie los rehacía al ponerse al día el índice: decenas de
        provincias del mapa nuevo salían sin dueño o con el de antes."""
        self.open_forge()
        self.window.show_page("map:world")
        map_ready(self)
        self.assert_owners_match_the_history("antes de exportar")
        new_shape = self.export()
        self.assertEqual(map_ready(self).raster.ids.shape, new_shape)
        self.assert_owners_match_the_history("tras exportar")
        session = self.window.session
        self.assertEqual(session.undo().label, ex.UNDO_EXPORT)
        self.assertTrue(_qt.wait_until(lambda: session.map.raster is not None
                                       and session.map.raster.ids.shape != new_shape, WAIT_MS))
        self.assert_owners_match_the_history("deshecha")
        self.assertEqual(session.redo().label, ex.UNDO_EXPORT)
        self.assertTrue(_qt.wait_until(lambda: session.map.raster is not None
                                       and session.map.raster.ids.shape == new_shape, WAIT_MS))
        self.assert_owners_match_the_history("rehecha")


class MapRulesEditedByHandTests(MapCase):
    def test_editing_sea_starts_changes_the_sea_of_the_map_before_saving(self):
        """Regresión: el mar del editor de mapa (los hechos y la brocha) sigue al ``default.map`` sin guardar, sin
        recargar el ráster, y vuelve al deshacer."""
        self.open_map()
        session = self.window.session
        ms = map_ready(self)
        self.assertFalse(ms.provinces.is_sea(8))
        self.assertEqual(facts_sea(ms), OLD_SEA)
        raster = ms.raster
        old = self.text_of("map/default.map").encode("cp1252")
        new = old.replace(b"sea_starts = {\r\n\t9 ", b"sea_starts = {\r\n\t8 9 ")
        self.assertNotEqual(new, old)
        ws = session.project.ws
        with session.edit("pending.undo_revert", name="map/default.map"):
            ws.replace_text(ws.open("map/default.map"), new)
        ms = map_ready(self)
        self.assertIs(ms.raster, raster, "el ráster no cambia")
        self.assertEqual(ms.rules().sea, frozenset(OLD_SEA | {8}))
        self.assertTrue(ms.provinces.is_sea(8), "la brocha ya no pinta la 8")
        self.assertEqual(facts_sea(ms), OLD_SEA | {8})
        self.assertEqual(ms.paint([7, 8], "owner", "BBB"), 1, "la 7, no la 8")
        session.undo()
        session.undo()
        ms = map_ready(self)
        self.assertFalse(ms.provinces.is_sea(8))
        self.assertEqual(facts_sea(ms), OLD_SEA)


class MapBeforeTheIndexTests(ForgeCase):
    def test_the_facts_are_built_when_the_index_arrives_after_the_raster(self):
        """Regresión: con el ráster listo antes que el índice (la sala Mapa abierta nada más abrir un proyecto
        grande), los hechos no se hacían nunca: ``_on_index_state`` comparaba el método ``index_state`` con
        ``READY``."""
        import threading

        from _minigame import build_map_minigame

        self.game = build_map_minigame(clean=True)
        self.addCleanup(self.game.cleanup)
        window = self.make_window()
        session = window.session
        gate = threading.Event()
        self.addCleanup(gate.set)
        engine = session._index_engine
        real_build = engine.build

        def gated_build(*args, **kwargs):
            gate.wait(WAIT_MS / 1000)
            return real_build(*args, **kwargs)

        engine.build = gated_build
        page = window.page("project")
        page.set_game_path(self.game.game_root)
        page.set_mod_path(self.game.mod_root)
        self.assertTrue(_qt.wait_until(lambda: session.project is not None, WAIT_MS))
        self.window = window
        window.show_page("map:world")
        ms = session.map
        self.assertTrue(_qt.wait_until(lambda: ms.raster_state == RASTER_READY, WAIT_MS), ms.raster_error)
        self.assertEqual(session.index_state(), "busy")
        self.assertIsNone(ms.facts, "sin índice todavía no hay hechos")
        gate.set()
        self.assertTrue(_qt.wait_until(lambda: session.index_state() == "ready", WAIT_MS))
        self.assertTrue(_qt.wait_until(lambda: ms.facts is not None, 3000), "llegó el índice y no hay hechos")
        self.assertEqual(facts_sea(map_ready(self)), OLD_SEA)


if __name__ == "__main__":
    unittest.main()
