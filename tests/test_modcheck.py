"""Descriptor ``.mod`` (core.modfile) y validación de un mod completo (core.modcheck), sin Qt."""

import codecs
import gc
import os
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import DEV_DIARY, corpus_roots, user_mod, user_mod_error_files  # noqa: E402
from vic2studio.core import modcheck  # noqa: E402
from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.core.clausewitz import Severity, parse_file, to_source, write_file  # noqa: E402
from vic2studio.core.csvloc import read_csv_file  # noqa: E402
from vic2studio.core.modcheck import (  # noqa: E402
    CHECK_FAILED,
    FOLDER_ERROR,
    KIND_CLAUSEWITZ,
    KIND_CSV,
    MESSAGES,
    NO_GAME_FOLDERS,
    READ_ERROR,
    STRAY_BOM,
    UNREADABLE_ENCODING,
    check_descriptor,
    check_file,
    check_mod,
    collect_files,
    file_kind,
    is_mod_root,
)
from vic2studio.core.modfile import (  # noqa: E402
    FIELD_NEWLINE,
    FIELD_QUOTE,
    INSIDE,
    SIBLING,
    DescriptorFieldError,
    ModDescriptor,
    find_descriptor,
    read_descriptor,
    write_descriptor,
)
from vic2studio.core.modfile import MESSAGES as DESCRIPTOR_MESSAGES  # noqa: E402


def write(path: Path, text: str, encoding: str = "cp1252") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding))
    return path


class DescriptorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_fields_lists_and_errors(self):
        file = write(self.root / "Big.mod", '# comentario\r\nname = "Gran Mod"\r\npath = "mod\\BigMod"\r\n'
                                            'user_dir = "Big"\r\nreplace_path = "history/pops"\r\n'
                                            'replace_path = "history/units"\r\ndependencies = { "A" "B" }\r\n')
        d = read_descriptor(file)
        self.assertEqual((d.name, d.path, d.user_dir), ("Gran Mod", "mod\\BigMod", "Big"))
        self.assertEqual(d.folder_name, "BigMod")
        self.assertEqual(d.replace_paths, ("history/pops", "history/units"))
        self.assertEqual(d.dependencies, ("A", "B"))
        self.assertEqual(d.errors, [])
        self.assertEqual(d.archive, "")
        broken = read_descriptor(write(self.root / "Broken.mod", 'name = "Roto"\ndependencies = { "A"\n'))
        self.assertEqual(broken.name, "Roto")
        self.assertEqual([e.code for e in broken.errors], ["unclosed_block"])
        self.assertIsNone(read_descriptor(self.root / "missing.mod"))

    def test_find_sibling_by_path_then_by_name_then_inside(self):
        mod = self.root / "mod" / "MiMod"
        mod.mkdir(parents=True)
        self.assertIsNone(find_descriptor(mod))
        write(mod / "copia.mod", 'name = "Dentro"\n')
        inside = find_descriptor(mod)
        self.assertEqual((inside.name, inside.location), ("Dentro", INSIDE))
        write(self.root / "mod" / "mimod.mod", 'name = "Por nombre"\n')
        self.assertEqual(find_descriptor(mod).name, "Por nombre", "los nombres no distinguen mayúsculas")
        write(self.root / "mod" / "zz.mod", 'name = "Por ruta"\npath = "mod/MIMOD"\n')
        found = find_descriptor(mod)
        self.assertEqual((found.name, found.location), ("Por ruta", SIBLING))

    def test_unreadable_descriptors_never_raise(self):
        """P2: un .mod con BOM UTF-8 y texto cp1252 en la carpeta superior impedía arrancar la aplicación."""
        mod = self.root / "mod" / "VSM"
        mod.mkdir(parents=True)
        (self.root / "mod" / "Leon.mod").write_bytes(b'\xef\xbb\xbfname = "Le\xf3n"\r\npath = "mod/Leon"\r\n')
        write(self.root / "mod" / "VSM.mod", 'name = "Shago Mod"\r\npath = "mod/VSM"\r\n')
        self.assertEqual(find_descriptor(mod).name, "Shago Mod")
        leon = read_descriptor(self.root / "mod" / "Leon.mod")
        self.assertEqual(leon.path, "mod/Leon")
        self.assertEqual(read_descriptor(self.root / "mod"), None, "una carpeta no es un descriptor")

    def test_descriptors_the_game_cannot_read(self):
        """R1: find_descriptor prefería Utf16.mod (ilegible para el juego) a VSM.mod, y guardarlo lo dejaba en UTF-16."""
        mod = self.root / "mod" / "VSM"
        mod.mkdir(parents=True)
        utf16 = self.root / "mod" / "Utf16.mod"
        utf16.write_bytes('# copia\r\nname = "U16"\r\npath = "mod/VSM"\r\n'.encode("utf-16"))
        only = find_descriptor(mod)
        self.assertEqual((only.name, only.encoding, only.game_readable), ("U16", "utf-16", False),
                         "si no hay otro, se usa (y la validación dirá que el juego no lo lee)")
        write(self.root / "mod" / "VSM.mod", 'name = "Shago Mod"\r\npath = "mod/VSM"\r\n')
        self.assertEqual(find_descriptor(mod).name, "Shago Mod")
        (mod / "a.mod").write_bytes('name = "Dentro U16"\r\n'.encode("utf-16"))
        write(mod / "b.mod", 'name = "Dentro"\r\n')
        self.assertEqual(find_descriptor(self.root / "mod" / "VSM").name, "Shago Mod")
        (self.root / "mod" / "VSM.mod").unlink()
        utf16.unlink()
        self.assertEqual(find_descriptor(mod).name, "Dentro")
        # Al guardarlo pasa a cp1252, sin perder el comentario.
        utf16.write_bytes('# copia\r\nname = "U16"\r\npath = "mod/VSM"\r\n'.encode("utf-16"))
        descriptor = read_descriptor(utf16)
        write_descriptor(utf16, replace(descriptor, user_dir="VSM"), backup=False)
        self.assertEqual(utf16.read_bytes(), b'# copia\r\nname = "U16"\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n')
        self.assertTrue(read_descriptor(utf16).game_readable)

    def test_archive_and_replace_paths(self):
        """FC-14: no se leía «archive» y replace_path quedaba sin normalizar."""
        d = read_descriptor(write(self.root / "A.mod", 'name = "A"\narchive = "mod/a.zip"\n'
                                  'replace_path = "history/countries/"\nreplace_path = "common\\\\countries"\n'))
        self.assertEqual(d.archive, "mod/a.zip")
        self.assertEqual(d.normalized_replace_paths, ("history/countries", "common/countries"))
        self.assertTrue(d.replaces("History\\Countries"))
        self.assertFalse(d.replaces("localisation"))

    def test_rereads_from_disk(self):
        """MISSED-3: tras editar el .mod, volver a leerlo da los datos nuevos (no hay caché)."""
        file = write(self.root / "VSM.mod", 'name = "Shago Mod"\npath = "mod/VSM"\n')
        self.assertEqual(read_descriptor(file).user_dir, "")
        write(file, 'name = "Shago Mod"\npath = "mod/VSM"\nuser_dir = "VSM"\n')
        self.assertEqual(read_descriptor(file).user_dir, "VSM")

    def test_descriptors_are_hashable(self):
        """FC-12: hash() de un descriptor con errores fallaba (los Diagnostic no son hashables)."""
        broken = read_descriptor(write(self.root / "bad.mod", 'name = "A\npath = { \n'))
        self.assertTrue(broken.errors)
        self.assertEqual(len({broken, read_descriptor(broken.file)}), 1)

    def test_generate_a_new_descriptor(self):
        """FC-14: no había forma de generar el .mod (objetivo del Wizard)."""
        target = self.root / "mod" / "DAM.mod"
        wanted = ModDescriptor(target, name="Dark Age Mod", path="mod/DAM", user_dir="DAM",
                               replace_paths=("history/pops",), dependencies=("Base Mod",))
        self.assertIsNone(write_descriptor(target, wanted))
        self.assertEqual(target.read_bytes(), b'name = "Dark Age Mod"\r\npath = "mod/DAM"\r\nuser_dir = "DAM"\r\n'
                                              b'replace_path = "history/pops"\r\ndependencies = { "Base Mod" }\r\n')
        self.assertEqual(read_descriptor(target), wanted)
        if os.name == "posix":
            self.assertNotEqual(target.stat().st_mode & 0o077, 0, "permisos por defecto, no 0o600")
        # R5: el error era un ValueError sin código y solo en español.
        bad_values = {
            ModDescriptor(target, name='Con "comillas"'): (FIELD_QUOTE, "name"),
            ModDescriptor(target, path="mod/a\nb"): (FIELD_NEWLINE, "path"),
            ModDescriptor(target, name="A", dependencies=('Otro "mod"',)): (FIELD_QUOTE, "dependencies"),
        }
        for bad, (code, field_name) in bad_values.items():
            with self.subTest(bad=bad):
                with self.assertRaises(DescriptorFieldError) as ctx:
                    write_descriptor(self.root / "nuevo.mod", bad)
                error = ctx.exception
                self.assertIsInstance(error, ValueError)
                self.assertEqual((error.code, error.params["field"]), (code, field_name))
                self.assertIn(field_name, error.message("es"))
                self.assertNotEqual(error.message("es"), error.message("en"))
                self.assertEqual(str(error), error.message("es"))
        self.assertFalse((self.root / "nuevo.mod").exists())
        self.assertEqual(set(DESCRIPTOR_MESSAGES["es"]), set(DESCRIPTOR_MESSAGES["en"]))

    def test_edit_an_existing_descriptor_keeps_the_rest(self):
        file = write(self.root / "VSM.mod", '# Mod del usuario\r\nname = "Shago Mod"\r\npath = "mod/VSM"\r\n'
                                            'picture = "thumb.png"\r\nreplace_path = "history/pops"\r\n')
        before = file.read_bytes()
        original = read_descriptor(file)
        self.assertIsNone(write_descriptor(file, original, backup=False))
        self.assertEqual(file.read_bytes(), before, "sin cambios el archivo queda igual")
        changed = ModDescriptor(file, name="Shago Mod 2", path="mod/VSM", user_dir="VSM",
                                replace_paths=("history/pops", "history/units"))
        backup = write_descriptor(file, changed)
        self.assertEqual(backup.read_bytes(), before)
        text = file.read_bytes().decode("cp1252")
        self.assertTrue(text.startswith('# Mod del usuario\r\nname = "Shago Mod 2"\r\n'), text)
        self.assertIn('picture = "thumb.png"', text)
        self.assertNotIn("\n", text.replace("\r\n", ""), "conserva los CRLF también en las líneas nuevas")
        self.assertEqual(read_descriptor(file), changed)

    def test_descriptor_in_every_encoding(self):
        """NF-1: write_descriptor de un .mod UTF-16 BE con BOM lanzaba UnencodableTextError (U+FEFF en 1:1)
        al pasarlo a cp1252, sin escribir nada. Las cuatro variantes, con y sin cambios."""
        text = '# copia\r\nname = "Le\u00f3n"\r\npath = "mod/Leon"\r\n'
        variants = {
            "cp1252": (text.encode("cp1252"), "cp1252"),
            "utf-8-sig": (codecs.BOM_UTF8 + text.encode("utf-8"), "utf-8-sig"),
            "utf-16": (codecs.BOM_UTF16_LE + text.encode("utf-16-le"), "cp1252"),
            "utf-16-be-bom": (codecs.BOM_UTF16_BE + text.encode("utf-16-be"), "cp1252"),
        }
        edited = text + 'user_dir = "Leon"\r\n'
        for encoding, (raw, saved_as) in variants.items():
            with self.subTest(encoding=encoding):
                file = self.root / f"{encoding}.mod"
                file.write_bytes(raw)
                descriptor = read_descriptor(file)
                self.assertEqual((descriptor.name, descriptor.encoding), ("Le\u00f3n", encoding))
                result = parse_file(file)
                self.assertEqual(to_source(result.document), text)
                write_file(file, result, backup=False)
                self.assertEqual(file.read_bytes(), raw, "guardar sin cambiar de codificación da los mismos bytes")
                write_descriptor(file, replace(descriptor, user_dir="Leon"), backup=False)
                self.assertEqual(file.read_bytes().decode(saved_as), edited, "UTF-16 pasa a cp1252, sin BOM")
                self.assertEqual(read_descriptor(file).encoding, saved_as)

    def test_descriptor_with_a_repeated_bom(self):
        """Con un BOM repetido, write_descriptor de un .mod UTF-16 lanzaba UnencodableTextError: el
        U+FEFF que queda delante no cabe en cp1252. En UTF-8 con BOM se conservan los dos BOM."""
        text = '# copia\r\nname = "León"\r\npath = "mod/Leon"\r\n'
        edited = text + 'user_dir = "Leon"\r\n'
        variants = {
            "utf-8-sig": (codecs.BOM_UTF8 * 2 + text.encode("utf-8"), codecs.BOM_UTF8 * 2 + edited.encode("utf-8")),
            "utf-16": (codecs.BOM_UTF16_LE * 2 + text.encode("utf-16-le"), edited.encode("cp1252")),
            "utf-16-be-bom": (codecs.BOM_UTF16_BE * 3 + text.encode("utf-16-be"), edited.encode("cp1252")),
        }
        for encoding, (raw, saved) in variants.items():
            with self.subTest(encoding=encoding):
                file = self.root / f"{encoding}.mod"
                file.write_bytes(raw)
                descriptor = read_descriptor(file)
                self.assertEqual((descriptor.name, descriptor.encoding), ("León", encoding))
                write_file(file, parse_file(file), backup=False)
                self.assertEqual(file.read_bytes(), raw)
                write_descriptor(file, replace(descriptor, user_dir="Leon"), backup=False)
                self.assertEqual(file.read_bytes(), saved)
                self.assertEqual(read_descriptor(file).user_dir, "Leon")

    def test_user_descriptor(self):
        for root in corpus_roots():
            if (root / "VSM.mod").is_file() and (root / "VSM").is_dir():
                d = find_descriptor(root / "VSM")
                self.assertEqual((d.name, d.path, d.user_dir, d.location), ("Shago Mod", "mod/VSM", "VSM", SIBLING))
                return
        self.skipTest("sin el mod del usuario en VIC2_CORPUS")


class ModCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Mod"
        self.addCleanup(self._tmp.cleanup)
        write(self.root / "events" / "good.txt", "country_event = {\n\tid = 1\n}\n")
        write(self.root / "decisions" / "bad.txt", "political_decisions = {\n\ta = {\n\t\tb = c\n\t}\n")
        write(self.root / "localisation" / "00_mod.csv", "KEY;Hello;;;;Hola;;;;;;;;;x\nKEY;Again;;;;Otra;;;;;;;;;x\n")
        write(self.root / "interface" / "x.gui", "guiTypes = { }\n")
        write(self.root / "notes.lua", "print('no se valida')\n")
        write(self.root / ".git" / "config.txt", "{{{ no se recorre\n")

    def test_collect_files_order_kinds_and_extras(self):
        descriptor = write(self.root.parent / "Mod.mod", 'name = "Mod"\npath = "mod/Mod"\n')
        files = [p.relative_to(self.root.parent).as_posix() for p in collect_files(self.root, [descriptor])]
        self.assertEqual(files, ["Mod.mod", "Mod/decisions/bad.txt", "Mod/events/good.txt",
                                 "Mod/interface/x.gui", "Mod/localisation/00_mod.csv"])
        self.assertEqual(len(collect_files(self.root, [descriptor, descriptor, self.root / "events" / "good.txt"])), 5)
        self.assertEqual(file_kind("mod/Localisation/B.CSV"), KIND_CSV)
        self.assertIsNone(file_kind("x.lua"))

    def test_only_what_the_game_reads(self):
        """VAL-M2, VAL-M4, P11: map/*.csv se validaban como localización, un léeme de la raíz como script
        y map/default.map no se validaba."""
        write(self.root / "map" / "definition.csv", "province;red;green;blue;x;x\n1;10;20;30;Paris;x\n")
        write(self.root / "map" / "adjacencies.csv", "From;To;Type;Through;Data;Comment\n")
        write(self.root / "map" / "default.map", "max_provinces = 3250\ndefinitions = \"definition.csv\"\n")
        write(self.root / "readme.txt", "Mi mod: instala en mod/ y disfruta.\n")
        write(self.root / "docs" / "changelog.txt", "v1: { roto\n")
        write(self.root / "localisation" / "viejos" / "x.csv", "K;a\n")
        write(self.root / "Copia.mod", 'name = "Mod"\npath = "mod/Mod"\n')
        files = [p.relative_to(self.root).as_posix() for p in collect_files(self.root)]
        self.assertEqual(files, ["Copia.mod", "decisions/bad.txt", "events/good.txt", "interface/x.gui",
                                 "localisation/00_mod.csv", "map/default.map"])
        self.assertEqual((file_kind("map/definition.csv"), file_kind("map/default.map")), (None, KIND_CLAUSEWITZ))
        report = check_mod(self.root)
        self.assertEqual(report.files_with(Severity.ERROR), ["decisions/bad.txt"])
        self.assertFalse([i for i in report.issues if i.relative.startswith(("map/", "readme", "docs/"))])

    def test_game_installations_are_never_validated(self):
        """VAL-7: una carpeta con el juego dentro hacía validar los archivos vanilla."""
        for game in (self.root / "common" / "Victoria 2", self.root / "Victoria 2"):
            write(game / "v2game.exe", "MZ")
            write(game / "events" / "vanilla.txt", "country_event = {\n")
            write(game / "common" / "countries.txt", "GER = { \n")
        files = [p.relative_to(self.root).as_posix() for p in collect_files(self.root)]
        self.assertFalse([f for f in files if "Victoria 2" in f], files)

    def test_scan_is_cancellable_and_reports_progress(self):
        """VAL-M3: la exploración inicial no se podía cancelar ni daba progreso."""
        for i in range(30):
            write(self.root / "history" / "provinces" / f"region{i:02d}" / "1 - A.txt", "owner = FRA\n")
        seen = []
        with mock.patch.object(modcheck, "SCAN_PROGRESS_INTERVAL", 0):
            files = collect_files(self.root, progress=lambda found, folder: seen.append((found, folder)))
        self.assertEqual(len(files), 34)
        self.assertIn("history/provinces/region29", [folder for _, folder in seen])
        self.assertEqual([found for found, _ in seen], sorted(found for found, _ in seen))
        calls = []
        with self.assertRaises(Cancelled):
            collect_files(self.root, cancelled=lambda: calls.append(1) or len(calls) > 5)
        self.assertEqual(len(calls), 6)
        report = check_mod(self.root, cancelled=lambda: calls.append(1) or len(calls) > 8)
        self.assertEqual((report.cancelled, report.files), (True, 0))

    def test_a_folder_that_is_not_a_mod_root_is_reported(self):
        """R4: validar una subcarpeta del mod (events/, map/...) daba en silencio «Sin problemas — 0 archivos»."""
        self.assertTrue(is_mod_root(self.root))
        self.assertFalse(is_mod_root(self.root / "events"))
        report = check_mod(self.root / "events")
        self.assertEqual(report.files, 0)
        self.assertEqual([(i.code, i.relative, i.severity) for i in report.issues],
                         [(NO_GAME_FOLDERS, ".", Severity.WARNING)])
        self.assertIn("«events»", report.issues[0].message("es"))
        self.assertIn("“events”", report.issues[0].message("en"))
        self.assertNotIn(NO_GAME_FOLDERS, {i.code for i in check_mod(self.root).issues})
        # Un mod recién creado (carpetas vacías) o solo con su descriptor sí es la raíz de un mod.
        new = Path(self._tmp.name) / "Nuevo"
        (new / "Common").mkdir(parents=True)
        self.assertEqual(check_mod(new).issues, [])
        write(Path(self._tmp.name) / "Solo" / "Solo.mod", 'name = "Solo"\npath = "mod/Solo"\n')
        self.assertTrue(is_mod_root(Path(self._tmp.name) / "Solo"))

    def test_encodings_the_game_cannot_read(self):
        """P3, R1: un script en UTF-16 (si era ASCII, sin ningún aviso) o con un BOM UTF-8 delante de cp1252
        pasaba «Validar mod» limpio o con un aviso falso («lo lee como Windows-1252»)."""
        def script(title: str) -> str:
            return f'country_event = {{\r\n\tid = 2\r\n\ttitle = "{title}"\r\n}}\r\n'

        files = {
            "events/notepad.txt": script("Leon").encode("utf-16"),
            "events/no_bom.txt": script("Leon").encode("utf-16-le"),
            "events/big_endian.txt": codecs.BOM_UTF16_BE + script("León").encode("utf-16-be"),
            "events/stray_bom.txt": codecs.BOM_UTF8 + script("León").encode("cp1252"),
            "events/utf8_bom.txt": codecs.BOM_UTF8 + script("León").encode("utf-8"),
        }
        for relative, data in files.items():
            (self.root / relative).write_bytes(data)
        descriptor = self.root.parent / "Mod.mod"
        descriptor.write_bytes('name = "Mod"\r\npath = "mod/Mod"\r\n'.encode("utf-16"))
        report = check_mod(self.root, extra_files=[descriptor])
        found = {(i.relative, i.code, i.severity, i.line) for i in report.issues
                 if i.relative in files or i.relative == "../Mod.mod"}
        self.assertEqual({i for i in found if i[0] != "events/utf8_bom.txt"}, {
            ("events/notepad.txt", UNREADABLE_ENCODING, Severity.ERROR, None),
            ("events/no_bom.txt", UNREADABLE_ENCODING, Severity.ERROR, None),
            ("events/big_endian.txt", UNREADABLE_ENCODING, Severity.ERROR, None),
            ("../Mod.mod", UNREADABLE_ENCODING, Severity.ERROR, None),
            ("events/stray_bom.txt", STRAY_BOM, Severity.WARNING, 1),
        })
        self.assertFalse({code for relative, code, _, _ in found if relative == "events/utf8_bom.txt"}
                         & {UNREADABLE_ENCODING, STRAY_BOM}, "un UTF-8 con BOM de verdad no es un BOM perdido")
        big_endian = next(i for i in report.issues if i.relative == "events/big_endian.txt")
        self.assertEqual(big_endian.args, {"encoding": "UTF-16-BE-BOM"})
        self.assertIn("no puede leerlo", big_endian.message("es"))
        self.assertIn("cannot read it", big_endian.message("en"))
        stray = next(i for i in report.issues if i.code == STRAY_BOM)
        self.assertIn("ï»¿", stray.message("es"))
        self.assertNotEqual(stray.message("es"), stray.message("en"))
        self.assertEqual([(i.code, i.severity) for i in check_file(descriptor, self.root)],
                         [(UNREADABLE_ENCODING, Severity.ERROR)], "sus campos se leen: solo falla la codificación")

    def test_missing_or_unreadable_folders_are_reported(self):
        """VAL-9: validar una carpeta que ya no existe daba «Sin problemas — Archivos analizados: 0»."""
        report = check_mod(self.root.parent / "borrado")
        self.assertEqual([(i.code, i.relative, i.severity) for i in report.issues],
                         [(FOLDER_ERROR, ".", Severity.ERROR)])
        self.assertIn("No se pudo recorrer la carpeta", report.issues[0].message("es"))
        self.assertEqual(set(MESSAGES["es"]), set(MESSAGES["en"]))
        blocked = os.path.join(self.root, "events")
        real_scandir = os.scandir

        def scandir(path="."):
            if os.fspath(path) == blocked:
                raise PermissionError(13, "Permission denied", blocked)
            return real_scandir(path)

        with mock.patch.object(os, "scandir", scandir):
            report = check_mod(self.root)
        self.assertEqual([(i.code, i.relative) for i in report.issues if i.code == FOLDER_ERROR],
                         [(FOLDER_ERROR, "events")])
        self.assertEqual(report.files, 3)

    def test_report_counts_order_and_messages(self):
        progress = []
        report = check_mod(self.root, progress=lambda done, total, rel: progress.append((done, total, rel)))
        self.assertFalse(report.cancelled)
        self.assertEqual((report.files, report.clausewitz_files, report.csv_files), (4, 3, 1))
        # VAL-5: antes de cada archivo, con el que empieza; al final, (total, total, "").
        self.assertEqual(progress, [(0, 4, "decisions/bad.txt"), (1, 4, "events/good.txt"),
                                    (2, 4, "interface/x.gui"), (3, 4, "localisation/00_mod.csv"), (4, 4, "")])
        self.assertEqual(report.files_with(Severity.ERROR), ["decisions/bad.txt"])
        first = report.issues[0]
        self.assertEqual((first.relative, first.code, first.line, first.severity),
                         ("decisions/bad.txt", "unclosed_block", 1, Severity.ERROR))
        self.assertIn("political_decisions", first.message("es"))
        self.assertIn("never closed", first.message("en"))
        duplicate = next(i for i in report.issues if i.code == "duplicate_key")
        self.assertEqual((duplicate.kind, duplicate.line, duplicate.severity), (KIND_CSV, 2, Severity.WARNING))
        ranks = [{Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}[i.severity] for i in report.issues]
        self.assertEqual(ranks, sorted(ranks), "los errores van primero")
        self.assertGreaterEqual(report.elapsed, 0)

    def test_cancel_and_failures_never_raise(self):
        calls = []
        report = check_mod(self.root, progress=lambda *a: calls.append(a), cancelled=lambda: len(calls) >= 3)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.files, 2)
        self.assertNotIn((4, 4, ""), calls, "una validación cancelada no anuncia el final")
        missing = check_file(self.root / "nope.txt", self.root)
        self.assertEqual([(i.code, i.severity) for i in missing], [(READ_ERROR, Severity.ERROR)])
        self.assertIn("No se pudo leer", missing[0].message("es"))
        self.assertEqual(missing[0].relative, "nope.txt")
        outside = check_file(self.root.parent / "elsewhere.txt", self.root)
        self.assertEqual(outside[0].relative, "../elsewhere.txt")

    def test_cancel_inside_a_file_stops_without_counting_it(self):
        # La consulta 1 es la de antes del archivo; la 2, ya dentro del análisis, pide parar.
        calls = []
        report = check_mod(self.root, cancelled=lambda: calls.append(1) or len(calls) >= 2)
        self.assertTrue(report.cancelled)
        self.assertEqual((report.files, report.issues), (0, []))
        with self.assertRaises(Cancelled):
            check_file(self.root / "events" / "good.txt", self.root, cancelled=lambda: True)

    def test_cancel_inside_a_big_csv_is_quick(self):
        """VAL-4: Cancelar no detenía el análisis de un archivo grande."""
        big = self.root / "localisation" / "big.csv"
        big.write_bytes("".join(f"K{i};text {i};;;;texto {i};;;;;;x\r\n" for i in range(200_000)).encode("cp1252"))
        stop, started, done = threading.Event(), threading.Event(), {}

        def progress(count, total, relative):
            if relative == "localisation/big.csv":
                started.set()

        def run():
            done["report"] = check_mod(self.root, progress=progress, cancelled=stop.is_set)
            done["at"] = time.perf_counter()

        # Sin el recolector cíclico, cuyas pausas no dependen del núcleo (ui.tasks lo controla en las tareas).
        if gc.isenabled():
            gc.disable()
            self.addCleanup(gc.enable)
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(started.wait(10))
        time.sleep(0.3)
        asked = time.perf_counter()
        stop.set()
        worker.join(10)
        self.assertTrue(done["report"].cancelled)
        self.assertLess(done["at"] - asked, 0.2)
        self.assertNotIn("localisation/big.csv", {i.relative for i in done["report"].issues})

    def test_cancel_while_converting_many_diagnostics(self):
        """VAL-4: convertir cientos de miles de diagnósticos en Issue (casi 1 s) no consultaba ``cancelled``."""
        path = self.root / "localisation" / "00_mod.csv"
        many = SimpleNamespace(diagnostics=read_csv_file(path).diagnostics * 50_000)
        blocks = -(-len(many.diagnostics) // modcheck.CANCEL_EVERY)
        self.assertGreater(blocks, 10)
        calls = []
        with mock.patch.object(modcheck, "read_csv_file", lambda *_, **__: many):
            issues = check_file(path, self.root, cancelled=lambda: calls.append(1) and False)
            self.assertEqual(len(issues), len(many.diagnostics))
            self.assertGreaterEqual(len(calls), blocks, "una consulta por bloque")
            # NC-1: pedir parar a mitad de la conversión (en la 4.ª consulta) la detiene ahí.
            calls.clear()
            with self.assertRaises(Cancelled):
                check_file(path, self.root, cancelled=lambda: calls.append(1) or len(calls) > 3)
            self.assertEqual(len(calls), 4)

    def test_issues_are_hashable(self):
        """FC-12: hash()/set() de los Issue fallaban en cuanto llevaban un diagnóstico Clausewitz."""
        report = check_mod(self.root)
        clausewitz = [i for i in report.issues if i.kind == KIND_CLAUSEWITZ]
        self.assertTrue(clausewitz)
        self.assertEqual(len(set(report.issues)), len(report.issues))
        self.assertEqual(set(check_mod(self.root).issues), set(report.issues))

    def test_descriptor_fields_are_checked(self):
        """FC-14: nada comprobaba que path sea "mod/<carpeta>", ni user_dir ni replace_path."""
        game = Path(self._tmp.name) / "game"
        (game / "mod" / "Mod").mkdir(parents=True)
        cases = {
            ModDescriptor(Path("a.mod"), name="A", path="mod/Mod", user_dir="Mod"): [],
            ModDescriptor(Path("a.mod"), name="A", path="mod\\MOD\\"): [],
            ModDescriptor(Path("a.mod")): ["descriptor_no_name", "descriptor_no_path"],
            ModDescriptor(Path("a.mod"), name="A", path="Mod"): ["descriptor_bad_path"],
            ModDescriptor(Path("a.mod"), name="A", path="mod/../Mod"): ["descriptor_bad_path"],
            ModDescriptor(Path("a.mod"), name="A", path="C:/mod/Mod"): ["descriptor_bad_path"],
            ModDescriptor(Path("a.mod"), name="A", path="mod/Otro"): ["descriptor_other_folder"],
            ModDescriptor(Path("a.mod"), name="A", path="mod/Mod", user_dir="a/b"): ["descriptor_bad_user_dir"],
            ModDescriptor(Path("a.mod"), name="A", path="mod/Mod", user_dir="dir."): ["descriptor_bad_user_dir"],
            ModDescriptor(Path("a.mod"), name="A", path="mod/Mod",
                          replace_paths=("history/pops", "../common", "C:\\x")): ["descriptor_bad_replace_path"] * 2,
        }
        for descriptor, expected in cases.items():
            with self.subTest(descriptor=descriptor):
                issues = check_descriptor(descriptor, mod_dir=self.root, game_dir=game)
                self.assertEqual([i.code for i in issues], expected)
                self.assertEqual(len(set(issues)), len(issues), "dos replace_path malos son dos problemas")
                for issue in issues:
                    self.assertNotEqual(issue.message("es"), issue.message("en"))
                    self.assertNotIn("{", issue.message("es") + issue.message("en"))
        missing = check_descriptor(ModDescriptor(Path("a.mod"), name="A", path="mod/Otro"), game_dir=game)
        self.assertEqual([i.code for i in missing], ["descriptor_missing_folder"])
        # «Validar mod» revisa los campos del descriptor contra la carpeta del mod.
        wrong = write(self.root.parent / "Mod.mod", 'name = "Mod"\npath = "mod/Otro"\n')
        report = check_mod(self.root, extra_files=[wrong])
        self.assertEqual([(i.code, i.relative) for i in report.issues if i.code.startswith("descriptor_")],
                         [("descriptor_other_folder", "../Mod.mod")])

    def test_unexpected_failure_is_reported(self):
        from vic2studio.core import modcheck

        original = modcheck.parse_file
        modcheck.parse_file = lambda path, **_: (_ for _ in ()).throw(RuntimeError("fallo simulado"))
        try:
            issues = check_file(self.root / "events" / "good.txt", self.root)
        finally:
            modcheck.parse_file = original
        self.assertEqual(issues[0].code, CHECK_FAILED)
        self.assertIn("fallo simulado", issues[0].message("en"))


class UserModTests(unittest.TestCase):
    def test_user_mod_has_exactly_the_known_errors(self):
        mod = user_mod()
        if mod is None:
            self.skipTest("sin el mod del usuario (VIC2_CORPUS o tests/fixtures/shago_mod_min)")
        report = check_mod(mod, extra_files=[mod.parent / "VSM.mod"])
        unclosed = sorted((i.relative, i.line, i.column) for i in report.issues if i.code == "unclosed_block")
        self.assertEqual(unclosed, [("decisions/somaliland_shago.txt", 1, 23),
                                    ("decisions/zulu_expancionshago.txt", 1, 23)])
        # En el mod completo, v2dd2.txt (un diario de desarrollo en prosa de Paradox, no un script)
        # es el tercer archivo con errores; la muestra mínima no lo incluye.
        self.assertEqual(report.files_with(Severity.ERROR), user_mod_error_files(mod))
        if (mod / DEV_DIARY).is_file():
            diary = [(i.code, i.line) for i in report.issues if i.relative == DEV_DIARY and i.severity is Severity.ERROR]
            self.assertEqual(diary, [("missing_key", 4)])
        self.assertFalse([i for i in report.issues if i.code.startswith("descriptor_")])
        # FC-3: sus 00_VSM_*.csv tienen los 13 idiomas sin «x»; el juego los muestra enteros: notas, no avisos.
        unmarked = [i for i in report.issues
                    if i.relative.startswith("localisation/00_VSM_") and i.code == "missing_end_marker"]
        self.assertTrue(unmarked)
        self.assertEqual({i.severity for i in unmarked}, {Severity.INFO})


if __name__ == "__main__":
    unittest.main()
