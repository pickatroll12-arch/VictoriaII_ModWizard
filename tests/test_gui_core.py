"""Suite de interfaces, núcleo (iteración 8): modelo de ``.gui``, catálogo de sprites, anclajes, fuentes, texturas,
renderizador, imágenes, sprites nuevos, esquemas y reglas, todo con el minijuego (datos inventados).

Las pruebas con vanilla están en ``test_gui_corpus.py``.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from _interface_fixtures import FONT_ATLAS, FONT_FNT, INTERFACE_FILES, PANEL_GUI  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.clausewitz.serializer import render_checked  # noqa: E402
from vic2studio.core.gfx.dds import read_dds  # noqa: E402
from vic2studio.core.gfx.images import (  # noqa: E402
    FORMAT_DDS,
    FORMAT_TGA,
    common_size,
    encode_image,
    fit_image,
    image_size,
    slot,
    slot_of,
)
from vic2studio.core.gui import (  # noqa: E402
    BMFont,
    GuiDocument,
    Rect,
    SpriteDB,
    TextureCache,
    WorkspaceSource,
    anchor_point,
    element_path,
    frame_box,
    layout,
    local_position,
    nine_slice,
)
from vic2studio.core.gui.render import SCREENS, GuiRenderer  # noqa: E402
from vic2studio.core.gui.sprites import SpriteError, import_picture, new_sprite  # noqa: E402
from vic2studio.core.index.builder import build_index  # noqa: E402
from vic2studio.core.locsync import LocSync  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for, parse_bytes  # noqa: E402
from vic2studio.core.schema import Entities  # noqa: E402
from vic2studio.core.schema.record import RecordRef  # noqa: E402
from vic2studio.core.validate import Validator, build_context, compute_baseline  # noqa: E402
from vic2studio.core.validate.context import game_only_snapshot  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

PANEL = "interface/mg_panel.gui"
EVENT_GUI = "interface/event_country_window.gui"
CODES = {"gui_sprite_missing", "texture_missing", "sprite_duplicate", "gui_orientation_unknown",
         "gui_named_element_removed"}


def parse(text: str):
    return parse_bytes(text.encode("cp1252"))


class InterfaceProjectCase(unittest.TestCase):
    """El minijuego con los archivos de interfaz como archivos del juego, abierto con ``Project``."""

    mod_files: dict = {}

    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame(game_files=INTERFACE_FILES, mod_files=dict(self.mod_files))
        self.addCleanup(self.game.cleanup)
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(self.project.close, discard=True)
        self.source = WorkspaceSource(self.project.ws)

    def entities(self) -> Entities:
        index = build_index(self.project.vfs.snapshot(), None, {})
        loc = LocSync(self.project.ws, self.project.vfs, prefix=self.project.settings.prefix)
        return Entities(self.project.ws, index, loc)

    def text(self, rel: str) -> str:
        handle = self.project.ws.peek(VPath.of(rel)) or self.project.ws.open(VPath.of(rel))
        return codec_for(handle.kind).snapshot(handle.model).decode("cp1252")

    def problems(self, codes=CODES, baseline=True):
        snap = self.project.vfs.snapshot()
        overrides = {h.rel: codec_for(h.kind).snapshot(h.model) if not h.deleted else None
                     for h in self.project.ws.dirty()}
        ctx = build_context(snap, build_index(snap, None, overrides), overrides)
        base = None
        if baseline:
            game = game_only_snapshot(snap)
            base = compute_baseline(build_context(game, build_index(game, None), game_only=True))
        return list(Validator(ctx, baseline=base).validate(codes=set(codes)).problems)


# --- modelo -------------------------------------------------------------------------------------------------


class GuiModelTests(unittest.TestCase):
    def test_windows_elements_and_paths(self):
        doc = GuiDocument(parse(PANEL_GUI).document)
        [window] = doc.windows()
        self.assertEqual((window.name, window.type, window.size, window.position), ("mg_panel_window", "windowtype",
                                                                                     (300, 200), (20, 30)))
        names = [element_path(el) for el in doc.elements()]
        self.assertIn("mg_panel_window/mg_inner/mg_label", names)
        self.assertEqual(doc.find("MG_PANEL_WINDOW/mg_inner/MG_LABEL").text, "Hola", "sin mayúsculas")
        label = doc.find("mg_panel_window/mg_inner/mg_label")
        self.assertEqual(label.size, (90, 20), "una caja de texto mide maxWidth × maxHeight")
        with self.assertRaises(KeyError):
            doc.find("mg_panel_window/nada")

    def test_orientation_is_read_whatever_its_case(self):
        doc = GuiDocument(parse(PANEL_GUI).document)
        self.assertEqual(doc.find("mg_panel_window/mg_close").orientation, "UPPER_RIGHT", "orientation")
        self.assertEqual(doc.find("mg_panel_window/mg_ghost").orientation, "LOWER_LEFT", "Orientation sin comillas")
        self.assertEqual(doc.find("mg_panel_window/mg_alt_icon").orientation, "UPPERL_LEFT")

    def test_moving_changes_only_the_position_line(self):
        result = parse(PANEL_GUI)
        doc = GuiDocument(result.document)
        doc.set_position(doc.find("mg_panel_window/mg_inner"), 151, 98)
        before, after = PANEL_GUI.split("\r\n"), render_checked(result).decode("cp1252").split("\r\n")
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(before), len(after))
        self.assertEqual(changed, [("\t\t\tposition = { x = 150 y = 100 }", "\t\t\tposition = { x = 151 y = 98 }")])

    def test_resize_sprite_and_text_keep_the_key_spelling(self):
        result = parse(PANEL_GUI)
        doc = GuiDocument(result.document)
        doc.set_size(doc.find("mg_panel_window/mg_inner/mg_label"), 120, 24)
        doc.set_sprite(doc.find("mg_panel_window/mg_close"), "GFX_mg_alt")
        doc.set_orientation(doc.find("mg_panel_window/mg_ghost"), "LOWER_RIGHT")
        text = render_checked(result).decode("cp1252")
        self.assertIn("\t\t\t\tmaxWidth = 120\r\n\t\t\t\tmaxHeight = 24\r\n", text)
        self.assertIn('quadTextureSprite = "GFX_mg_alt"', text)
        self.assertIn("\t\t\tOrientation = LOWER_RIGHT\r\n", text, "la clave conserva su grafía")


class LayoutTests(unittest.TestCase):
    def test_anchors(self):
        parent = Rect(10, 20, 100, 50)
        self.assertEqual(anchor_point("UPPER_LEFT", parent), (10, 20))
        self.assertEqual(anchor_point("lower_right", parent), (110, 70))
        self.assertEqual(anchor_point("CENTER", parent), (60, 45))
        self.assertEqual(anchor_point("CENTER_DOWN", parent), (60, 70))
        self.assertEqual(anchor_point("UPPERL_LEFT", parent), (10, 20), "desconocida: arriba a la izquierda")
        self.assertEqual(local_position("UPPER_RIGHT", parent, (100, 30)), (-10, 10))

    def test_layout_of_a_window_and_its_warnings(self):
        doc = GuiDocument(parse(PANEL_GUI).document)
        [window] = doc.windows()
        warnings: list = []
        rects = layout(window, (1024, 768), warnings=warnings)
        self.assertEqual(rects[window.uid], Rect(20, 30, 300, 200))
        close = doc.find("mg_panel_window/mg_close")
        self.assertEqual((rects[close.uid].x, rects[close.uid].y), (20 + 300 - 40, 30 + 8))
        ghost = doc.find("mg_panel_window/mg_ghost")
        self.assertEqual((rects[ghost.uid].x, rects[ghost.uid].y), (30, 30 + 200 - 30))
        label = doc.find("mg_panel_window/mg_inner/mg_label")
        self.assertEqual(rects[label.uid], Rect(20 + 150 + 5, 30 + 100 + 5, 90, 20))
        self.assertEqual([(el.name, value) for el, value in warnings], [("mg_alt_icon", "UPPERL_LEFT")])


class TextureAndFontTests(unittest.TestCase):
    def test_frames_and_nine_slice(self):
        self.assertEqual(frame_box((300, 30), 3, 1), (100, 0, 200, 30))
        source = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
        source.paste((0, 0, 255, 255), (4, 4, 12, 12))
        stretched = nine_slice(source, (4, 4), (40, 20))
        self.assertEqual(stretched.size, (40, 20))
        self.assertEqual(stretched.getpixel((1, 1)), (255, 0, 0, 255), "las esquinas no se estiran")
        self.assertEqual(stretched.getpixel((20, 10)), (0, 0, 255, 255))

    def test_texture_cache_reads_dds_and_tga_and_remembers_failures(self):
        reads: list = []

        def read(rel):
            reads.append(str(rel))
            return INTERFACE_FILES.get(str(rel)) if str(rel) != "broken.dds" else b"DDS roto"

        cache = TextureCache(read)
        self.assertEqual(cache.size_of("gfx/interface/mg_event_bg.dds"), (480, 400))
        self.assertEqual(cache.size_of("gfx/interface/mg_option.tga"), (600, 30))
        self.assertIsNone(cache.get("broken.dds"))
        self.assertIsNone(cache.get("broken.dds"))
        self.assertEqual(reads.count("broken.dds"), 1, "lo ilegible se recuerda")

    def test_bmfont_measures_wraps_and_aligns(self):
        atlas = Image.fromarray(FONT_ATLAS, "RGBA")
        font = BMFont.load(FONT_FNT, atlas)
        self.assertEqual(font.line_height, 12)
        self.assertEqual(font.text_width("AB"), 14)
        self.assertEqual(font.text_width("AV"), 13, "kerning")
        image = font.render("uno dos tres", max_width=30, align="right")
        self.assertEqual(image.size[0], 30)
        self.assertGreaterEqual(image.size[1], 24, "parte en varias líneas")
        tinted = font.render("§RA§!", color_codes={"R": (255, 0, 0)}, color=(255, 255, 255))
        red = np.asarray(tinted)[..., :3][np.asarray(tinted)[..., 3] > 0]
        self.assertTrue((red == [255, 0, 0]).all(), "el código §R tiñe el carácter")


# --- imágenes -----------------------------------------------------------------------------------------------


class ImageTests(unittest.TestCase):
    def test_slots_and_sizes(self):
        self.assertEqual((slot("event").format, slot("event").size), (FORMAT_TGA, (521, 203)))
        self.assertEqual((slot("decision").format, slot("decision").size), (FORMAT_DDS, (95, 95)))
        self.assertEqual(slot_of("gfx/pictures/events/x.tga").key, "event")
        self.assertIsNone(slot_of("map/terrain/x.dds"))
        headers = [INTERFACE_FILES["gfx/interface/mg_event_bg.dds"][:128],
                   INTERFACE_FILES["gfx/interface/mg_no_image.tga"][:128],
                   INTERFACE_FILES["gfx/interface/mg_no_image.tga"][:128]]
        self.assertEqual(image_size(headers[0]), (480, 400))
        self.assertEqual(common_size(headers), (420, 160))

    def test_fit_modes_and_encoding_reread(self):
        source = Image.new("RGBA", (200, 100), (10, 20, 30, 255))
        self.assertEqual(fit_image(source, (95, 95)).size, (95, 95))
        contained = fit_image(source, (100, 100), mode="contain")
        self.assertEqual(contained.getpixel((50, 2))[3], 0, "contain deja bandas transparentes")
        dds = encode_image(fit_image(source, (95, 95)), FORMAT_DDS)
        self.assertEqual(read_dds(dds).rgba.shape, (95, 95, 4))
        tga = encode_image(source, FORMAT_TGA)
        with Image.open(io.BytesIO(tga)) as reread:
            self.assertEqual(reread.size, (200, 100))


# --- catálogo de sprites, renderizador y creación --------------------------------------------------------


class SpriteDbTests(InterfaceProjectCase):
    def test_textures_resolve_with_the_other_extension_and_duplicates_are_listed(self):
        db = SpriteDB.build(self.source)
        alt = db.get("gfx_mg_alt")
        self.assertEqual(str(alt.resolved), "gfx/interface/mg_alt.dds")
        self.assertTrue(alt.alternative_extension)
        self.assertEqual([s.name for s in db.missing_textures()], ["GFX_mg_lost"])
        self.assertEqual(sorted(db.duplicates()), ["GFX_MG_TWICE"])
        self.assertEqual(db.get("GFX_mg_panel").border, (8, 8))
        self.assertEqual(db.get("GFX_mg_panel").size, (64, 64))
        self.assertEqual(db.get("GFX_event_country_button").frames, 3)
        uses = db.usages("GFX_event_country_button")
        self.assertEqual(sorted({str(rel) for rel, _ in uses}), [EVENT_GUI, PANEL])

    def test_renderer_draws_both_screens_with_and_without_game_art(self):
        renderer = GuiRenderer.from_source(self.source)
        doc = GuiDocument(self.source.document(VPath.of(EVENT_GUI)))
        window, *loose = doc.windows()
        for screen in ((1024, 768), (1920, 1080)):
            image, rects = renderer.render(doc, window, screen, extra=loose, overrides={"title": "Título"})
            self.assertEqual(image.size, screen)
            box = rects[window.uid]
            self.assertEqual((box.w, box.h), (480, 400))
            self.assertEqual((box.x, box.y), (screen[0] // 2 - 260, screen[1] // 2 - 250))
            pixel = image.getpixel((box.x + 2, box.y + 2))[:3]
            self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(pixel, (214, 196, 150))), f"fondo del .gui: {pixel}")
        self.assertIn((1920, 1080), SCREENS)
        procedural = GuiRenderer.from_source(self.source, game_art=False)
        image, rects = procedural.render(doc, window, (1024, 768), crop=True)
        self.assertEqual(image.size, (480, 400))
        self.assertNotEqual(image.getpixel((40, 100))[:3], (90, 120, 150), "sin arte del juego: procedural")

    def test_a_cornered_sprite_is_nine_sliced_to_the_element(self):
        renderer = GuiRenderer.from_source(self.source)
        doc = GuiDocument(self.source.document(VPath.of(PANEL)))
        frame = doc.find("mg_panel_window/mg_frame")
        self.assertEqual(renderer.sprite_size("GFX_mg_panel"), (64, 64))
        picture = renderer.element_image(frame, (120, 90))
        self.assertEqual(picture.size, (120, 90))

    def test_new_sprite_writes_a_dds_and_its_sprite_type_in_one_undo_step(self):
        entities = self.entities()
        history = len(self.project.ws.history())
        image = Image.new("RGBA", (64, 32), (0, 128, 255, 255))
        created = new_sprite(self.project.ws, entities, "GFX_mg_new", image, frames=2, prefix="TESTMOD")
        self.assertEqual(str(created.texture), "gfx/interface/TESTMOD/GFX_mg_new.dds")
        self.assertEqual(str(created.gfx), "interface/testmod_studio.gfx")
        self.assertEqual(len(self.project.ws.history()), history + 1)
        self.assertEqual(self.project.ws.history()[0][0], "undo.new_sprite")
        data = bytes(self.project.ws.peek(created.texture).model)
        self.assertEqual(read_dds(data).rgba.shape, (32, 64, 4), "Pillow/el lector relee el DDS")
        self.assertEqual(Image.open(io.BytesIO(data)).size, (64, 32), "Pillow lo abre")
        text = self.text(str(created.gfx))
        self.assertIn("spriteTypes = {", text)
        self.assertIn('name = "GFX_mg_new"', text)
        self.assertIn('texturefile = "gfx/interface/TESTMOD/GFX_mg_new.dds"', text)
        self.assertIn("noOfFrames = 2", text)
        record = entities.open(RecordRef("sprite", "GFX_mg_new", created.gfx))
        self.assertEqual(record.get("noOfFrames"), 2)
        self.assertEqual(SpriteDB.build(self.source).get("GFX_mg_new").resolved, created.texture)
        with self.assertRaises(SpriteError) as taken:
            new_sprite(self.project.ws, entities, "gfx_MG_new", image, prefix="TESTMOD")
        self.assertEqual(taken.exception.code, "taken")
        with self.assertRaises(SpriteError) as frames:
            new_sprite(self.project.ws, entities, "GFX_three", image, frames=3, prefix="TESTMOD")
        self.assertEqual(frames.exception.code, "bad_frames")
        self.project.ws.undo()
        self.assertIsNone(SpriteDB.build(self.source).get("GFX_mg_new"))

    def test_a_cornered_sprite_gets_its_border(self):
        entities = self.entities()
        created = new_sprite(self.project.ws, entities, "GFX_mg_box", Image.new("RGBA", (32, 32)),
                             kind="corneredTileSpriteType", border=(6, 5), prefix="TESTMOD")
        text = self.text(str(created.gfx))
        self.assertIn("corneredTileSpriteType = {", text)
        self.assertRegex(text, r"borderSize = \{\s*x = 6\s*y = 5\s*\}")

    def test_import_picture_fits_the_family_size(self):
        rel = import_picture(self.project.ws, slot("decision"), "mg_harbour", Image.new("RGB", (300, 120)), (95, 95))
        self.assertEqual(str(rel), "gfx/pictures/decisions/mg_harbour.dds")
        data = bytes(self.project.ws.peek(rel).model)
        self.assertEqual(read_dds(data).rgba.shape, (95, 95, 4))
        self.assertEqual(self.project.ws.history()[0][0], "undo.import_picture")


# --- esquemas ----------------------------------------------------------------------------------------------


class SchemaTests(InterfaceProjectCase):
    def test_sprites_and_elements_are_records_without_problems(self):
        entities = self.entities()
        sprites = {item.ref.ident for item in entities.list("sprite")}
        self.assertTrue({"GFX_mg_panel", "GFX_event_country_bg", "GFX_mg_alt"} <= sprites)
        panel = entities.open(RecordRef("sprite", "GFX_mg_panel", VPath.of("interface/mg_event.gfx")))
        self.assertEqual(panel.entity_key, "corneredTileSpriteType")
        self.assertEqual(panel.issues(), [])
        buttons = {(str(item.rel), item.ref.ident) for item in entities.list("gui_button")}
        self.assertIn((PANEL, "mg_panel_window/mg_close"), buttons)
        self.assertIn((EVENT_GUI, "Event_Country_OptionButton"), buttons)
        windows = {item.ref.ident for item in entities.list("gui_window")}
        self.assertIn("mg_panel_window/mg_inner", windows, "también las anidadas")
        for kind, ident, rel in (("gui_window", "mg_panel_window", PANEL), ("gui_icon", "mg_panel_window/mg_alt_icon",
                                                                           PANEL)):
            record = entities.open(RecordRef(kind, ident, VPath.of(rel)))
            self.assertEqual(record.issues(), [], ident)

    def test_editing_an_element_from_its_record_copies_the_game_file_and_changes_one_line(self):
        entities = self.entities()
        record = entities.open(RecordRef("gui_icon", "mg_panel_window/mg_alt_icon", VPath.of(PANEL)))
        self.assertEqual(record.get("orientation"), "UPPERL_LEFT", "Orientation sin mayúsculas")
        with self.project.ws.transaction("edit"):
            record.set("orientation", "UPPER_LEFT")
        before = PANEL_GUI.split("\r\n")
        after = self.text(PANEL).split("\r\n")
        self.assertEqual([(a, b) for a, b in zip(before, after) if a != b],
                         [('\t\t\tOrientation = "UPPERL_LEFT"', '\t\t\tOrientation = "UPPER_LEFT"')])
        self.project.save()
        self.assertTrue(self.game.mod(PANEL).is_file(), "guardar escribe la copia entera en el mod")

    def test_elements_are_not_created_from_the_studio(self):
        from vic2studio.core.schema.record import InvalidIdentError

        with self.assertRaises(InvalidIdentError):
            with self.project.ws.transaction("new"):
                self.entities().create("gui_button", "nuevo", None)


# --- reglas ------------------------------------------------------------------------------------------------


class RuleTests(InterfaceProjectCase):
    def by_code(self, problems):
        found: dict[str, list] = {}
        for problem in problems:
            found.setdefault(problem.code, []).append(problem)
        return found

    def test_game_problems_are_inherited(self):
        problems = self.by_code(self.problems())
        self.assertEqual([dict(p.args)["sprite"] for p in problems["texture_missing"]], ["GFX_mg_lost"])
        self.assertEqual([dict(p.args)["sprite"] for p in problems["gui_sprite_missing"]], ["GFX_mg_nowhere"])
        self.assertEqual([dict(p.args)["sprite"] for p in problems["sprite_duplicate"]], ["GFX_MG_TWICE"])
        self.assertEqual([dict(p.args)["orientation"] for p in problems["gui_orientation_unknown"]], ["UPPERL_LEFT"])
        self.assertNotIn("gui_named_element_removed", problems)
        self.assertTrue(all(p.inherited for group in problems.values() for p in group), "son del juego")


class RemovedElementTests(InterfaceProjectCase):
    mod_files = {PANEL: PANEL_GUI.replace('\t\tguiButtonType = {\r\n\t\t\tname = "mg_close"', '\t\tguiButtonType = {\r\n\t\t\tname = "mg_close_renamed"')}

    def test_a_mod_copy_without_a_named_element_is_warned(self):
        problems = [p for p in self.problems({"gui_named_element_removed"}) if not p.inherited]
        self.assertEqual([(str(p.rel), dict(p.args)["element"]) for p in problems],
                         [(PANEL, "mg_panel_window/mg_close")])


if __name__ == "__main__":
    unittest.main()
