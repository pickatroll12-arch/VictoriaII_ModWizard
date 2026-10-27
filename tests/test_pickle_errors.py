"""Serialización con pickle de los errores y problemas de guardado del núcleo (wizard §18.4, G3)."""

from __future__ import annotations

import dataclasses
import pickle
import sys
import unittest
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.clausewitz.diagnostics import EditError, EditTypeError  # noqa: E402
from vic2studio.core.clausewitz.serializer import SourceMismatchError  # noqa: E402
from vic2studio.core.csvloc.model import (  # noqa: E402
    SEPARATOR_IN_TEXT,
    DuplicateKeyError,
    InvalidFieldError,
)
from vic2studio.core.encoding import (  # noqa: E402
    GAME_ENCODING,
    UnencodableTextError,
    find_unencodable,
)
from vic2studio.core.fileio import FileChangedError  # noqa: E402
from vic2studio.core.modfile import (  # noqa: E402
    FIELD_NEWLINE,
    FIELD_QUOTE,
    DescriptorFieldError,
    DescriptorProblemsError,
    DescriptorSpec,
    DescriptorWriteError,
    descriptor_problems,
)
from vic2studio.core.project.model import (  # noqa: E402
    READ_ONLY_LOCKED,
    READ_ONLY_PARSE_ERRORS,
    SAVE_CONFLICT,
    SAVE_READ_ONLY,
    SAVE_UNENCODABLE,
    SaveProblem,
)
from vic2studio.core.project.workspace import (  # noqa: E402
    ReadOnlyDocumentError,
    WrongThreadError,
)
from vic2studio.core.vfs.guard import WriteOutsideModError  # noqa: E402
from vic2studio.core.vfs.paths import DESCRIPTOR_REL, InvalidPathError, VPath  # noqa: E402


