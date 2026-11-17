"""La vista viva sigue a las ``replace_path`` del descriptor: las que añade «Exportar al mod» (y las que se quitan al
deshacerla), las que se escriben a mano en el descriptor y las que cambian en el disco fuera del Studio.

Antes, la VFS fijaba sus carpetas reemplazadas al abrir el proyecto y nada las cambiaba hasta volver a abrirlo: tras
exportar (y aun tras guardar) la historia de provincias del juego seguía contando. Donde el juego tiene la historia de
un id con otro nombre de archivo que la exportada, las dos eran efectivas y ganaba la del juego: el editor de mapa
enseñaba los dueños viejos, la validación daba ``province_history_duplicate`` y la brocha volvía a abrir (y, al
guardar, a copiar al mod) el archivo del juego.

Sobre el minijuego del mapa (inventado), con el taller en el mismo proceso, como ``test_ui_map_after_export``. Su
juego tiene ``history/provinces/north/1 - Capital.txt`` (dueño AAA) y la exportación escribe la historia de la 1 con
otro nombre; el mod trae su propia copia de la 5, que la exportación manda a la papelera; su descriptor no tiene
``replace_path``.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_entity import WAIT_MS  # noqa: E402
from test_ui_mapforge import ForgeCase  # noqa: E402

from _minigame import build_map_minigame  # noqa: E402
from vic2studio.core.domain.province import UNDO_PAINT  # noqa: E402
from vic2studio.core.index.model import KIND_PROVINCE_HISTORY  # noqa: E402
from vic2studio.core.mapforge import export as ex  # noqa: E402
from vic2studio.core.modfile import (  # noqa: E402
    DescriptorSpec,
    apply_descriptor,
    descriptor_from_result,
    read_descriptor,
)
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.vfs.model import LayerKind  # noqa: E402
from vic2studio.core.vfs.paths import DESCRIPTOR_REL, folder_key  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD  # noqa: E402
from vic2studio.ui.session_map import RASTER_READY  # noqa: E402

GAME_CAPITAL = "history/provinces/north/1 - Capital.txt"      # dueño AAA en el juego
MOD_QUINTA = "history/provinces/south/5 - Quinta.txt"         # copia del mod (dueño CCC); la exportación la tira
MOD_FILES = {MOD_QUINTA: "owner = CCC\r\ncontroller = CCC\r\nadd_core = CCC\r\n"}
REPLACED = tuple(folder_key(f) for f in ex.REPLACED_FOLDERS)
HISTORY_RE = re.compile(r"history/provinces/[^/]+/(\d+)\D[^/]*\.txt$", re.IGNORECASE)
OWNER_RE = re.compile(rb"^\s*owner\s*=\s*([A-Za-z0-9]{3})", re.MULTILINE)


def owners_in(files: dict[str, bytes]) -> dict[int, str]:
    """Dueño de cada provincia según los BYTES de sus archivos de historia (no a través de la vista efectiva);
    ``""`` si su historia no tiene ``owner``. Más de un archivo para un id es un fallo de la prueba."""
    found: dict[int, list[str]] = {}
    for rel, data in files.items():
        match = HISTORY_RE.match(rel)
        if match is None:
            continue
        owner = OWNER_RE.search(data)
        found.setdefault(int(match.group(1)), []).append(owner.group(1).decode().upper() if owner else "")
    duplicated = {pid: owners for pid, owners in found.items() if len(owners) > 1}
    assert not duplicated, f"historias repetidas: {duplicated}"
    return {pid: owners[0] for pid, owners in found.items()}


def map_ready(case, *, rounds: int = 4):
    """Espera a que el editor de mapa termine con todo: ráster listo, índice al día y hechos sin tarea en marcha, del
    tamaño del ráster (varias vueltas: al ponerse al día el índice, los hechos pueden rehacerse una vez más)."""
    session = case.window.session
    ms = session.map

    def settled():
        return (ms.raster_state == RASTER_READY and ms.raster is not None and not session._index_behind()
                and session.index_state() == "ready" and not ms._facts_runner.is_busy() and ms.facts is not None
                and ms.facts.size == ms.raster.max_id + 1)

    for _ in range(rounds):
        case.assertTrue(_qt.wait_until(settled, WAIT_MS), (ms.raster_state, session._index_behind()))
        _qt.process_events(150)
    case.assertTrue(settled())
    return ms


def facts_owners(ms) -> dict[int, str]:
    facts = ms.facts
    return {pid: facts.name("tags", int(facts.owner[pid])) or "" for pid in range(1, facts.size)}


class ReplacePathsCase(ForgeCase):
    def open_forge(self):
        """Como ``ForgeCase.open_forge``, con la copia de la 5 en el mod."""
        self.game = build_map_minigame(clean=True, mod_files=MOD_FILES)
        self.addCleanup(self.game.cleanup)
        window = self.make_window()
        window.exec_dialog = self.dialogs
        window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        page = window.page("project")
        page.set_game_path(self.game.game_root)
        page.set_mod_path(self.game.mod_root)
        self.window = window
        self.wait_open()
        self.wiz = window.show_page("forge").wizard
        self.idle()

    def wait_open(self):
        session, window = self.window.session, self.window
        self.assertTrue(_qt.wait_until(lambda: session.project is not None and session.index_state() == "ready"
                                       and session.texts_ready() and not window.is_busy(), WAIT_MS))

    @property
    def session(self):
        return self.window.session

    def export(self) -> list[str]:
        self.window.show_page("forge")
        self.idle()
        self.small_world()
        self.wiz.go("review")
        self.idle()
        # «Los archivos del mod bajo las carpetas reemplazadas van a la papelera» (la copia de la 5): confirmado.
        for box in self.wiz.review._confirm_boxes.values():
            box.setChecked(True)
        _qt.process_events(20)
        self.assertTrue(self.wiz.review.export_button.isEnabled(), [i.code for i in self.wiz.review.blocking()])
        touched = self.wiz.export()
        self.assertIn("map/provinces.bmp", touched)
        self.window.show_page("map:world")
        return touched

    def live_bytes(self, rels) -> dict[str, bytes]:
        """Bytes de los documentos vivos de ``rels`` (lo que se guardará), sin pasar por la vista efectiva."""
        ws = self.session.project.ws
        out = {}
        for rel in rels:
            handle = ws.peek(rel)
            if handle is not None and not handle.deleted:
                out[str(handle.rel)] = codec_for(handle.kind).snapshot(handle.model)
        return out

    def mod_disk_histories(self) -> dict[str, bytes]:
        root = self.game.mod_root
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in (root / "history" / "provinces").rglob("*.txt")}

    def assert_map_owners(self, want: dict[int, str], label: str) -> None:
        """El dueño de cada provincia de tierra en los hechos del mapa es el de los bytes de su historia; las
        provincias sin historia (las de mar), sin dueño."""
        ms = map_ready(self)
        got = facts_owners(ms)
        expected = {pid: want.get(pid, "") for pid in got}
        wrong = {pid: (got[pid], expected[pid]) for pid in got if got[pid] != expected[pid]}
        self.assertEqual(wrong, {}, f"{label}: (en el mapa, en los bytes de la historia)")
        self.assertTrue(any(expected.values()), f"{label}: el mundo tiene dueños")


class ExportReplacePathsTests(ReplacePathsCase):
    def test_the_live_view_follows_the_replace_paths_of_the_export(self):
        """Regresión (ALTO): ``apply_export`` añade los ``replace_path`` al documento del descriptor, pero la VFS los
        fijaba al abrir el proyecto. Hasta volver a abrirlo, la historia de provincias del juego seguía siendo
        efectiva: los dueños del juego en el mapa, ``province_history_duplicate`` en la validación y la brocha sobre
        el archivo del juego (que el guardado copiaba al mod, con dos historias para una provincia)."""
        self.open_forge()
        session = self.session
        project = session.project
        self.window.show_page("map:world")
        ms = map_ready(self)
        self.assertEqual(project.vfs.replace_paths, ())
        self.assertEqual(facts_owners(ms)[1], "AAA")
        self.assertEqual(facts_owners(ms)[5], "CCC", "la copia del mod")
        # La ficha de la 1 ya abrió la historia del juego antes de exportar (un documento limpio en el Workspace).
        self.assertEqual(str(ms.provinces.record(1).ref.rel), GAME_CAPITAL)
        self.assertIsNotNone(project.ws.peek(GAME_CAPITAL))

        touched = self.export()
        self.assertIn(MOD_QUINTA, touched)
        self.assertTrue(project.ws.peek(MOD_QUINTA).deleted, "la copia del mod va a la papelera")
        exported = set(self.live_bytes(rel for rel in touched if HISTORY_RE.match(rel)))   # sin la papelera
        rel_of = {int(HISTORY_RE.match(rel).group(1)): rel for rel in exported}
        self.assertEqual(len(rel_of), len(exported), "una historia exportada por provincia")
        self.assertNotEqual(rel_of[1].casefold(), GAME_CAPITAL.casefold(), "otro nombre que el del juego")
        self.assertNotEqual(rel_of[5].casefold(), MOD_QUINTA.casefold())

        # Sin guardar: la VFS ya oculta lo que oculta el descriptor exportado.
        self.assertEqual(set(project.vfs.replace_paths), set(REPLACED))
        self.assertIsNone(project.vfs.resolve(GAME_CAPITAL), "el juego ya no carga su historia")
        self.assertEqual([str(e.rel) for e in project.vfs.list("history/provinces", "*.txt")
                          if e.layer.kind is LayerKind.GAME], [])
        want = owners_in(self.live_bytes(exported))
        self.assert_map_owners(want, "tras exportar sin guardar")
        index = session.index
        self.assertEqual([str(s.rel) for s in index.effective(KIND_PROVINCE_HISTORY, "1")], [rel_of[1]])
        self.assertEqual([str(s.rel) for s in index.effective(KIND_PROVINCE_HISTORY, "5")], [rel_of[5]])
        self.assertEqual(str(ms.provinces.record(1).ref.rel), rel_of[1])
        self.assertEqual(str(ms.provinces.record(5).ref.rel), rel_of[5])

        # La brocha edita la historia exportada; ni la del juego ni la copia tirada a la papelera vuelven.
        new_owner = "BBB" if want[1] != "BBB" else "CCC"
        self.assertEqual(ms.paint([1, 5], "owner", new_owner), 2)
        _qt.process_events(50)
        ws = project.ws
        self.assertTrue(ws.peek(MOD_QUINTA).deleted, "la copia del mod sigue en la papelera")
        game_handle = ws.peek(GAME_CAPITAL)
        self.assertTrue(game_handle is None or not game_handle.dirty, "el archivo del juego no se toca")
        painted = owners_in(self.live_bytes([rel_of[1], rel_of[5]]))
        self.assertEqual(painted, {1: new_owner, 5: new_owner})
        self.assertEqual({pid: facts_owners(map_ready(self))[pid] for pid in (1, 5)}, {1: new_owner, 5: new_owner})
        self.assertEqual(session.undo().label, UNDO_PAINT)
        self.assert_map_owners(want, "deshecho el trazo")

        # Deshacer la exportación devuelve la vista de antes; rehacerla, la de después.
        shape = ms.raster.ids.shape
        self.assertEqual(session.undo().label, ex.UNDO_EXPORT)
        self.assertEqual(project.vfs.replace_paths, ())
        self.assertIsNotNone(project.vfs.resolve(GAME_CAPITAL))
        self.assertTrue(_qt.wait_until(lambda: ms.raster is not None and ms.raster.ids.shape != shape, WAIT_MS))
        ms = map_ready(self)
        self.assertEqual((facts_owners(ms)[1], facts_owners(ms)[5]), ("AAA", "CCC"), "deshecha la exportación")
        self.assertEqual(str(ms.provinces.record(5).ref.rel), MOD_QUINTA)
        self.assertEqual(session.redo().label, ex.UNDO_EXPORT)
        self.assertEqual(set(project.vfs.replace_paths), set(REPLACED))
        self.assertTrue(_qt.wait_until(lambda: ms.raster is not None and ms.raster.ids.shape == shape, WAIT_MS))
        self.assert_map_owners(want, "rehecha la exportación")

        # Guardado: el mod tiene una sola historia por provincia (la exportada) y la vista no cambia.
        report = session.save()
        self.assertTrue(report.ok, report)
        self.assertEqual(set(project.vfs.replace_paths), set(REPLACED))
        on_disk = self.mod_disk_histories()
        self.assertEqual(set(on_disk), exported)
        self.assertEqual(owners_in(on_disk), want)
        on_disk_descriptor = read_descriptor(self.game.descriptor)
        self.assertEqual({folder_key(p) for p in on_disk_descriptor.replace_paths}, set(REPLACED))
        self.assert_map_owners(want, "tras guardar")

        # Volver a abrir da lo mismo.
        mod_root = self.game.mod_root
        session.close_project()
        _qt.process_events(50)
        session.open_project(self.game.game_root, mod_root)
        self.assertTrue(_qt.wait_until(lambda: session.project is not None and session.index_state() == "ready"
                                       and session.texts_ready() and not self.window.is_busy(), WAIT_MS))
        self.assertEqual(set(session.project.vfs.replace_paths), set(REPLACED))
        self.window.show_page("map:world")
        self.assert_map_owners(want, "al volver a abrir")

    def test_validation_after_the_export_has_no_duplicated_province_histories(self):
        """Regresión: con la historia del juego aún efectiva, la validación de la exportación sin guardar daba un
        ``province_history_duplicate`` por cada provincia cuya historia el juego tiene con otro nombre."""
        self.open_forge()
        session = self.session
        self.export()
        map_ready(self)
        self.assertTrue(session.validate())
        self.assertTrue(_qt.wait_until(lambda: not session.is_validating(), WAIT_MS))
        self.assertEqual(session.validation_state(), "ready", session.validation_error())
        duplicated = [(p.code, str(p.rel)) for p in session.problems(inherited=True)
                      if p.code == "province_history_duplicate"]
        self.assertEqual(duplicated, [])

    def test_an_alliance_added_in_diplomacy_after_the_export_does_not_bring_back_the_game_ones(self):
        """Regresión (verificación final): una alianza añadida en Diplomacia antes de exportar se descarta («Descartar
        cambios») y el archivo del juego queda oculto por ``replace_path``. La que se añadía después en Diplomacia iba
        detrás de las del juego, y guardar las copiaba todas al mod."""
        alliances = "history/diplomacy/Alliances.txt"
        self.open_forge()
        diplomacy = self.window.show_page("war:diplomacy")
        _qt.process_events(50)
        self.assertEqual([(r.first, r.second) for r in diplomacy.relations], [("AAA", "CCC")])
        self.assertTrue(diplomacy.add_relation("alliance", "BBB", "CCC", "1836.1.1"))
        _qt.process_events(50)
        self.export()
        self.assertIn(ex.PlannedFile(alliances, ex.ACTION_DISCARD, "A", 0), self.wiz.review.plan)
        diplomacy = self.window.show_page("war:diplomacy")
        _qt.process_events(50)
        self.assertEqual(diplomacy.relations, [], "el juego ya no carga sus alianzas")
        first, second = sorted(self.wiz.final.entities.get("owners") or [])[:2]
        self.assertTrue(diplomacy.add_relation("alliance", first, second, "1836.1.1"))
        _qt.process_events(50)
        self.assertEqual([(r.first, r.second) for r in diplomacy.relations], [(first, second)])
        self.assertTrue(self.session.save().ok)
        _qt.process_events(100)
        saved = (self.game.mod_root / alliances).read_bytes()
        self.assertIn(first.encode(), saved)
        self.assertNotIn(b"1830.1.1", saved, "nada de las alianzas del juego en el mod")


class DescriptorReplacePathsTests(ReplacePathsCase):
    """Las ``replace_path`` que cambian sin el taller: a mano en el descriptor y fuera del Studio."""

    def edit_descriptor(self, replace_paths: tuple[str, ...]) -> None:
        session = self.session
        ws = session.project.ws
        with session.edit("descriptor.undo_edit", field="replace_path"):
            handle = ws.open(DESCRIPTOR_REL)
            spec = DescriptorSpec.from_descriptor(descriptor_from_result(self.game.descriptor, handle.model))
            ws.touch(handle)
            apply_descriptor(handle.model.document, DescriptorSpec(spec.name, spec.folder, spec.user_dir,
                                                                   replace_paths, spec.dependencies))

    def test_a_replace_path_written_by_hand_hides_the_game_files_until_undone(self):
        self.open_forge()
        session = self.session
        project = session.project
        self.window.show_page("map:world")
        ms = map_ready(self)
        self.assertEqual(str(ms.provinces.record(1).ref.rel), GAME_CAPITAL)
        builds = []
        ms.factsChanged.connect(lambda pids: builds.append(pids) if pids is None else None)
        self.edit_descriptor(("history/provinces",))
        self.assertEqual(project.vfs.replace_paths, ("HISTORY/PROVINCES",))
        self.assertIsNone(project.vfs.resolve(GAME_CAPITAL))
        self.assertIsNone(project.ws.peek(GAME_CAPITAL), "el documento limpio del juego oculto se suelta")
        self.assertIsNone(ms.provinces.record(1), "la 1 ya no tiene historia")
        ms = map_ready(self)
        self.assertEqual(session.index.effective(KIND_PROVINCE_HISTORY, "1"), [])
        owners = facts_owners(ms)
        self.assertEqual((owners[1], owners[5]), ("", "CCC"), "la copia del mod sigue contando")
        self.assertTrue(builds, "los hechos del mapa se rehacen (sin ráster nuevo, nadie más lo haría)")
        # Sin cambio de las carpetas (guardar), nada se rehace: ni textos, ni hechos, ni informe desfasado.
        texts = []
        session.textsChanged.connect(lambda: texts.append(1))
        builds.clear()
        report = session.save()
        self.assertTrue(report.ok, report)
        map_ready(self)
        self.assertEqual(project.vfs.replace_paths, ("HISTORY/PROVINCES",))
        self.assertEqual((texts, builds), ([], []), "guardar no cambia lo que oculta el descriptor")
        session.undo()
        self.assertEqual(project.vfs.replace_paths, ())
        ms = map_ready(self)
        self.assertEqual(facts_owners(ms)[1], "AAA")
        self.assertEqual(str(ms.provinces.record(1).ref.rel), GAME_CAPITAL)

    def change_on_disk(self, data: bytes, stamp: int) -> None:
        """Otro programa reescribe el descriptor (con otra fecha: la huella cambia aunque el tamaño no)."""
        descriptor = self.game.descriptor
        descriptor.write_bytes(data)
        os.utime(descriptor, ns=(stamp, stamp))

    def test_a_descriptor_changed_outside_the_studio_is_followed(self):
        """Otro programa cambia el descriptor: al recuperar el foco (``check_external_changes``) la vista lo sigue,
        como lo seguiría el juego. Abierto y limpio (la sala Proyecto lo abre), se recarga; sin abrir (la LRU lo
        soltó), se lee del disco."""
        self.open_forge()
        session = self.session
        project = session.project
        old = self.game.descriptor.read_bytes()
        replaced = old.rstrip(b"\r\n") + b'\r\nreplace_path = "history/provinces"\r\n'
        handle = project.ws.peek(DESCRIPTOR_REL)
        self.assertTrue(handle is not None and not handle.dirty)
        self.change_on_disk(replaced, 10**18)
        session.check_external_changes()
        _qt.process_events(50)
        self.assertEqual(project.vfs.replace_paths, ("HISTORY/PROVINCES",), "abierto y limpio")
        self.assertTrue(_qt.wait_until(lambda: session.index_state() == "ready" and not session._index_behind(),
                                       WAIT_MS))
        self.assertEqual(session.index.effective(KIND_PROVINCE_HISTORY, "1"), [])
        self.assertTrue(session.validate())
        self.assertTrue(_qt.wait_until(lambda: session.validation_state() == "ready", WAIT_MS))
        self.assertFalse(session.report_stale())
        project.ws._store.discard(DESCRIPTOR_REL)       # lo que hace la LRU con un documento limpio
        self.change_on_disk(old, 2 * 10**18)
        session.check_external_changes()
        _qt.process_events(50)
        self.assertEqual(project.vfs.replace_paths, (), "sin abrir")
        self.assertTrue(session.report_stale(), "el informe es de cuando el juego no cargaba su historia")
        self.assertTrue(_qt.wait_until(lambda: session.index_state() == "ready" and not session._index_behind(),
                                       WAIT_MS))
        self.assertEqual([str(s.rel) for s in session.index.effective(KIND_PROVINCE_HISTORY, "1")], [GAME_CAPITAL])
        # Otra vez sin cambios: nada se rehace.
        texts = []
        session.textsChanged.connect(lambda: texts.append(1))
        session.check_external_changes()
        _qt.process_events(50)
        self.assertEqual(texts, [])
        self.assertFalse(session._index_behind())

    def test_a_replace_path_on_localisation_changes_the_texts(self):
        """``replace_path = "localisation"`` escrito a mano oculta los CSV del juego: los textos efectivos (también
        los del buscador, que guardaba la base de antes) dejan de tenerlos, y vuelven al deshacer."""
        self.open_forge()
        session = self.session
        self.assertTrue(session.texts_ready())
        self.assertEqual(session._loc_for_search().lookup("conquer_land"), "Conquer land")
        texts = []
        session.textsChanged.connect(lambda: texts.append(1))
        self.edit_descriptor(("localisation",))
        _qt.process_events(50)
        self.assertEqual(session.project.vfs.replace_paths, ("LOCALISATION",))
        self.assertTrue(texts, "textsChanged")
        self.assertIsNone(session.locsync.text("conquer_land", "en"))
        self.assertIsNone(session._loc_for_search().lookup("conquer_land"), "el buscador tampoco lo tiene")
        self.assertEqual(session._loc_for_search().lookup("tst_reform"), "Reform", "los CSV del mod siguen")
        texts.clear()
        session.undo()
        _qt.process_events(50)
        self.assertTrue(texts)
        self.assertEqual(session._loc_for_search().lookup("conquer_land"), "Conquer land")


if __name__ == "__main__":
    unittest.main()
