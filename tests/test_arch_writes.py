"""Criterio 9 (I1, wizard §4): quién escribe en disco, comprobado con un recorrido AST de ``src/``.

- Las primitivas de escritura cruda (``open`` para escribir, ``Path.write_*``,
  ``os.replace/rename/remove/unlink/mkdir…``, ``shutil.copy*/move/rmtree``,
  ``tempfile.mkstemp…``, ``os.open`` con banderas de escritura) solo aparecen en
  ``core/fileio.py``.
- Las funciones de escritura de ``fileio`` y sus envoltorios ``serializer.write_file``
  y ``csvloc.write_csv_file`` solo se llaman desde ``core/project/journal.py`` (dentro
  del mod, siempre tras ``WriteGuard.check``), ``core/project/lock.py`` (fuera del mod,
  en ``core.appdirs``) y los propios envoltorios.
- Las excepciones están declaradas y justificadas aquí mismo. Una excepción que ya
  no hace falta también hace fallar la prueba: hay que quitarla.

Quedan fuera del recorrido, a propósito: ``tools/`` (fuera de ``src/``), lo que
escribe Qt (``QSettings`` en ``settings.py``, ``QImage.save`` de los glifos de
``ui/theme.py``) y la salida estándar de las CLI.

Además: ``vic2studio.core`` se importa sin PySide6 y todo ``src/`` tiene sintaxis de Python 3.10.
"""

import ast
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SRC = PROJECT / "src"
PACKAGE = SRC / "vic2studio"

FILEIO = "vic2studio.core.fileio"
# Escrituras crudas por módulo de la biblioteca estándar.
RAW_FUNCTIONS = {
    "os": {"replace", "rename", "renames", "remove", "unlink", "rmdir", "removedirs", "mkdir", "makedirs", "link",
           "symlink", "truncate", "fdopen", "write", "ftruncate"},
    "shutil": {"copy", "copy2", "copyfile", "copytree", "move", "rmtree", "copymode", "copystat", "copyfileobj"},
    "tempfile": {"mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory", "TemporaryFile",
                 "SpooledTemporaryFile"},
}
# Métodos de Path que escriben (los nombres son genéricos: solo cuentan como llamada).
PATH_WRITERS = {"write_text", "write_bytes", "unlink", "rename", "rmdir", "mkdir", "symlink_to", "hardlink_to"}
OS_WRITE_FLAGS = {"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC", "O_EXCL"}
# API de escritura de fileio (fsync_dir no modifica nada) y sus envoltorios.
FILEIO_WRITERS = {"atomic_write_bytes", "write_text", "stage_bytes", "commit_staged", "discard_staged", "copy_file",
                  "move_file", "remove_file", "make_dirs", "remove_empty_dirs", "create_exclusive"}
WRAPPERS = {
    "vic2studio.core.clausewitz.serializer": {"write_file"},
    "vic2studio.core.clausewitz": {"write_file"},
    "vic2studio.core.csvloc.serialization": {"write_csv_file"},
    "vic2studio.core.csvloc": {"write_csv_file"},
}

# Quién puede llamar a la API de escritura (además de fileio.py).
WRITERS_ALLOWED = {
    "core/project/journal.py": "el único que escribe dentro del mod: guardado, papelera, originals/ y recovery/",
    "core/project/lock.py": "el bloqueo, fuera del mod (core.appdirs.locks_dir)",
    "core/clausewitz/serializer.py": "es el envoltorio write_file",
    "core/csvloc/serialization.py": "es el envoltorio write_csv_file",
}
# Excepciones declaradas (y justificadas) a las dos reglas.
RAW_EXCEPTIONS = {
    "ui/theme.py": "glifos PNG en una carpeta temporal del proceso (tempfile.mkdtemp), que se borra al salir",
    "core/csvloc/cli.py": "CLI: tojson escribe el JSON donde indica el usuario (--output)",
}
WRITER_EXCEPTIONS = {
    "core/csvloc/cli.py": "CLI: fromjson escribe el CSV donde indica el usuario",
}
# Temporales: deben desaparecer en esta iteración (entonces esta prueba pide quitar la línea).
# Excepciones temporales, con su motivo y su fecha de caducidad (hoy ninguna: modfile.write_descriptor ya escribe
# con el diario desde la integración de la iteración 2).
TEMPORARY_WRITER_EXCEPTIONS: dict[str, str] = {}


