"""Generador del descriptor .mod (wizard §14.1, criterio 8 de la iteración 2): bytes, edición sin pérdidas,
problemas del formulario, propuestas de carpeta y «Nuevo mod».

Las pruebas que escriben a través del diario o renderizan sobre un descriptor existente necesitan el núcleo
real (``core/project/journal``, ``serializer.render_checked``): hasta la integración se omiten con su motivo.
"""

import codecs
import difflib
import string
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _fake_project import implemented  # noqa: E402
from _layers import build_layers, descriptor_bytes  # noqa: E402
from vic2studio.core import modcheck  # noqa: E402
from vic2studio.core.clausewitz import Severity, parse, parse_file, render_checked, to_source  # noqa: E402
from vic2studio.core.modfile import (  # noqa: E402
    DESCRIPTOR_FOLDER_RESERVED,
    DESCRIPTOR_FOLDER_TAKEN,
    DESCRIPTOR_NAME_DUPLICATE,
    DESCRIPTOR_USER_DIR_EMPTY,
    FIELD_NEWLINE,
    FIELD_QUOTE,
    NEW_CODES,
    REPLACE_PATH_EMPTY,
    SKELETON_FOLDERS,
    DescriptorFieldError,
    DescriptorProblemsError,
    DescriptorSpec,
    ModDescriptor,
    apply_descriptor,
    create_mod_skeleton,
    descriptor_problems,
    read_descriptor,
    render_descriptor,
    sanitize_folder,
    taken_folders,
    template_files,
)
from vic2studio.core.project.journal import SaveTransaction  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "shago_mod_min"
RENDER_CHECKED = implemented(render_checked)
JOURNAL = implemented(SaveTransaction.__init__, SaveTransaction.commit) and hasattr(SaveTransaction, "add_folder")
NEEDS_RENDER = "necesita serializer.render_checked (agente A, integración de la iteración 2)"
NEEDS_JOURNAL = "necesita core/project/journal con SaveTransaction.add_folder (agente A, integración)"


def codes(issues) -> list[str]:
    return [issue.code for issue in issues]


