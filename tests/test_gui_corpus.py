"""Suite de interfaces con vanilla (iteración 8, criterios 1, 2 y 4). Se omite sin corpus (``VIC2_CORPUS``).

- Criterio 1: los 59 ``.gui`` y los 66 ``.gfx`` se leen sin errores y cumplen sus esquemas (0 claves desconocidas y
  0 tipos que no encajan; las 8 claves repetidas de vanilla son la línea base declarada). Las texturas con la otra
  extensión se resuelven; las que faltan y los nombres repetidos salen como problemas heredados.
  ``Orientation``/``orientation`` y ``UPPERL_LEFT`` se reconocen.
- Criterio 2: mover un elemento de un ``.gui`` de vanilla cambia solo su línea ``position`` en la copia del mod.
- Criterio 4: la ventana de eventos de vanilla se compone a 1024×768 y a 1920×1080.

Nada de lo que leen estas pruebas se copia al repositorio: las imágenes se componen en memoria.
"""

from __future__ import annotations

import collections
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import copy_user_mod, user_mod, vanilla_root  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from vic2studio.core.clausewitz.diagnostics import Severity  # noqa: E402
from vic2studio.core.gui import GuiDocument, SpriteDB, WorkspaceSource, layout  # noqa: E402
from vic2studio.core.gui.render import GuiRenderer  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import parse_bytes  # noqa: E402
from vic2studio.core.schema import registry  # noqa: E402
from vic2studio.core.schema.record import Record, RecordRef  # noqa: E402
from vic2studio.core.validate import discover_rules  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

VANILLA_DUPLICATE_FIELDS = 8          # 4 buttonFont repetidos en wardeclaration.gui y 4 claves en metaserver.gui


@unittest.skipUnless(vanilla_root(), "requiere vanilla (VIC2_CORPUS o VIC2_GAME)")
class VanillaInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        discover_rules()
        cls.root = vanilla_root() / "interface"
        cls.gui = sorted(cls.root.glob("*.gui"))
        cls.gfx = sorted(cls.root.glob("*.gfx"))

    def test_criterion_1_every_file_complies_with_its_schema(self):
        self.assertEqual((len(self.gui), len(self.gfx)), (59, 66))
        schemas = [s for s in registry.all_schemas() if s.kind == "sprite" or s.kind.startswith("gui_")]
        self.assertEqual(len(schemas), 14)
        counts: collections.Counter = collections.Counter()
        problems: collections.Counter = collections.Counter()
        for path in [*self.gui, *self.gfx]:
            result = parse_bytes(path.read_bytes())
            self.assertFalse([d for d in result.diagnostics if d.severity is Severity.ERROR], path.name)
            rel = VPath.of(f"interface/{path.name}")
            for schema in schemas:
                if not schema.layout.touches(rel):
                    continue
                for ident, block, entry in schema.layout.entries(result.document, rel):
                    counts[schema.kind] += 1
                    record = Record(schema, RecordRef(schema.kind, ident, rel), SimpleNamespace(rel=rel), block,
                                    entry=entry)
                    for problem in record.issues():
                        problems[problem.code] += 1
        self.assertEqual(counts["sprite"], 1264)
        self.assertEqual(counts["gui_window"], 523)
        self.assertEqual(counts["gui_instant_text"], 1591)
        self.assertEqual(problems["unknown_field"], 0)
        self.assertEqual(problems["bad_type"], 0)
        self.assertEqual(dict(problems), {"duplicate_field": VANILLA_DUPLICATE_FIELDS})

    def test_criterion_1_textures_duplicates_and_orientations(self):
        source = DirectorySource(vanilla_root())
        db = SpriteDB.build(source)
        self.assertEqual(len(db.all()), 1264)
        self.assertEqual(sum(1 for s in db.all() if s.alternative_extension), 432)
        self.assertEqual(len(db.missing_textures()), 26)
        self.assertEqual(len(db.duplicates()), 13)
        unknown = []
        both = set()
        for path in self.gui:
            document = parse_bytes(path.read_bytes()).document
            for element in GuiDocument(document).elements():
                entry = element.block.find("orientation", ignore_case=True)
                if entry is not None:
                    both.add(entry.key.text)
            for window in GuiDocument(document).windows():
                warnings: list = []
                layout(window, (1024, 768), warnings=warnings)
                unknown.extend(value for _, value in warnings)
        self.assertTrue({"Orientation", "orientation"} <= both)
        self.assertEqual(unknown, ["UPPERL_LEFT", "UPPERL_LEFT"])

    def test_criterion_4_the_event_window_renders_at_both_resolutions(self):
        source = DirectorySource(vanilla_root())
        renderer = GuiRenderer.from_source(source)
        doc = GuiDocument(source.document(VPath.of("interface/event_country_window.gui")))
        window, *loose = doc.windows()
        for screen in ((1024, 768), (1920, 1080)):
            image, rects = renderer.render(doc, window, screen, extra=loose, overrides={"title": "Prueba"})
            self.assertEqual(image.size, screen)
            box = rects[window.uid]
            self.assertTrue(0 <= box.x and box.right <= screen[0] and 0 <= box.y and box.bottom <= screen[1])


@unittest.skipUnless(vanilla_root() and user_mod(), "requiere vanilla y la copia del mod del usuario")
class VanillaDragTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_criterion_2_moving_changes_only_the_position_line_of_the_mod_copy(self):
        mod = copy_user_mod(self, "decisions")
        project = Project.open(vanilla_root(), mod)
        self.addCleanup(project.close, discard=True)
        rel = VPath.of("interface/event_country_window.gui")
        source = WorkspaceSource(project.ws)
        with project.ws.transaction("undo.gui_move", element="event_images"):
            handle = project.ws.open(rel)
            project.ws.touch(handle)
            doc = GuiDocument(source.document(rel))
            element = doc.find("Event_Country_Window/event_images")
            x, y = element.position
            doc.set_position(element, x + 7, y - 3)
        project.save()
        original = (vanilla_root() / "interface" / "event_country_window.gui").read_bytes().split(b"\n")
        copy = (mod / "interface" / "event_country_window.gui").read_bytes().split(b"\n")
        self.assertEqual(len(original), len(copy))
        changed = [(a, b) for a, b in zip(original, copy) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertIn(b"position", changed[0][1])
        self.assertIn(f"x= {x + 7} y = {y - 3}".encode(), changed[0][1])


class DirectorySource:
    """Los archivos de una carpeta como ``GuiSource`` (rutas sin mayúsculas), solo para leer el corpus."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files = {p.relative_to(root).as_posix().lower(): p.relative_to(root).as_posix()
                      for p in root.rglob("*") if p.is_file()}

    def rels(self, folder: str, pattern: str) -> list[VPath]:
        import fnmatch

        found = []
        for key, rel in sorted(self.files.items()):
            parent, _, name = key.rpartition("/")
            if parent == folder.lower() and fnmatch.fnmatch(name, pattern.lower()):
                found.append(VPath.of(rel))
        return found

    def find(self, rel: VPath) -> VPath | None:
        found = self.files.get(str(rel).lower())
        return None if found is None else VPath.of(found)

    def read(self, rel: VPath) -> bytes | None:
        found = self.find(rel)
        return None if found is None else (self.root / str(found)).read_bytes()

    def document(self, rel: VPath):
        data = self.read(rel)
        return None if data is None else parse_bytes(data).document


if __name__ == "__main__":
    unittest.main()