def _module_name(rel: str) -> str:
    parts = Path(rel).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(("vic2studio", *parts))


def _resolve(module: str | None, level: int, current: str, is_package: bool) -> str:
    if level == 0:
        return module or ""
    base = current.split(".")
    if not is_package:
        base = base[:-1]
    base = base[:len(base) - (level - 1)]
    return ".".join(base + ([module] if module else []))


class _Finder(ast.NodeVisitor):
    """Encuentra escrituras crudas y llamadas a la API de escritura en un módulo."""

    def __init__(self, module: str, is_package: bool):
        self.module = module
        self.is_package = is_package
        self.modules: dict[str, str] = {}       # nombre local -> módulo
        self.functions: dict[str, tuple[str, str]] = {}   # nombre local -> (módulo, función)
        self.raw: list[tuple[int, str]] = []
        self.writers: list[tuple[int, str, str]] = []     # (línea, qué, función que la contiene)
        self._function = "<módulo>"

    # --- importaciones ---

    def visit_Import(self, node):
        for alias in node.names:
            if alias.asname:
                self.modules[alias.asname] = alias.name
            else:
                self.modules[alias.name.split(".")[0]] = alias.name.split(".")[0]

    def visit_ImportFrom(self, node):
        source = _resolve(node.module, node.level, self.module, self.is_package)
        for alias in node.names:
            local = alias.asname or alias.name
            full = f"{source}.{alias.name}" if source else alias.name
            if full in (FILEIO, *WRAPPERS) or alias.name in RAW_FUNCTIONS:
                self.modules[local] = full
            self.functions[local] = (source, alias.name)

    # --- funciones ---

    def visit_FunctionDef(self, node):
        previous, self._function = self._function, node.name
        self.generic_visit(node)
        self._function = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    # --- usos ---

    def _qualified(self, node) -> tuple[str, str] | None:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = self.modules.get(node.value.id)
            if module is not None:
                return module, node.attr
        if isinstance(node, ast.Name) and node.id in self.functions:
            return self.functions[node.id]
        return None

    def _is_writer(self, target: tuple[str, str] | None) -> str | None:
        if target is None:
            return None
        module, name = target
        if module == FILEIO and name in FILEIO_WRITERS:
            return f"fileio.{name}"
        if name in WRAPPERS.get(module, ()):
            return name
        return None

    def _is_raw(self, target: tuple[str, str] | None) -> str | None:
        if target is None:
            return None
        module, name = target
        if name in RAW_FUNCTIONS.get(module, ()):
            return f"{module}.{name}"
        return None

    def visit_Attribute(self, node):
        raw = self._is_raw(self._qualified(node))
        if raw:
            self.raw.append((node.lineno, raw))      # también como referencia (atexit.register(shutil.rmtree…))
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        target = self._qualified(func)
        writer = self._is_writer(target)
        if writer:
            self.writers.append((node.lineno, writer, self._function))
        raw = self._is_raw(target) if isinstance(func, ast.Name) else None
        if raw:
            self.raw.append((node.lineno, raw))
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name == "open" and target != ("os", "open"):
            method = isinstance(func, ast.Attribute) and target not in (("io", "open"), ("codecs", "open"))
            if self._writes_mode(node, attribute=method):
                self.raw.append((node.lineno, "open(..., escritura)"))
        if self._qualified(func) == ("os", "open") and self._write_flags(node):
            self.raw.append((node.lineno, "os.open(..., escritura)"))
        if isinstance(func, ast.Attribute) and target is None:
            if func.attr in PATH_WRITERS:
                self.raw.append((node.lineno, f".{func.attr}()"))
            elif func.attr == "replace" and len(node.args) == 1 and not node.keywords:
                self.raw.append((node.lineno, ".replace(destino)"))   # Path.replace (str.replace lleva 2)
            elif func.attr == "touch" and not node.args:
                self.raw.append((node.lineno, ".touch()"))
        self.generic_visit(node)

    @staticmethod
    def _writes_mode(node, *, attribute: bool) -> bool:
        index = 0 if attribute else 1        # Path.open(mode) / open(file, mode)
        mode = node.args[index] if len(node.args) > index else None
        for keyword in node.keywords:
            if keyword.arg == "mode":
                mode = keyword.value
        if mode is None:
            return False
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
            return any(flag in mode.value for flag in "wax+")
        # Modo calculado: en open() se trata como escritura; en x.open(…) es otra API (Workspace.open, Image.open).
        return not attribute

    @staticmethod
    def _write_flags(node) -> bool:
        flags = node.args[1] if len(node.args) > 1 else None
        names = {n.attr if isinstance(n, ast.Attribute) else n.id
                 for n in ast.walk(flags) if isinstance(n, (ast.Attribute, ast.Name))} if flags else set()
        return bool(names & OS_WRITE_FLAGS) or (flags is not None and not names)