class RenderTests(unittest.TestCase):
    def test_golden_shago_mod(self):
        """Criterio 8: el descriptor canónico de VSM es byte a byte el del usuario."""
        self.assertEqual(render_descriptor(DescriptorSpec("Shago Mod", "VSM", "VSM")), (FIXTURE / "VSM.mod").read_bytes())

    def test_dark_age_mod_in_cp1252_with_crlf(self):
        data = render_descriptor(DescriptorSpec("Dark Age Mod", "DAM", "DAM"))
        self.assertEqual(data, b'name = "Dark Age Mod"\r\npath = "mod/DAM"\r\nuser_dir = "DAM"\r\n')
        lines = data.split(b"\r\n")
        self.assertEqual(lines[-1], b"", "termina en CRLF")
        self.assertNotIn(b"\n", b"".join(lines), "ningún LF suelto")
        result = parse(data.decode("cp1252"))
        self.assertEqual((result.document.get_text("path"), result.document.get_text("user_dir")), ("mod/DAM", "DAM"))

    def test_accents_are_written_in_cp1252(self):
        data = render_descriptor(DescriptorSpec("Guerra del Ñandú", "GDN"))
        self.assertIn("Ñandú".encode("cp1252"), data)
        self.assertNotIn("Ñandú".encode("utf-8"), data)
        self.assertNotIn(b"user_dir", data, "sin user_dir no se escribe la línea")

    def test_replace_paths_and_dependencies(self):
        data = render_descriptor(DescriptorSpec("A", "A", "A", ("history/pops", "history/units"), ("Base Mod",)))
        self.assertEqual(data, b'name = "A"\r\npath = "mod/A"\r\nuser_dir = "A"\r\nreplace_path = "history/pops"\r\n'
                               b'replace_path = "history/units"\r\ndependencies = { "Base Mod" }\r\n')

    def test_values_that_cannot_be_written(self):
        for spec, (code, field) in (
            (DescriptorSpec('Con "comillas"', "A"), (FIELD_QUOTE, "name")),
            (DescriptorSpec("A", "a\nb"), (FIELD_NEWLINE, "path")),
            (DescriptorSpec("A", "A", "x\ry"), (FIELD_NEWLINE, "user_dir")),
            (DescriptorSpec("A", "A", replace_paths=('a"b',)), (FIELD_QUOTE, "replace_path")),
            (DescriptorSpec("A", "A", dependencies=('Otro "mod"',)), (FIELD_QUOTE, "dependencies")),
        ):
            with self.subTest(spec=spec), self.assertRaises(DescriptorFieldError) as ctx:
                render_descriptor(spec)
            self.assertEqual((ctx.exception.code, ctx.exception.params["field"]), (code, field))

    def test_spec_round_trip_from_the_user_descriptor(self):
        descriptor = read_descriptor(FIXTURE / "VSM.mod")
        spec = DescriptorSpec.from_descriptor(descriptor)
        self.assertEqual(spec, DescriptorSpec("Shago Mod", "VSM", "VSM"))
        self.assertEqual(spec.path, "mod/VSM")
        self.assertEqual(render_descriptor(spec), (FIXTURE / "VSM.mod").read_bytes())
        self.assertEqual(spec.fields().path, "mod/VSM")
        self.assertEqual(DescriptorSpec("A", "").fields().path, "", "sin carpeta no hay path a medias")

    @unittest.skipUnless(RENDER_CHECKED, NEEDS_RENDER)
    def test_render_over_an_existing_descriptor_keeps_the_rest(self):
        text = '# Mod del usuario\r\nname = "Shago Mod"\r\npath = "mod/VSM"\r\npicture = "thumb.png"\r\n' \
               'archive = "mod/vsm.zip"\r\n'
        existing = parse(text)
        before = to_source(existing.document)
        data = render_descriptor(DescriptorSpec("Shago Mod 2", "VSM", "VSM"), existing)
        out = data.decode("cp1252")
        self.assertTrue(out.startswith('# Mod del usuario\r\nname = "Shago Mod 2"\r\n'), out)
        self.assertIn('picture = "thumb.png"', out)
        self.assertIn('archive = "mod/vsm.zip"', out, "archive no es del formulario: se conserva")
        self.assertIn('user_dir = "VSM"', out)
        self.assertEqual(to_source(existing.document), before, "el documento original no cambia")

    @unittest.skipUnless(RENDER_CHECKED, NEEDS_RENDER)
    def test_render_over_utf16_writes_cp1252(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "Leon.mod"
            file.write_bytes(codecs.BOM_UTF16_LE + '# copia\r\nname = "León"\r\npath = "mod/Leon"\r\n'.encode("utf-16-le"))
            data = render_descriptor(DescriptorSpec("León", "Leon", "Leon"), parse_file(file))
        self.assertEqual(data, '# copia\r\nname = "León"\r\npath = "mod/Leon"\r\nuser_dir = "Leon"\r\n'.encode("cp1252"))


class ApplyTests(unittest.TestCase):
    """``apply_descriptor``: lo que hace el formulario sobre el CST vivo (sin el disco)."""

    TEXT = '# Mi mod\r\nname = "Shago Mod"   # el nombre\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n' \
           'picture = "thumb.png"\r\nreplace_path = "history/pops"\r\n'

    def test_only_the_changed_lines_differ(self):
        result = parse(self.TEXT)
        changed = apply_descriptor(result.document, DescriptorSpec("Shago Mod", "VSM", "VSM_2", ("history/pops",)))
        self.assertTrue(changed)
        after = to_source(result.document)
        diff = [line for line in difflib.ndiff(self.TEXT.splitlines(), after.splitlines()) if line[:1] in "+-"]
        self.assertEqual(diff, ['- user_dir = "VSM"', '+ user_dir = "VSM_2"'])
        self.assertIn("# el nombre", after)
        self.assertIn('picture = "thumb.png"', after, "las claves que el formulario no conoce se conservan")

    def test_no_change_is_reported_as_such(self):
        result = parse(self.TEXT)
        self.assertFalse(apply_descriptor(result.document, DescriptorSpec("Shago Mod", "VSM", "VSM", ("history/pops",))))
        self.assertEqual(to_source(result.document), self.TEXT)

    def test_lists_and_removed_fields(self):
        result = parse(self.TEXT)
        apply_descriptor(result.document, DescriptorSpec("Shago Mod", "VSM", "", (), ("Base",)))
        after = to_source(result.document)
        self.assertNotIn("user_dir", after)
        self.assertNotIn("replace_path", after)
        self.assertIn('dependencies = { "Base" }', after)

    def test_invalid_values_leave_the_document_untouched(self):
        result = parse(self.TEXT)
        with self.assertRaises(DescriptorFieldError):
            apply_descriptor(result.document, DescriptorSpec("Shago Mod", "VSM", "VSM", ('a"b',)))
        self.assertEqual(to_source(result.document), self.TEXT)


class SanitizeTests(unittest.TestCase):
    def test_dark_age_mod(self):
        self.assertEqual(sanitize_folder("Dark Age Mod"), ["DAM", "Dark_Age_Mod"])

    def test_accents_and_symbols_become_ascii(self):
        self.assertEqual(sanitize_folder("Guerra del Ñandú: ¡1861!"), ["GDN1", "Guerra_del_Nandu_1861"])
        self.assertEqual(sanitize_folder("Shago"), ["Shago"])
        self.assertEqual(sanitize_folder("¡¿?!"), [])
        self.assertEqual(sanitize_folder(""), [])

    def test_taken_and_windows_names_get_a_number(self):
        self.assertEqual(sanitize_folder("Dark Age Mod", taken=frozenset({"dam"})), ["DAM2", "Dark_Age_Mod"])
        self.assertEqual(sanitize_folder("Dark Age Mod", taken=frozenset({"DAM", "dam2", "dark_age_mod"})),
                         ["DAM3", "Dark_Age_Mod_2"])
        self.assertEqual(sanitize_folder("Con"), ["Con2"], "CON es un dispositivo de Windows")
        self.assertEqual(sanitize_folder("Lpt 1"), ["L1", "Lpt_1"])
        self.assertEqual(sanitize_folder("Com Port 1"), ["CP1", "Com_Port_1"])

    def test_proposals_are_valid_folders(self):
        for name in ("Dark Age Mod", "Ñandú", "a.b c", "  x  ", "CON NUL", "Mod 2", "aux"):
            for proposal in sanitize_folder(name):
                with self.subTest(name=name, proposal=proposal):
                    self.assertRegex(proposal, r"^[A-Za-z0-9_]+$")
                    found = codes(descriptor_problems(DescriptorSpec(name, proposal, proposal), None))
                    self.assertNotIn(DESCRIPTOR_FOLDER_RESERVED, found)


class ProblemsTests(unittest.TestCase):
    def setUp(self):
        self.layers = build_layers(game={"history/provinces/a/1 - A.txt": "owner = AAA\r\n"},
                                   mod={"common/countries.txt": "X = 1\r\n"}, mod_name="VSM",
                                   descriptor=descriptor_bytes("Shago Mod", "VSM", "VSM"))
        self.addCleanup(self.layers.cleanup)
        self.game = self.layers.game_root

    def problems(self, spec, **kwargs):
        kwargs.setdefault("descriptor_file", self.layers.descriptor)
        return descriptor_problems(spec, self.game, **kwargs)

    def test_a_good_descriptor_has_no_problems(self):
        self.assertEqual(self.problems(DescriptorSpec("Shago Mod", "VSM", "VSM"), mod_root=self.layers.mod_root), [])

    def test_check_descriptor_codes_are_reused(self):
        found = self.problems(DescriptorSpec("", "Otro", "VSM"), mod_root=self.layers.mod_root)
        self.assertEqual(codes(found), ["descriptor_no_name", "descriptor_other_folder"])
        found = self.problems(DescriptorSpec("Shago Mod", "Falta", "VSM"))
        self.assertEqual(codes(found), ["descriptor_missing_folder"])
        self.assertTrue(all(issue.message("es") != issue.message("en") for issue in found))

    def test_user_dir_empty_is_info(self):
        found = self.problems(DescriptorSpec("Shago Mod", "VSM", ""), mod_root=self.layers.mod_root)
        self.assertEqual([(i.code, i.severity) for i in found], [(DESCRIPTOR_USER_DIR_EMPTY, Severity.INFO)])

    def test_name_duplicate_ignores_the_own_descriptor(self):
        (self.game / "mod" / "Copia.mod").write_bytes(descriptor_bytes("shago mod", "Copia"))
        found = self.problems(DescriptorSpec("Shago Mod", "VSM", "VSM"), mod_root=self.layers.mod_root)
        self.assertEqual([(i.code, i.severity, i.args["file"]) for i in found],
                         [(DESCRIPTOR_NAME_DUPLICATE, Severity.WARNING, "Copia.mod")])
        (self.game / "mod" / "Copia.mod").unlink()
        self.assertEqual(self.problems(DescriptorSpec("Shago Mod", "VSM", "VSM"), mod_root=self.layers.mod_root), [])

    def test_windows_reserved_and_taken_folders(self):
        found = descriptor_problems(DescriptorSpec("Nuevo", "CON", "CON"), self.game, creating=True)
        self.assertIn(DESCRIPTOR_FOLDER_RESERVED, codes(found))
        found = descriptor_problems(DescriptorSpec("Nuevo", "vsm", "vsm"), self.game, creating=True)
        self.assertEqual(codes(found), [DESCRIPTOR_FOLDER_TAKEN], "sin distinguir mayúsculas, como Windows")
        self.assertEqual(descriptor_problems(DescriptorSpec("Nuevo", "DAM", "DAM"), self.game, creating=True), [])
        for bad in ("a:b", "nombre.", "x?", "NUL.txt"):
            with self.subTest(folder=bad):
                found = descriptor_problems(DescriptorSpec("Nuevo", bad, "u"), self.game, creating=True)
                self.assertIn(DESCRIPTOR_FOLDER_RESERVED, codes(found))
        self.assertEqual(taken_folders(self.game), frozenset({"vsm"}))

    def test_replace_path_left_empty(self):
        found = self.problems(DescriptorSpec("Shago Mod", "VSM", "VSM", ("history/provinces",)),
                              mod_root=self.layers.mod_root)
        self.assertEqual([(i.code, i.args) for i in found], [(REPLACE_PATH_EMPTY, {"replace_path": "history/provinces"})])
        self.assertEqual(self.problems(DescriptorSpec("Shago Mod", "VSM", "VSM", ("Common",)),
                                       mod_root=self.layers.mod_root), [], "la carpeta se busca sin mayúsculas")
        (self.layers.mod_root / "history" / "provinces").mkdir(parents=True)
        (self.layers.mod_root / "history" / "provinces" / "x.txt.bak").write_bytes(b"")
        self.assertEqual(codes(self.problems(DescriptorSpec("Shago Mod", "VSM", "VSM", ("history/provinces",)),
                                             mod_root=self.layers.mod_root)), [REPLACE_PATH_EMPTY],
                         "una copia .bak no cuenta")
        # Al crear, el mod nace vacío: solo una plantilla con esa carpeta lo evita.
        spec = DescriptorSpec("Nuevo", "DAM", "DAM", ("common",))
        self.assertEqual(codes(descriptor_problems(spec, self.game, creating=True)), [REPLACE_PATH_EMPTY])
        self.assertEqual(descriptor_problems(spec, self.game, creating=True, template=self.layers.mod_root), [])

    def test_unwritable_values_are_problems_with_their_own_message(self):
        found = self.problems(DescriptorSpec('Sha"go', "VSM", "VSM"), mod_root=self.layers.mod_root)
        self.assertEqual(codes(found), [FIELD_QUOTE])
        self.assertIsInstance(found[0].diagnostic, DescriptorFieldError)
        self.assertIn("name", found[0].message("es"))
        self.assertNotEqual(found[0].message("es"), found[0].message("en"))

    def test_new_codes_have_texts_in_both_languages(self):
        for code in NEW_CODES:
            with self.subTest(code=code):
                es, en = modcheck.MESSAGES["es"][code], modcheck.MESSAGES["en"][code]
                self.assertNotEqual(es, en)
                fields = {name for _, name, _, _ in string.Formatter().parse(es) if name}
                self.assertEqual(fields, {name for _, name, _, _ in string.Formatter().parse(en) if name})

    def test_without_game_nothing_of_the_mod_folder_is_checked(self):
        self.assertEqual(descriptor_problems(DescriptorSpec("A", "A", "A"), None), [])
        self.assertEqual(codes(descriptor_problems(DescriptorSpec("A", "A", "A", ("map",)), None)), [],
                         "sin juego ni mod no se sabe qué hay en la carpeta")


class SkeletonTests(unittest.TestCase):
    def setUp(self):
        self.layers = build_layers(game={"common/countries.txt": "A = 1\r\n"}, mod_name="VSM",
                                   descriptor=descriptor_bytes("Shago Mod", "VSM", "VSM"))
        self.addCleanup(self.layers.cleanup)
        self.game = self.layers.game_root

    def test_template_files_skip_project_folder_backups_and_root_descriptors(self):
        template = self.layers.base / "Plantilla"
        for rel in ("common/a.txt", "common/a.txt.bak", ".vic2studio/journal/x.json", "Plantilla.mod",
                    "history/b.txt", "events/.e.txt.123.tmp"):
            (template / rel).parent.mkdir(parents=True, exist_ok=True)
            (template / rel).write_bytes(b"x")
        self.assertEqual([rel for rel, _ in template_files(template)], ["common/a.txt", "history/b.txt"])

    def test_problems_stop_the_creation_before_writing(self):
        before = self.layers.tree(self.game)
        with self.assertRaises(DescriptorProblemsError) as ctx:
            create_mod_skeleton(self.game, DescriptorSpec("Otro", "vsm", "vsm"))
        self.assertIsInstance(ctx.exception, ValueError)
        self.assertEqual(codes(ctx.exception.issues), [DESCRIPTOR_FOLDER_TAKEN])
        self.assertEqual(self.layers.tree(self.game), before, "no se escribe nada")

    @unittest.skipUnless(JOURNAL, NEEDS_JOURNAL)
    def test_new_mod_creates_folders_and_descriptor(self):
        game_before = self.layers.tree(self.game)
        descriptor = create_mod_skeleton(self.game, DescriptorSpec("Dark Age Mod", "DAM", "DAM"))
        self.assertIsInstance(descriptor, ModDescriptor)
        self.assertEqual((descriptor.name, descriptor.path, descriptor.user_dir), ("Dark Age Mod", "mod/DAM", "DAM"))
        self.assertEqual((self.game / "mod" / "DAM.mod").read_bytes(),
                         b'name = "Dark Age Mod"\r\npath = "mod/DAM"\r\nuser_dir = "DAM"\r\n')
        for folder in SKELETON_FOLDERS:
            self.assertTrue((self.game / "mod" / "DAM" / folder).is_dir(), folder)
        after = self.layers.tree(self.game)
        new = {rel for rel in after if rel not in game_before}
        self.assertTrue(all(rel.startswith(("mod/DAM/", "mod/DAM.mod")) for rel in new), new)
        self.assertFalse([rel for rel in new if "/journal/" in rel], "el diario se cierra")

    @unittest.skipUnless(JOURNAL, NEEDS_JOURNAL)
    def test_template_is_copied_inside(self):
        template = self.layers.base / "Plantilla Mod"
        (template / "common").mkdir(parents=True)
        (template / "common" / "defines.lua").write_bytes(b"x = 1\r\n")
        create_mod_skeleton(self.game, DescriptorSpec("Con plantilla", "CP", "CP"), template=template)
        self.assertEqual((self.game / "mod" / "CP" / "common" / "defines.lua").read_bytes(), b"x = 1\r\n")


if __name__ == "__main__":
    unittest.main()