class PickleErrorsTests(unittest.TestCase):
    def assert_roundtrip(self, original):
        restored = pickle.loads(pickle.dumps(original))
        self.assertIs(type(restored), type(original))
        self.assertEqual(str(restored), str(original))
        if isinstance(original, BaseException):
            self.assertEqual(restored.args, original.args)
        if hasattr(original, "message"):
            self.assertEqual(restored.message("es"), original.message("es"))
            self.assertEqual(restored.message("en"), original.message("en"))
        if dataclasses.is_dataclass(original):
            self.assertEqual(restored, original)
            self.assertEqual(repr(restored), repr(original))
        for name, value in vars(original).items():
            if name.startswith("_"):
                continue
            restored_value = getattr(restored, name)
            self.assertEqual(restored_value, value, name)
            self.assertIs(type(restored_value), type(value), name)
        return restored

    def test_source_mismatch_error(self):
        err1 = SourceMismatchError(Path("common/cb_types.txt"), "conquer_land > months", 10)
        self.assert_roundtrip(err1)
        err2 = SourceMismatchError(
            Path("decisions/somaliland_shago.txt"),
            "political_decisions > unite",
            4,
            near_errors=True,
        )
        self.assert_roundtrip(err2)

    def test_unencodable_text_error(self):
        problems = find_unencodable("a = 1\nc = Ω", GAME_ENCODING)
        err = UnencodableTextError(GAME_ENCODING, problems)
        self.assert_roundtrip(err)

    def test_descriptor_field_error(self):
        err_quote = DescriptorFieldError(FIELD_QUOTE, field="name", value='Mod "A"')
        self.assert_roundtrip(err_quote)
        err_newline = DescriptorFieldError(FIELD_NEWLINE, field="user_dir", value="a\nb")
        self.assert_roundtrip(err_newline)

    def test_descriptor_problems_error(self):
        issues = descriptor_problems(DescriptorSpec("", "CON", "x"), None, creating=True)
        self.assertTrue(issues)
        self.assert_roundtrip(DescriptorProblemsError(issues))
        quote_issues = descriptor_problems(DescriptorSpec('Mod "A"', "VSM", "VSM"), None, creating=True)
        self.assert_roundtrip(DescriptorProblemsError(quote_issues))

    def test_save_problem(self):
        default_args = SaveProblem(SAVE_READ_ONLY, None)
        restored_default = self.assert_roundtrip(default_args)
        self.assertIsInstance(restored_default.args, MappingProxyType)

        with_vpath = SaveProblem(
            SAVE_UNENCODABLE,
            VPath.of("common/countries/Somalia.txt"),
            {"line": 3, "column": 5, "char": "'Ω'", "encoding": "Windows-1252"},
            blocking=True,
        )
        restored_vpath = self.assert_roundtrip(with_vpath)
        self.assertIs(type(restored_vpath.rel), VPath)
        self.assertIs(type(restored_vpath.args), dict)

        with_descriptor = SaveProblem(
            SAVE_CONFLICT,
            DESCRIPTOR_REL,
            MappingProxyType({"path": "/tmp/VSM.mod"}),
            blocking=False,
        )
        restored_desc = self.assert_roundtrip(with_descriptor)
        self.assertIs(type(restored_desc.rel), VPath)
        self.assertEqual(restored_desc.rel, DESCRIPTOR_REL)
        self.assertIsInstance(restored_desc.args, MappingProxyType)

    def test_descriptor_write_error(self):
        err_default = DescriptorWriteError([SaveProblem(SAVE_READ_ONLY, None)])
        restored_default = self.assert_roundtrip(err_default)
        self.assertIsInstance(restored_default.problems[0].args, MappingProxyType)

        err_conflict = DescriptorWriteError(
            [SaveProblem(SAVE_CONFLICT, DESCRIPTOR_REL, {"path": "/tmp/VSM.mod"})]
        )
        restored_conflict = self.assert_roundtrip(err_conflict)
        self.assertIs(type(restored_conflict.problems[0].rel), VPath)

    def test_read_only_document_error(self):
        err = ReadOnlyDocumentError(
            VPath.of("decisions/somaliland_shago.txt"),
            READ_ONLY_PARSE_ERRORS,
        )
        restored = self.assert_roundtrip(err)
        self.assertIs(type(restored.rel), VPath)

        err_desc = ReadOnlyDocumentError(DESCRIPTOR_REL, READ_ONLY_LOCKED)
        restored_desc = self.assert_roundtrip(err_desc)
        self.assertIs(type(restored_desc.rel), VPath)
        self.assertEqual(restored_desc.rel, DESCRIPTOR_REL)

    def test_edit_error(self):
        self.assert_roundtrip(EditError("empty_key", {"where": "common/countries.txt"}))
        self.assert_roundtrip(EditTypeError("text_type", {"type": "int"}))

    def test_invalid_field_error(self):
        self.assert_roundtrip(InvalidFieldError(SEPARATOR_IN_TEXT, text="a;b"))

    def test_duplicate_key_error(self):
        self.assert_roundtrip(DuplicateKeyError("KEY_A"))

    def test_wrong_thread_error(self):
        self.assert_roundtrip(
            WrongThreadError("el Workspace solo se usa desde el hilo que lo posee (I12)")
        )

    def test_file_changed_error(self):
        err = FileChangedError(Path("common/countries/Somalia.txt"))
        restored = self.assert_roundtrip(err)
        self.assertIsInstance(restored.path, Path)

    def test_invalid_path_error(self):
        try:
            VPath.of("../outside.txt")
        except InvalidPathError as error:
            restored = self.assert_roundtrip(error)
        self.assertEqual((restored.path, restored.reason), ("../outside.txt", "parent"))

    def test_write_outside_mod_error(self):
        restored = self.assert_roundtrip(WriteOutsideModError(Path("/juego/common/a.txt"), Path("/juego/mod/VSM")))
        self.assertIsInstance(restored.path, Path)
        self.assertEqual(restored.mod_root, Path("/juego/mod/VSM"))


if __name__ == "__main__":
    unittest.main()