def scan_source(source: str, rel: str) -> _Finder:
    finder = _Finder(_module_name(rel), rel.endswith("__init__.py"))
    finder.visit(ast.parse(source, filename=rel))
    return finder


def scan_package() -> dict[str, _Finder]:
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        found[rel] = scan_source(path.read_text(encoding="utf-8"), rel)
    return found


class DetectorTests(unittest.TestCase):
    """El detector encuentra lo que debe (si no, la prueba de arquitectura no vale nada)."""

    def raw(self, code):
        return sorted({what for _, what in scan_source(textwrap.dedent(code), "core/x.py").raw})

    def test_raw_primitives_are_found(self):
        self.assertEqual(self.raw("open(p, 'w')"), ["open(..., escritura)"])
        self.assertEqual(self.raw("open(p, mode='ab')"), ["open(..., escritura)"])
        self.assertEqual(self.raw("open(p, m)"), ["open(..., escritura)"])
        self.assertEqual(self.raw("import io\nio.open(p, 'r+b')"), ["open(..., escritura)"])
        self.assertEqual(self.raw("Path(p).write_text('x')"), [".write_text()"])
        self.assertEqual(self.raw("p.write_bytes(b'')"), [".write_bytes()"])
        self.assertEqual(self.raw("p.open('wb')"), ["open(..., escritura)"])
        self.assertEqual(self.raw("import os\nos.replace(a, b)"), ["os.replace"])
        self.assertEqual(self.raw("from os import remove\nremove(a)"), ["os.remove"])
        self.assertEqual(self.raw("import shutil as sh\nsh.rmtree(a)"), ["shutil.rmtree"])
        self.assertEqual(self.raw("import atexit, shutil\natexit.register(shutil.rmtree, d)"), ["shutil.rmtree"])
        self.assertEqual(self.raw("import tempfile\ntempfile.mkstemp()"), ["tempfile.mkstemp"])
        self.assertEqual(self.raw("import os\nos.open(p, os.O_WRONLY | os.O_CREAT)"), ["os.open(..., escritura)"])
        self.assertEqual(self.raw("p.replace(q)"), [".replace(destino)"])
        self.assertEqual(self.raw("p.unlink()"), [".unlink()"])
        self.assertEqual(self.raw("p.touch()"), [".touch()"])

    def test_reads_are_not_writes(self):
        for code in ("open(p)", "open(p, 'rb')", "open(p, encoding='utf-8')", "p.open('rb')", "p.read_bytes()",
                     "'a'.replace('a', 'b')", "ws.touch(handle)", "import os\nos.open(p, os.O_RDONLY)",
                     "import os\nos.scandir(p)", "import shutil\nshutil.disk_usage(p)", "ws.open(rel, create=True)",
                     "Image.open(handle)"):
            with self.subTest(code=code):
                self.assertEqual(self.raw(code), [])

    def test_writer_calls_are_found_through_every_import_form(self):
        cases = {
            "from vic2studio.core import fileio\nfileio.copy_file(a, b)": ["fileio.copy_file"],
            "from .. import fileio\nfileio.stage_bytes(a, b)": ["fileio.stage_bytes"],
            "from ..fileio import write_text\nwrite_text(p, t, 'cp1252')": ["fileio.write_text"],
            "from ..fileio import atomic_write_bytes as w\nw(p, b'')": ["fileio.atomic_write_bytes"],
            "from ..clausewitz import write_file\nwrite_file(p, d)": ["write_file"],
            "from ..clausewitz import serializer\nserializer.write_file(p, d)": ["write_file"],
            "from ..csvloc.serialization import write_csv_file\nwrite_csv_file(p, f)": ["write_csv_file"],
            "import vic2studio.core.fileio as f\nf.remove_file(p)": ["fileio.remove_file"],
            "from ..fileio import FileStamp, fsync_dir\nfsync_dir(p)\nFileStamp.of(b'')": [],
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                found = scan_source(code, "core/project/x.py").writers
                self.assertEqual([what for _, what, _ in found], expected)


class ArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found = scan_package()

    def test_raw_writes_only_in_fileio(self):
        offenders = {rel: finder.raw for rel, finder in self.found.items()
                     if finder.raw and rel != "core/fileio.py" and rel not in RAW_EXCEPTIONS}
        self.assertEqual(offenders, {}, "escrituras crudas fuera de core/fileio.py: pásalas por fileio/journal")
        self.assertTrue(self.found["core/fileio.py"].raw, "el detector ve las primitivas de fileio")

    def test_write_api_only_from_the_allowed_modules(self):
        allowed = {"core/fileio.py", *WRITERS_ALLOWED, *WRITER_EXCEPTIONS, *TEMPORARY_WRITER_EXCEPTIONS}
        offenders = {rel: finder.writers for rel, finder in self.found.items()
                     if finder.writers and rel not in allowed}
        self.assertEqual(offenders, {}, "solo journal (dentro del mod), lock y los envoltorios llaman a fileio")

    def test_journal_writes_only_through_guarded_helpers(self):
        """Dentro del mod, cada llamada a fileio de journal.py está en un _guarded_* que llama a guard.check."""
        source = (PACKAGE / "core/project/journal.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        writers = self.found["core/project/journal.py"].writers
        self.assertTrue(writers)
        for line, what, function in writers:
            with self.subTest(line=line, what=what):
                self.assertTrue(function.startswith("_guarded_"), f"{what} en {function} (línea {line})")
                calls = {n.func.attr for n in ast.walk(functions[function])
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
                self.assertIn("check", calls, f"{function} no comprueba el guard")

    def test_lock_writes_outside_the_mod(self):
        source = (PACKAGE / "core/project/lock.py").read_text(encoding="utf-8")
        self.assertIn("appdirs.locks_dir()", source)
        self.assertNotIn("WriteGuard", source)

    def test_declared_exceptions_are_still_needed(self):
        for rel in RAW_EXCEPTIONS:
            with self.subTest(rel=rel):
                self.assertTrue(self.found[rel].raw, f"{rel} ya no escribe en crudo: quítalo de RAW_EXCEPTIONS")
        for rel in {**WRITER_EXCEPTIONS, **TEMPORARY_WRITER_EXCEPTIONS}:
            with self.subTest(rel=rel):
                self.assertTrue(self.found[rel].writers, f"{rel} ya no llama a la API de escritura: quita la excepción")
        for rel in WRITERS_ALLOWED:
            with self.subTest(rel=rel):
                self.assertIn(rel, self.found)

    def test_python_310_syntax(self):
        for path in sorted(SRC.rglob("*.py")):
            with self.subTest(path=path.relative_to(SRC)):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 10))

    def test_core_imports_without_pyside6(self):
        script = textwrap.dedent("""
            import importlib, pkgutil, sys
            sys.path.insert(0, sys.argv[1])
            import vic2studio.core as core
            names = [m.name for m in pkgutil.walk_packages(core.__path__, "vic2studio.core.")
                     if not m.name.endswith("__main__")]
            for name in names:
                importlib.import_module(name)
            loaded = sorted(m for m in sys.modules if m.split(".")[0] in ("PySide6", "shiboken6"))
            print(len(names), loaded)
            sys.exit(1 if loaded else 0)
        """)
        done = subprocess.run([sys.executable, "-c", script, str(SRC)], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        count = int(done.stdout.split()[0])
        self.assertGreaterEqual(count, 35, "se importaron todos los módulos del núcleo")


if __name__ == "__main__":
    unittest.main()
