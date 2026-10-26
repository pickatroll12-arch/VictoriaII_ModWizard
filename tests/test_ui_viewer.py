"""Visor Clausewitz y tabla de diagnósticos (offscreen).

Cubre a qué entrada pertenece cada diagnóstico (saltos e iconos), el árbol
perezoso, el JSON por trozos, la vista de código y la tabla de diagnósticos, y
mide con un latido de 10 ms que abrir un archivo grande, expandirlo o cambiar de
idioma no congela la interfaz. Los archivos son sintéticos y se crean en
carpetas temporales (salvo la muestra del mod del usuario de ``tests/fixtures``).
Todas fallan ante cualquier aviso de Qt.
"""

import codecs
import errno
import gc
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import _qt
from _corpus import CLAUSEWITZ_SUFFIXES, FIXTURE_ROOT, corpus_files
from PySide6.QtCore import QElapsedTimer, QEvent, QModelIndex, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QHelpEvent, QHoverEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QStyle, QStyleOptionViewItem, QToolTip, QVBoxLayout, QWidget

APP = _qt.application()

from test_ui_integration import STALL_LIMIT_SECONDS, IntegrationCase, activate  # noqa: E402
from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.core.clausewitz import Block, Entry, Scalar, parse, parse_file, to_json, to_source  # noqa: E402
from vic2studio.core.encoding import GAME_UNREADABLE  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.tasks import POOL_PREVIEW, POOL_RELEASE, thread_pool, wait_for_tasks  # noqa: E402
from vic2studio.ui.viewers import clausewitz_viewer  # noqa: E402
from vic2studio.ui.viewers.clausewitz_viewer import (  # noqa: E402
    EXPAND_ALL_LIMIT, RELEASE_CHUNK, ROOT_BATCH, TAB_DIAGNOSTICS, TAB_JSON, TAB_SOURCE, TAB_STRUCTURE, TABS,
    ClausewitzViewer, build_index, dismantle_load, json_chunks, json_preview, load_clausewitz,
)
from vic2studio.ui.viewers.code_view import CodeView, build_document, display_text  # noqa: E402
from vic2studio.ui.viewers.common import LOADING_DELAY_MS, ElidedLabel, format_size, severity_icon  # noqa: E402
from vic2studio.ui.widgets import make_icon, rich  # noqa: E402
from vic2studio.ui.viewers.diagnostics import (  # noqa: E402
    COL_FILE, COL_LINE, COL_MESSAGE, COL_SEVERITY, FILE_WIDTH, MESSAGE_MIN_WIDTH, DiagnosticRow, DiagnosticsModel,
    DiagnosticsView,
)

LOAD_TIMEOUT_MS = 20000
COORDINATES = ("unit", "text_position", "building_construction", "military_construction", "factory")
# La «}» de la línea 6 cierra «casa» y no «decisiones», a la que le falta (como en zulu_expancionshago.txt).
CLOSES_INNER = "decisiones = {\n\tcasa = {\n\t\tai_will_do = {\n\t\t\tfactor = 1\n\t\t}\n}\n"
# Una «}» sobrante en la línea 4, detrás de un escalar de primer nivel que no tiene nada mal.
STRAY_AFTER_SCALAR = "a = {\n\tb = 1\n}\nowner = FRA }\nc = 2\n"
# Copia desde una TextView y sale sin más, como al cerrar la aplicación.
COPY_AND_EXIT = '''
import sys
sys.path.insert(0, {src!r})
from PySide6.QtWidgets import QApplication
app = QApplication([])
from vic2studio.ui.viewers.code_view import TextView
view = TextView()
view.setPlainText("a\\u00a0b\\n")
view.selectAll()
view.copy()
print(repr(app.clipboard().text()))
'''


def positions_like(provinces: int) -> str:
    """Texto con la forma de map/positions.txt: bloques de coordenadas por provincia, en CRLF."""
    parts = []
    for n in range(1, provinces + 1):
        parts.append(f"# provincia {n}\r\n{n} =\r\n{{\r\n")
        for i, name in enumerate(COORDINATES):
            parts.append(f"\t{name}=\r\n\t{{\r\n\t\tx={n * 7 % 5000 + i}.250000\r\n\t\ty={n * 3 % 2000 + i}.500000\r\n"
                         "\t}\r\n")
        parts.append(f"\ttext_rotation={n % 6}.123456\r\n\ttext_scale={n % 3 + 1}.000000\r\n"
                     "\tbuilding_position=\r\n\t{\r\n")
        for name in ("fort", "railroad", "naval_base"):
            parts.append(f"\t\t{name}=\r\n\t\t{{\r\n\t\t\tx={n % 97}.000000\r\n\t\t\ty={n % 89}.000000\r\n\t\t}}\r\n")
        parts.append("\t}\r\n}\r\n")
    return "".join(parts)


def decisions_like(count: int) -> str:
    """Un único bloque raíz con ``count`` decisiones, como un archivo de decisions/."""
    parts = ["political_decisions = {\n"]
    for n in range(count):
        parts.append(f"\tdecision_{n} = {{\n"
                     f"\t\tpotential = {{ tag = T{n % 90:02d} NOT = {{ has_country_flag = f_{n} }} }}\n"
                     f"\t\tallow = {{ prestige = {n % 50} war = no }}\n\t\teffect = {{ add_core = {n} prestige = 5 }}\n"
                     "\t\tai_will_do = { factor = 1 }\n\t}\n")
    parts.append("}\n")
    return "".join(parts)


def many_roots(count: int) -> str:
    return "".join(f"clave_{n} = {{ valor = {n} }}\n" for n in range(count))


def provinces_like(count: int) -> str:
    """Historia de provincias con un bloque anidado cada una: ~113 bytes por provincia."""
    return "".join(f"p_{n} = {{\n\towner = ABC\n\tcore = ABC\n\ttrade_goods = grain\n\tlife_rating = {n % 50}\n"
                   f"\tpos = {{ x = {n}.5 y = {n % 977}.25 }}\n}}\n" for n in range(count))


delete_pending = _qt.delete_pending


class Heartbeat:
    """Mayor hueco (``worst``, en s) entre latidos de 10 ms del bucle de eventos dentro del ``with``."""

    def __enter__(self):
        self.gaps = []
        self._clock = QElapsedTimer()
        self._timer = QTimer()
        self._timer.setInterval(10)
        self._timer.timeout.connect(lambda: self.gaps.append(self._clock.restart()))
        self._clock.start()
        self._timer.start()
        return self

    def __exit__(self, *exc) -> None:
        self._timer.stop()
        self.gaps.append(self._clock.restart())  # lo que pasó desde el último latido también cuenta

    @property
    def worst(self) -> float:
        return max(self.gaps) / 1000


class _Message:
    """Origen mínimo de una ``DiagnosticRow``."""

    def __init__(self, text: str):
        self.text = text

    def message(self, lang: str) -> str:
        return self.text


# --- lo que se prepara en el hilo de la tarea -----------------------------------------------

class StructureIndexTests(unittest.TestCase):
    """``StructureIndex.node_at``: la entrada más profunda que contiene una posición (CP-5)."""

    def owner(self, text: str, line: int, column: int | None = None) -> tuple[str, ...] | None:
        index = build_index(parse(text).document)
        node = index.node_at(line, column)
        return None if node is None else index.key_path(node)

    def test_closing_brace_belongs_to_the_block_it_closes(self):
        self.assertEqual(self.owner(CLOSES_INNER, 6, 1), ("decisiones", "casa"))
        self.assertEqual(self.owner(CLOSES_INNER, 5, 3), ("decisiones", "casa", "ai_will_do"))
        self.assertEqual(self.owner(CLOSES_INNER, 4, 4), ("decisiones", "casa", "ai_will_do", "factor"))

    def test_unclosed_block_with_entries_on_its_line(self):
        text = "foo = { bar = 1 baz = 2\n"
        self.assertEqual(self.owner(text, 1, 7), ("foo",))  # su «{», donde lo señala unclosed_block
        self.assertEqual(self.owner(text, 1, 17), ("foo", "baz"))

    def test_positions_outside_every_entry(self):
        after_block = "b = {\n\tc = 1\n\td = 2\n}\n}\n"
        self.assertEqual(self.owner(after_block, 4, 1), ("b",))
        self.assertIsNone(self.owner(after_block, 5, 1))  # «}» sobrante tras un bloque cerrado
        self.assertIsNone(self.owner("}\nz = 1\n", 1, 1))  # «}» sobrante antes de la primera entrada
        # Un escalar acaba en su valor: la «}» sobrante de detrás no es suya.
        self.assertEqual(self.owner(STRAY_AFTER_SCALAR, 4, 11), ("owner",))
        self.assertIsNone(self.owner(STRAY_AFTER_SCALAR, 4, 13))
        same_line = "a = { b = 1 } c = 2 }\n"
        self.assertEqual(self.owner(same_line, 1, 19), ("c",))
        self.assertIsNone(self.owner(same_line, 1, 21))
        # Dentro de un bloque, lo que sobra tras un escalar («= c», sin clave) es del bloque.
        self.assertEqual(self.owner("p = { a = b = c }\n", 1, 13), ("p",))

    def test_multiline_string_ends_at_its_closing_quote(self):
        text = 'name = "a\nb" c = 1\n'
        self.assertEqual(self.owner(text, 2, 2), ("name",))
        self.assertIsNone(self.owner(text, 2, 3))
        self.assertEqual(self.owner(text, 2, 4), ("c",))
        self.assertEqual(self.owner(text, 2), ("c",))  # sin columna: la entrada que empieza en la línea
        self.assertEqual(self.owner('name = "a\r\nb\rcd"\r\nz = 1\r\n', 3, 3), ("name",))  # CRLF y CR suelto

    def test_unterminated_string_ends_on_its_last_line(self):
        # La cadena sin cerrar llega al final del archivo con su salto de línea, que está en la línea 2:
        # la línea 3, vacía, ya no es suya (antes, el final era la columna 0 de la línea 3).
        for text in ('x = 1\nname = "Mod\n', 'x = 1\nname = "Mod\r\n', 'x = 1\nname = "Mod\r'):
            with self.subTest(text=text):
                self.assertEqual(self.owner(text, 2, 12), ("name",))
                self.assertIsNone(self.owner(text, 2, 13))
                self.assertIsNone(self.owner(text, 3))
                self.assertIsNone(self.owner(text, 3, 1))
        self.assertEqual(self.owner('x = 1\nname = "Mod\nb = 2\n', 3, 5), ("name",))  # se traga «b = 2»

    def test_index_uses_the_public_end_positions(self):
        """VIEW-NF-4: los finales salen de ``Entry.value_end`` y ``Block.close_position``, no del lexer."""
        document = parse("a = { b = 1 }\nc = 2\n").document
        with mock.patch.object(Entry, "value_end", new_callable=mock.PropertyMock, return_value=(1, 40)), \
                mock.patch.object(Block, "close_position", new_callable=mock.PropertyMock, return_value=(2, 30)):
            index = build_index(document)
        self.assertEqual([(end >> 32, end & 0xFFFFFFFF) for end in index.ends], [(2, 30), (1, 40), (1, 40)])
        document.get("a").set("b", 5)  # un valor cambiado por código acaba donde empieza su entrada
        index = build_index(document)
        self.assertEqual([(end >> 32, end & 0xFFFFFFFF) for end in index.ends], [(1, 13), (1, 7), (2, 5)])
        self.assertEqual(index.ends[1], index.starts[1])

    def test_positions_match_the_shown_text_with_a_repeated_bom(self):
        """REG-VIEW-BOM-COL: con el BOM repetido, el texto que muestra el visor (``to_source``) llevaba delante
        los U+FEFF sobrantes, que las posiciones no cuentan: en la línea 1 todo se señalaba un carácter antes."""
        body = "country_event = { id = 2 }\nb = 3\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            for raw in (codecs.BOM_UTF8 * 3 + body.encode("utf-8"),
                        codecs.BOM_UTF16_LE * 2 + body.encode("utf-16-le")):
                with self.subTest(raw=raw[:4]):
                    path.write_bytes(raw)
                    load = load_clausewitz(path)
                    self.assertEqual(load.text, body)
                    lines = load.text.split("\n")
                    index = load.index
                    at = [lines[(p >> 32) - 1][(p & 0xFFFFFFFF) - 1] for p in (index.starts[0], index.ends[0])]
                    self.assertEqual(at, ["c", "}"])
                    self.assertTrue(all((row.line, row.column) == (1, 1) for row in load.rows))

    def test_ends_point_at_the_last_character_in_corpus(self):
        """VIEW-NF-4: en todo el corpus, el final de cada entrada es el último carácter de su valor en el texto
        leído: el escalar tal como se escribe o la «}» de su bloque, detrás de todo lo de dentro y antes de la
        entrada siguiente; solo los bloques sin cerrar llegan al final del archivo."""
        files = corpus_files(CLAUSEWITZ_SUFFIXES)
        if not files:
            self.skipTest("no hay corpus")
        unbounded = clausewitz_viewer._UNBOUNDED
        checked, wrong = 0, []
        for path in files:
            document = parse_file(path).document
            text = to_source(document)
            line_starts = [0] + [m.end() for m in re.finditer(r"\r\n|\r|\n", text)]
            index = build_index(document)
            starts, ends, children = index.starts, index.ends, index.children
            last = list(range(len(index)))  # último descendiente en preorden
            for node in reversed(range(len(index))):
                if children[node]:
                    last[node] = last[children[node][-1]]
            for node, entry in enumerate(index.entries):
                checked += 1
                end = ends[node]
                value = entry.value
                if end == unbounded:
                    ok = not value.is_closed
                elif starts[node] > end or (last[node] + 1 < len(index) and end >= starts[last[node] + 1]):
                    ok = False
                else:
                    at = line_starts[(end >> 32) - 1] + (end & 0xFFFFFFFF) - 1
                    if value.__class__ is Scalar:
                        written = f'"{value.text}"' if value.quoted else value.text
                        ok = text[at - len(written) + 1:at + 1] == written or (
                            value.quoted and at == len(text) - 1  # cadena sin cerrar al final del archivo
                            and text[at - len(value.text):] == '"' + value.text)
                    else:
                        ok = value.is_closed and text[at] == "}" and (
                            not children[node] or max(ends[child] for child in children[node]) < end)
                if not ok:
                    wrong.append((str(path), index.key_path(node), end >> 32, end & 0xFFFFFFFF))
        self.assertGreater(checked, 0)
        self.assertEqual(wrong[:20], [])

    def test_entries_sharing_a_line(self):
        text = "a = { c = { x = 1 } d = 2 }\n"
        self.assertEqual(self.owner(text, 1, 19), ("a", "c"))  # la «}» de c, no x
        self.assertEqual(self.owner(text, 1, 21), ("a", "d"))
        self.assertEqual(self.owner(text, 1, 27), ("a",))
        two = "a = {\n\tb = 1 c = 2\n}\n"
        self.assertEqual(self.owner(two, 2), ("a", "b"))  # sin columna: la primera que empieza en la línea
        self.assertEqual(self.owner(two, 2, 8), ("a", "c"))

    def test_expand_all_opens_the_beginning_up_to_the_limit(self):
        index = build_index(parse("r = { a = { x = 1 y = 2 } b = { z = 3 } }\ns = { t = 1 }\n").document)

        def expansion(limit, roots):
            opened, roots = index.expansion(limit, roots)
            return [index.keys[n] for n in opened], roots

        self.assertEqual(expansion(100, 2), (["r", "a", "b", "s"], 2))
        # Abrir r deja 4 filas visibles; abrir a, 6: se para ahí, sin saltar a las ramas siguientes.
        self.assertEqual(expansion(5, 2), (["r"], 2))
        self.assertEqual(expansion(1, 2), (["r"], 2))  # la primera rama, aunque no quepa
        # Una raíz que la vista aún no tiene cuesta una fila más: s (2 filas) cabe en 8, no en 7.
        self.assertEqual(expansion(8, 1), (["r", "a", "b", "s"], 2))
        self.assertEqual(expansion(7, 1), (["r", "a", "b"], 1))
        # También cuestan las raíces escalares que haya que entregar antes de la rama.
        index = build_index(parse("x = 1\ny = 2\nz = { w = 1 }\n").document)
        self.assertEqual(expansion(4, 1), (["z"], 3))

    def test_expand_all_reaches_roots_beyond_the_first_batch(self):
        """REG-3: un archivo mediano se abre entero aunque tenga más raíces que el primer lote."""
        index = build_index(parse(many_roots(ROOT_BATCH + 500)).document)
        opened, roots = index.expansion(5_000, ROOT_BATCH)
        self.assertEqual((len(opened), roots), (ROOT_BATCH + 500, ROOT_BATCH + 500))
        opened, roots = index.expansion(ROOT_BATCH * 2 + 500, ROOT_BATCH)  # 250 raíces más, de 2 filas cada una
        self.assertEqual((len(opened), roots), (ROOT_BATCH + 250, ROOT_BATCH + 250))


class PreparationTests(unittest.TestCase):
    """JSON por trozos y sin recursión (CP-4, P6) y cancelación de la carga (CP-1)."""

    def test_chunks_match_json_dumps(self):
        for text in ('a = { b = "c d\u00a0ñ" e = { 1 2 3 } }\nf = 1.5\n# nota\ng = { }\n', "", "# solo\n"):
            document = parse(text).document
            self.assertEqual("".join(json_chunks(document)),
                             json.dumps(to_json(document), ensure_ascii=False, indent=2), repr(text))

    def test_deep_nesting_without_recursion_error(self):
        depth = 5000
        document = parse("a = { " * depth + "x = 1 " + "} " * depth).document
        text, truncated = json_preview(document, limit=10 ** 6)
        self.assertTrue(truncated)
        self.assertTrue(text.startswith('{\n  "type": "block"'))

    def test_preview_stops_at_the_limit_and_converts_lazily(self):
        document = parse(many_roots(2000)).document
        full = json.dumps(to_json(document), ensure_ascii=False, indent=2)
        with mock.patch.object(clausewitz_viewer, "to_json", wraps=to_json) as converted:
            text, truncated = json_preview(document, limit=1000)
        self.assertTrue(truncated)
        self.assertLessEqual(len(text), 1000)
        self.assertTrue(full.startswith(text))
        self.assertEqual(full[len(text)], "\n", "el recorte va en un salto de línea")
        converted_nodes = [call.args[0] for call in converted.call_args_list]
        self.assertFalse(any(node is document for node in converted_nodes), "convirtió el árbol entero")
        self.assertLess(len(converted_nodes), 20, "convirtió entradas que no se iban a mostrar")
        self.assertEqual(json_preview(document, limit=len(full)), (full, False))

    def test_dismantling_an_analysis_frees_it_in_small_steps(self):
        """NF-TREE-RELEASE: soltar de una vez el árbol del parser libera millones de objetos en una sola cascada
        que no cede el GIL. Desmontado por pasos, ninguno suelta más que unos pocos miles de entradas, también
        con un único bloque raíz (decisiones) o con muchas raíces."""
        for name, text in (("decisiones", decisions_like(3000)), ("posiciones", positions_like(800)),
                           ("raíces", many_roots(30_000))):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"{name}.txt"
                path.write_bytes((text + "suelta = {\n").encode("cp1252"))  # y un diagnóstico, con su fila
                load = load_clausewitz(path)
            self.assertTrue(load.rows and load.marks, name)
            entries = len(load.index)
            enabled = gc.isenabled()
            gc.collect()
            gc.disable()  # solo el recuento de referencias libera: lo que suelta cada paso es suyo
            try:
                before = sys.getallocatedblocks()
                freed = []
                for _ in dismantle_load(load):
                    now = sys.getallocatedblocks()
                    freed.append(before - now)
                    before = now
                del load
                rest = before - sys.getallocatedblocks()
            finally:
                if enabled:
                    gc.enable()
            total = sum(freed) + rest
            self.assertGreater(total, 8 * entries, f"{name}: el análisis no se soltó")
            self.assertLess(max(freed), 16 * RELEASE_CHUNK, f"{name}: un paso soltó demasiado de una vez")
            self.assertLess(rest, 1000, f"{name}: quedó casi todo para el final")
            self.assertGreater(len(freed), entries // RELEASE_CHUNK, name)

    def test_cancelled_load_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text(many_roots(100), encoding="cp1252")
            with self.assertRaises(Cancelled):
                load_clausewitz(path, cancelled=lambda: True)
        with self.assertRaises(Cancelled):
            build_document("a = 1\n" * 100, QFont(), 10.0, cancelled=lambda: True)
        with self.assertRaises(Cancelled):
            json_preview(parse(many_roots(10)).document, cancelled=lambda: True)


# --- vistas sueltas ----------------------------------------------------------------------------

class WidgetCase(unittest.TestCase):
    def setUp(self):
        self.addCleanup(delete_pending)  # la última limpieza: después de los deleteLater de ``show``
        _qt.reset_settings()
        set_language("es")
        _qt.take_qt_messages()

    def tearDown(self):
        self.assertTrue(wait_for_tasks(10000), "quedaron tareas en segundo plano")
        _qt.process_events()
        set_language("es")
        self.assertEqual(_qt.take_qt_messages(), [], "avisos de Qt durante la prueba")

    def show(self, widget, width: int = 900, height: int = 600):
        # Tamaño mínimo propio, como MainWindow: si no, el layout lo cambia al maquetar y la
        # plataforma offscreen avisa («does not support propagateSizeHints»).
        widget.setMinimumSize(200, 200)
        widget.resize(width, height)
        widget.show()
        self.addCleanup(widget.deleteLater)
        _qt.process_events(20)
        return widget


class CodeViewTests(WidgetCase):
    def test_lines_are_the_parser_lines(self):
        """CRLF y un CR suelto separan líneas, como para el parser; U+2028 o U+FDD0 no (P8)."""
        result = parse("a = 1\rb = 2\r\nc = { # nota\u2028sigue\ufdd0y sigue\nd = 3\n")
        view = self.show(CodeView())
        view.set_source(display_text(to_source(result.document)))
        index = build_index(result.document)
        for entry, key in zip(index.entries, index.keys):
            block = view.document().findBlockByNumber(entry.line - 1)
            self.assertEqual(block.text()[entry.column - 1:][:1], key, key)
        unclosed = result.diagnostics[0]
        self.assertTrue(view.go_to_line(unclosed.line, unclosed.column))
        cursor = view.textCursor()
        self.assertEqual(cursor.block().text()[cursor.positionInBlock()], "{")

    def test_the_view_changes_width_only_with_an_empty_document(self):
        """VIEW-NF-3: QPlainTextEdit maqueta entero el documento colgado cada vez que cambia el ancho de la vista.
        La barra vertical de uno largo aparecía en diferido después de colgarlo (otros 300 ms con 1,7 M líneas),
        y el margen de los números de línea cambiaba con el documento viejo aún colgado."""
        view = self.show(CodeView())
        attached = []  # bloques del documento colgado en cada cambio de ancho

        class Spy(QObject):
            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.Resize and event.size().width() != event.oldSize().width():
                    attached.append(view.document().blockCount())
                return False

        spy = Spy(view)
        view.viewport().installEventFilter(spy)
        for lines in (20_000, 3, 120_000, 20_000, 3):
            view.set_source("a = 1\n" * lines)
            _qt.process_events(20)
            self.assertEqual(view.blockCount(), lines + 1)
            self.assertEqual(view.verticalScrollBar().isVisible(), lines > 3, lines)
        self.assertGreaterEqual(len(attached), 4, "la prueba debe cambiar el ancho de la vista")
        self.assertEqual(set(attached), {1}, "la vista cambió de ancho con un documento lleno colgado")
        self.assertEqual(view.toPlainText(), "a = 1\n" * 3, "se ve el último documento")

    def test_copy_keeps_non_breaking_spaces(self):
        text = 'nombre = "Café\u00a0Bar"\nb = 1\n'
        view = self.show(CodeView())
        view.set_source(text)
        view.selectAll()
        view.copy()
        self.assertEqual(QApplication.clipboard().text(), text)

    def test_copying_does_not_crash_the_exit(self):
        """Lo copiado se crea desde Python: el portapapeles offscreen lo destruía con el intérprete ya
        cerrado y el proceso moría al salir (señal 11)."""
        script = COPY_AND_EXIT.format(src=str(_qt.SRC))
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120,
                                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), repr("a b\n"))

    def test_many_marked_lines_slow_neither_the_cursor_nor_the_next_file(self):
        """CP-10: colgar el documento, mover el cursor o pasar al archivo siguiente no dependen de cuántas
        líneas haya marcadas (los documentos llegan hechos, como desde la tarea de carga)."""
        view = self.show(CodeView())
        lines = 50_000
        text, following = many_roots(lines), many_roots(30_000)
        marked, plain = view.document_factory()(text), view.document_factory()(following)
        with Heartbeat() as beat:
            view.set_source(text, {n: "error" for n in range(1, lines + 1)}, document=marked)
            _qt.process_events()
        self.assertLess(beat.worst, STALL_LIMIT_SECONDS, "colgar un documento con muchas marcas congela la vista")
        started = time.perf_counter()
        for _ in range(20):
            view.moveCursor(QTextCursor.MoveOperation.Down)
        _qt.process_events()
        self.assertLess(time.perf_counter() - started, STALL_LIMIT_SECONDS, "cada movimiento pasa todas las marcas")
        with Heartbeat() as beat:
            view.set_source(following, {}, document=plain)
            _qt.process_events()
        self.assertLess(beat.worst, STALL_LIMIT_SECONDS, "las marcas del archivo anterior frenan el siguiente")
        self.assertEqual(len(view.extraSelections()), 1, "solo debe quedar la línea actual")
        self.assertTrue(0 < view.highlighted_lines() < 200, "solo se colorean las líneas que se ven")

    def test_marked_lines_are_tinted(self):
        view = self.show(CodeView())
        view.set_source(many_roots(20), {2: "error", 3: "warning", 4: "info"})
        view.go_to_line(10)
        _qt.process_events(20)
        image = view.viewport().grab().toImage()
        x = view.viewport().width() - 10  # a la derecha del texto: solo fondo

        def background(line):
            rect = view.blockBoundingGeometry(view.document().findBlockByNumber(line - 1))
            return image.pixelColor(x, int(rect.translated(view.contentOffset()).center().y()))

        plain = background(6)
        tints = [background(line) for line in (2, 3, 4)]
        self.assertNotIn(plain, tints, "una línea marcada sin fondo")
        self.assertEqual(len(set(color.name() for color in tints)), 3, "cada gravedad tiene su fondo")
        self.assertNotIn(background(10), (plain, *tints), "la línea actual tiene su propio fondo")

    def test_go_to_line_before_the_view_is_shown(self):
        view = CodeView()
        self.addCleanup(view.deleteLater)
        view.set_source(many_roots(100))
        self.assertTrue(view.go_to_line(40, 3))
        self.assertEqual(view.current_line(), 40)
        self.assertFalse(view.go_to_line(500))
        self.show(view)
        self.assertEqual((view.textCursor().blockNumber(), view.textCursor().positionInBlock()), (39, 2))


class DiagnosticsViewTests(WidgetCase):
    """Tabla de diagnósticos: anchos, recortes, teclado, ratón y coste con muchas filas (VAL-8, VAL-12, LOC-6,
    REG-1, REG-2, REG-4)."""

    COLUMNS = (COL_SEVERITY, COL_FILE, COL_LINE, COL_MESSAGE)

    def table(self, rows: list[DiagnosticRow], model: DiagnosticsModel | None = None,
              width: int = 900) -> DiagnosticsView:
        model = model or DiagnosticsModel(self.COLUMNS)
        view = self.show(DiagnosticsView(model), width)
        model.set_rows(rows)
        _qt.process_events(20)
        return view

    def cell_fits(self, view: DiagnosticsView, index: QModelIndex) -> bool:
        """El texto de la celda cabe, sin recortarse, en el rectángulo que le da el estilo."""
        option = QStyleOptionViewItem()
        view.initViewItemOption(option)
        view.itemDelegate().initStyleOption(option, index)
        option.rect = view.visualRect(index)
        rect = view.style().subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, view)
        return QFontMetrics(option.font).horizontalAdvance(option.text) <= rect.width()

    def test_columns_fit_their_header_and_content(self):
        rows = [DiagnosticRow(severity, 123456, 123, _Message("m"), "c", Path("x"), "decisions/zulu_expancionshago.txt")
                for severity in ("error", "warning", "info")]
        view = self.table(rows)
        header, model = view.horizontalHeader(), view.diagnostics_model()
        bold = QFont(view.font())
        bold.setWeight(QFont.Weight.DemiBold)
        for lang in ("es", "en"):
            set_language(lang)
            model.retranslate()
            _qt.process_events(20)
            for column in (self.COLUMNS.index(COL_LINE), self.COLUMNS.index(COL_SEVERITY)):
                title = model.headerData(column, Qt.Orientation.Horizontal)
                self.assertGreaterEqual(header.sectionSize(column), QFontMetrics(bold).horizontalAdvance(title) + 16,
                                        f"{lang}: {title}")
                for row in range(len(rows)):
                    index = model.index(row, column)
                    self.assertTrue(self.cell_fits(view, index), f"{lang}: {index.data()}")

    def test_line_column_follows_the_rows_and_keeps_a_manual_width(self):
        short = [DiagnosticRow("error", 35, 24, _Message("m"), "c", Path("x"), "a.txt")]
        view = self.table(short)
        header, model = view.horizontalHeader(), view.diagnostics_model()
        line = self.COLUMNS.index(COL_LINE)
        narrow = header.sectionSize(line)
        model.set_rows(short + [DiagnosticRow("error", 123456, 123, _Message("m"), "c", Path("x"), "b.txt")])
        self.assertGreater(header.sectionSize(line), narrow, "la columna no crece con una ubicación más larga")
        self.assertTrue(self.cell_fits(view, model.index(1, line)))
        header.resizeSection(line, 200)
        model.set_filter(text="b.txt")
        self.assertEqual(header.sectionSize(line), 200, "filtrar deshace el ancho que puso el usuario")

    def test_narrow_table_has_no_horizontal_scroll_bar(self):
        """REG-2: a 1100x700 la tabla de validación mide unos 440 px: Archivo cede ancho al mensaje."""
        rows = [DiagnosticRow("warning", n, 24, _Message("mensaje " * 10), "c", Path("x"),
                              f"decisions/archivo_{n}_shago.txt") for n in range(1, 134)]
        view = self.table(rows, width=440)
        header = view.horizontalHeader()
        for lang in ("es", "en"):
            set_language(lang)
            view.diagnostics_model().retranslate()
            _qt.process_events(20)
            sizes = [header.sectionSize(i) for i in range(header.count())]
            self.assertTrue(view.verticalScrollBar().isVisible(), lang)
            self.assertLessEqual(sum(sizes), view.viewport().width(), f"{lang}: {sizes}")
            self.assertFalse(view.horizontalScrollBar().isVisible(), f"{lang}: {sizes}")
            self.assertGreaterEqual(sizes[-1], MESSAGE_MIN_WIDTH, f"{lang}: {sizes}")
        view.resize(900, 600)
        _qt.process_events(20)
        self.assertEqual(header.sectionSize(self.COLUMNS.index(COL_FILE)), FILE_WIDTH, "con sitio, Archivo no crece")

    def test_message_gets_the_width_the_other_columns_leave(self):
        """VIEW-NF-5: a 1100x700 Archivo se quedaba con 156-160 px y el mensaje con 120, y con el panel al mínimo
        (323 px) el mensaje con 100 y una barra horizontal. Entero, en su ayuda emergente."""
        long = "La clave «EVT_1_NAME» no está en ningún CSV de localisation/ del mod ni del juego base " * 2
        rows = [DiagnosticRow("warning", n, 24, _Message(long), "c", Path("x"),
                              f"events/archivos_largos/evento_{n}_shago.txt") for n in range(1, 134)]
        view = self.table(rows, width=440)
        view.setToolTip("ayuda de la tabla")  # como el panel de validación: la de la celda manda
        header, model = view.horizontalHeader(), view.diagnostics_model()
        file, message = self.COLUMNS.index(COL_FILE), self.COLUMNS.index(COL_MESSAGE)
        for width in (440, 340):  # 1100x700 con el panel como sale y al mínimo del divisor
            view.resize(width, 600)
            for lang in ("es", "en"):
                set_language(lang)
                model.retranslate()
                _qt.process_events(20)
                sizes = [header.sectionSize(i) for i in range(header.count())]
                self.assertGreaterEqual(sizes[message], 2 * sizes[file] if width == 440 else 100, f"{lang}: {sizes}")
                self.assertEqual(sizes[message], max(sizes), f"{lang}: {sizes}")
                self.assertFalse(view.horizontalScrollBar().isVisible(), f"{lang}: {sizes}")
        # Al mínimo, la cabecera «Archivo» no cabe entera: su ayuda emergente la nombra.
        self.assertEqual(model.headerData(file, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole),
                         tr("diag.col.file"))
        index = model.index(0, message)
        self.assertFalse(self.cell_fits(view, index), "el mensaje de la prueba debe verse recortado")
        pos = view.visualRect(index).center()
        QApplication.sendEvent(view.viewport(), QHelpEvent(QEvent.Type.ToolTip, pos, view.viewport().mapToGlobal(pos)))
        self.addCleanup(QToolTip.hideText)
        self.assertEqual(QToolTip.text(), long)
        # La plataforma offscreen avisa de que no sabe subir la ventana de la ayuda emergente.
        self.assertLessEqual(set(_qt.take_qt_messages()), {"QtWarningMsg: This plugin does not support raise()"})
        view.resize(1880, 600)
        _qt.process_events(20)
        self.assertEqual(header.sectionSize(file), FILE_WIDTH, "con sitio, Archivo no crece")
        self.assertGreater(header.sectionSize(message), 1200)

    def test_tab_leaves_the_table(self):
        """REG-1: Tab pasa al control siguiente, no a la celda siguiente."""
        page = QWidget()
        column = QVBoxLayout(page)
        model = DiagnosticsModel(self.COLUMNS)
        view = DiagnosticsView(model)
        following = QLineEdit()
        column.addWidget(view)
        column.addWidget(following)
        self.show(page)
        model.set_rows([DiagnosticRow("error", n, 1, _Message("m")) for n in range(1, 4)])
        page.activateWindow()
        view.setFocus()
        view.setCurrentIndex(model.index(0, 0))
        _qt.process_events(20)
        self.assertIs(page.focusWidget(), view)
        QTest.keyClick(view, Qt.Key.Key_Tab)
        _qt.process_events(20)
        self.assertIs(page.focusWidget(), following, "el foco se queda en la tabla")

    def test_row_under_the_mouse_is_highlighted(self):
        """REG-4: como en los árboles, la fila bajo el ratón cambia de fondo."""
        view = self.table([DiagnosticRow("info", n, 1, _Message("m")) for n in range(1, 8)])
        rect = view.visualRect(view.model().index(3, len(self.COLUMNS) - 1))
        point = QPoint(rect.right() - 20, rect.center().y())

        def pixel():
            return view.viewport().grab().toImage().pixelColor(point)

        before = pixel()
        QTest.mouseMove(view.viewport(), point)
        QApplication.sendEvent(view.viewport(), QHoverEvent(QEvent.Type.HoverMove, QPointF(point), QPointF(point),
                                                            QPointF(point)))
        _qt.process_events(20)
        self.assertNotEqual(pixel(), before)

    def test_paths_are_elided_on_the_left(self):
        row = DiagnosticRow("error", 1, 1, _Message("mensaje largo " * 20), "c", Path("x"),
                            "decisions/zulu_expancionshago.txt")
        view = self.table([row])
        for column, mode in ((COL_FILE, Qt.TextElideMode.ElideLeft), (COL_MESSAGE, Qt.TextElideMode.ElideRight)):
            option = QStyleOptionViewItem()
            view.initViewItemOption(option)
            view.itemDelegate().initStyleOption(option, view.model().index(0, self.COLUMNS.index(column)))
            self.assertEqual(option.textElideMode, mode, column)

    def test_many_rows_do_not_walk_the_model(self):
        calls = []

        class Counting(DiagnosticsModel):
            def rowCount(self, parent=QModelIndex()):
                calls.append(parent.isValid())
                return super().rowCount(parent)

        self.table([DiagnosticRow("error", n, 1, _Message("m")) for n in range(1, 60_001)], Counting())
        _qt.process_events(50)
        self.assertLess(len(calls), 2000, "la vista pregunta por todas las filas al maquetar")


class ViewerTests(WidgetCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.viewer = self.show(ClausewitzViewer(), 900, 700)

    def load(self, path: Path, **kwargs):
        viewer = self.viewer
        viewer.load(path, **kwargs)
        loaded = _qt.wait_until(lambda: viewer.current_load() is not None and viewer.current_load().path == path
                                and not viewer.is_busy(), LOAD_TIMEOUT_MS)
        self.assertTrue(loaded, f"{path.name} no terminó de cargar")
        return viewer.current_load()

    def open(self, name: str, text: str, **kwargs):
        path = self.folder / name
        path.write_bytes(text.encode("cp1252"))
        return self.load(path, **kwargs)

    def wait_json(self) -> None:
        viewer = self.viewer
        self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy() and (viewer.json_note.isVisible()
                                       or viewer.json_view.document().characterCount() > 1), LOAD_TIMEOUT_MS),
                        "el JSON no terminó")

    def test_diagnostic_activation_selects_the_entry_that_owns_it(self):
        cases = {  # archivo: (texto, entrada dueña del diagnóstico, gravedad)
            "cierra_otro.txt": (CLOSES_INNER, ("decisiones", "casa"), "info"),
            "misma_linea.txt": ("foo = { bar = 1 baz = 2\n", ("foo",), "error"),
            "tras_bloque.txt": ("b = {\n\tc = 1\n\td = 2\n}\n}\n", None, "error"),
            "al_principio.txt": ("}\nz = 1\n", None, "error"),
            "tras_escalar.txt": (STRAY_AFTER_SCALAR, None, "error"),
        }
        viewer = self.viewer
        for name, (text, owner, severity) in cases.items():
            load = self.open(name, text)
            index = load.index
            row = next(i for i, r in enumerate(viewer.diagnostics_model.visible_rows()) if r.severity == severity)
            marks = {index.key_path(n): s for n, s in load.marks.items()}
            if owner is None:
                self.assertEqual(marks, {}, f"{name}: icono en una entrada que no tiene nada mal")
            else:
                self.assertEqual(marks.get(owner), severity, name)
            for how in ("doble clic", "Intro"):
                viewer.reveal_node(len(index) - 1)  # otra selección: el salto tiene que cambiarla o quitarla
                viewer.select_tab(TAB_DIAGNOSTICS)
                activate(viewer.diagnostics_view, viewer.diagnostics_model.index(row, 2), how)
                node = viewer.current_node()
                self.assertEqual(None if node is None else index.key_path(node), owner, f"{name}, {how}")
                self.assertEqual(viewer.current_tab(), TAB_SOURCE)
                self.assertEqual(viewer.code.current_line(), viewer.diagnostics_model.visible_rows()[row].line)

    def test_go_to_source_from_the_menu_keeps_the_entry(self):
        """«Ir al código fuente» no vuelve a buscar la entrada por su línea (MISSED-5)."""
        load = self.open("dos.txt", "a = {\n\tb = 1 c = 2\n}\n")
        viewer = self.viewer
        b = load.index.node_at(2, 2)
        viewer.reveal_node(b)
        menu = viewer.tree_menu(b)  # sin abrirlo: offscreen no admite ventanas emergentes
        next(a for a in menu.actions() if a.text() == tr("viewer.menu.go_to_source")).trigger()
        _qt.process_events(20)
        self.assertEqual(viewer.current_node(), b)
        self.assertEqual(viewer.current_tab(), TAB_SOURCE)
        self.assertEqual((viewer.code.current_line(), viewer.code.textCursor().positionInBlock()), (2, 1))

    def test_reopening_a_file_changed_on_disk_reads_it_again(self):
        """MISSED-1: el visor no puede seguir enseñando lo que ya no hay en el archivo."""
        path = self.folder / "roto.txt"
        path.write_bytes(b"decisiones = {\n\tcasa = { a = 1 }\n")
        first = self.load(path)
        self.assertEqual([r.code for r in first.rows], ["unclosed_block"])
        self.assertIs(self.load(path), first, "sin cambios en disco se reutiliza el análisis")
        self.assertFalse(self.viewer.reload_if_changed())
        path.write_bytes(b"decisiones = {\n\tcasa = { a = 1 }\n}\n")  # corregido fuera de la aplicación
        second = self.load(path, line=2)
        self.assertIsNot(second, first)
        self.assertEqual(second.rows, [])
        self.assertEqual(self.viewer.code.current_line(), 2)
        path.write_bytes(b"otra = cosa\n")
        self.assertTrue(self.viewer.reload_if_changed())
        self.assertTrue(_qt.wait_until(lambda: self.viewer.current_load() not in (None, second)
                                       and not self.viewer.is_busy(), LOAD_TIMEOUT_MS))
        self.assertEqual(self.viewer.structure_model.index(0, 0).data(), "otra")

    def test_read_errors_are_explained_in_the_current_language(self):
        """LOC-2: el fallo mostraba el texto de la libc («Permission denied»), en inglés y sin retraducir."""
        viewer = self.viewer
        locked = self.folder / "bloqueado.txt"
        locked.write_bytes(b"a = 1\n")
        denied = PermissionError(errno.EACCES, os.strerror(errno.EACCES), os.fspath(locked))
        with mock.patch.object(clausewitz_viewer, "parse_file", side_effect=denied):  # siendo root se podría leer
            viewer.load(locked, root=self.folder)
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        self.assertIs(viewer.stack.currentWidget(), viewer.failure)
        for lang in ("en", "es"):
            set_language(lang)
            viewer.retranslate()
            reason = tr("file_error.permission")
            self.assertEqual(viewer.failure_text(), reason, lang)
            self.assertIn(reason, viewer.failure.text.text(), lang)
            self.assertNotIn("Permission denied", viewer.failure.text.text(), lang)
            self.assertEqual(viewer.header.details.text(), tr("viewer.details_failed", path="bloqueado.txt"), lang)
            self.assertEqual(viewer.failure.toolTip(),
                             tr("file_error.detail", path=os.fspath(locked), detail=os.strerror(errno.EACCES)), lang)
        # Un archivo que desaparece después de abrirlo.
        gone = self.folder / "desaparece.txt"
        gone.write_bytes(b"a = 1\n")
        self.load(gone)
        gone.unlink()
        self.assertTrue(viewer.reload_if_changed())
        self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        self.assertIsNone(viewer.current_load())
        self.assertEqual(viewer.failure_text(), tr("file_error.not_found"))
        self.assertTrue(viewer.reload_if_changed(), "un fallo de lectura se reintenta aunque no haya cambios")
        self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        self.assertEqual(viewer.failure_text(), tr("file_error.not_found"))
        gone.write_bytes(b"b = 2\n")
        self.assertTrue(viewer.reload_if_changed(), "si vuelve a aparecer, se lee")
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None and not viewer.is_busy(),
                                       LOAD_TIMEOUT_MS))
        self.assertEqual(viewer.failure_text(), "")
        self.assertIs(viewer.stack.currentWidget(), viewer.tabs)

    def test_a_read_failure_is_retried_even_if_the_file_did_not_change(self):
        """R3: arreglar un permiso (o soltar un bloqueo) no cambia la fecha ni el tamaño, y el reintento
        exigía que cambiaran. Un error interno sí espera a que el archivo cambie: reanalizar cuesta."""
        viewer = self.viewer
        path = self.folder / "bloqueado.txt"
        path.write_bytes(b"a = 1\n")
        denied = PermissionError(errno.EACCES, os.strerror(errno.EACCES), os.fspath(path))
        with mock.patch.object(clausewitz_viewer, "parse_file", side_effect=denied):
            viewer.load(path, root=self.folder)
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
            self.assertEqual(viewer.failure_text(), tr("file_error.permission"))
            self.assertTrue(viewer.reload_if_changed(), "sin arreglarlo también se reintenta")
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
            self.assertEqual(viewer.failure_text(), tr("file_error.permission"))
        self.assertTrue(viewer.reload_if_changed(), "el permiso ya está arreglado")
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None and not viewer.is_busy(),
                                       LOAD_TIMEOUT_MS))
        self.assertIs(viewer.stack.currentWidget(), viewer.tabs)
        broken = self.folder / "interno.txt"
        broken.write_bytes(b"a = 1\n")
        with mock.patch.object(clausewitz_viewer, "parse_file", side_effect=RuntimeError("fallo interno")), \
                self.assertLogs("vic2studio.ui.tasks", "WARNING"):
            viewer.load(broken, root=self.folder)
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        self.assertEqual(viewer.failure_text(), "RuntimeError: fallo interno")
        self.assertFalse(viewer.reload_if_changed(), "un error interno sin cambios en disco no se reintenta")
        broken.write_bytes(b"a = 2\n")
        os.utime(broken, ns=(time.time_ns(), time.time_ns() + 1_000_000))
        self.assertTrue(viewer.reload_if_changed())
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None and not viewer.is_busy(),
                                       LOAD_TIMEOUT_MS))

    def test_retrying_a_read_failure_keeps_it_until_there_is_an_answer(self):
        """NF-R3-HEADER-BLINK: al reintentar un fallo de lectura la cabecera pasaba un instante por
        «analizando…» antes de volver a «no se pudo leer». El fallo sigue a la vista hasta que hay respuesta
        o pasan ``LOADING_DELAY_MS``: si el archivo ya se lee pero tarda, entonces sí dice que analiza."""
        viewer = self.viewer
        path = self.folder / "bloqueado.txt"
        path.write_bytes(b"a = 1\n")
        failed = tr("viewer.details_failed", path=path.name)
        seen = []
        set_details = viewer.header.set_details

        def record(text: str, *rest) -> None:
            seen.append((text, viewer.stack.currentWidget() is viewer.failure))
            set_details(text, *rest)

        denied = PermissionError(errno.EACCES, os.strerror(errno.EACCES), os.fspath(path))
        with mock.patch.object(clausewitz_viewer, "parse_file", side_effect=denied):
            viewer.load(path, root=self.folder)
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
            with mock.patch.object(viewer.header, "set_details", record):
                self.assertTrue(viewer.reload_if_changed())
                self.assertEqual(viewer.failure_text(), tr("file_error.permission"), "mientras se reintenta")
                self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
                _qt.process_events(2 * LOADING_DELAY_MS)
        self.assertTrue(seen)
        self.assertEqual(set(seen), {(failed, True)}, "un reintento que vuelve a fallar no parpadea")
        # Ya se puede leer, pero tarda: el fallo sigue hasta el plazo; luego, la página de carga.
        gate = threading.Event()
        parse_file = clausewitz_viewer.parse_file

        def slow(*args, **kwargs):
            gate.wait(LOAD_TIMEOUT_MS / 1000)
            return parse_file(*args, **kwargs)

        try:
            with mock.patch.object(clausewitz_viewer, "parse_file", slow):
                self.assertTrue(viewer.reload_if_changed())
                self.assertIs(viewer.stack.currentWidget(), viewer.failure)
                self.assertEqual(viewer.header.details.text(), failed)
                self.assertTrue(_qt.wait_until(lambda: viewer.stack.currentWidget() is viewer.loading,
                                               LOAD_TIMEOUT_MS))
                self.assertEqual(viewer.header.details.text(), tr("viewer.details_loading", path=path.name))
                self.assertEqual(viewer.failure_text(), "")
                gate.set()
                self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None and not viewer.is_busy(),
                                               LOAD_TIMEOUT_MS))
        finally:
            gate.set()
        loaded = tr("viewer.details_one", path=path.name, encoding="Windows-1252", lines="1", size=format_size(6))
        self.assertIs(viewer.stack.currentWidget(), viewer.tabs)
        self.assertEqual(viewer.header.details.text(), loaded)
        # Si responde antes del plazo, el análisis sustituye directamente al fallo.
        with mock.patch.object(clausewitz_viewer, "parse_file", side_effect=denied):
            viewer.load(self.folder / "otro.txt", root=self.folder)  # sin crear: falla
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
            viewer.load(path, root=self.folder)
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        self.assertEqual(viewer.header.details.text(), failed)
        viewer._loading_timer.setInterval(10 * LOAD_TIMEOUT_MS)  # que responda antes aunque la máquina vaya lenta
        self.assertTrue(viewer.reload_if_changed())
        self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        self.assertIs(viewer.stack.currentWidget(), viewer.tabs)
        self.assertEqual(viewer.header.details.text(), loaded)
        self.assertEqual(viewer.failure_text(), "")

    def record_releases(self) -> tuple[list, list]:
        """``(entregas, pasos)``: lo que se ve de cada análisis al soltarlo y en qué hilo corre cada paso.

        Cada entrega es ``(visto, ruta)`` con ``visto`` lo que de ese análisis seguía en las vistas en ese
        momento; cada paso, ``(hilo, inicio, fin)`` (``time.perf_counter``).
        """
        viewer, handed, steps = self.viewer, [], []
        original_release, original_dismantle = clausewitz_viewer.release_in_background, dismantle_load

        def release(load, dismantle):
            rows = {id(row) for row in load.rows}
            seen = [what for what, used in (
                ("estructura", viewer.structure_model._index is load.index),
                ("diagnósticos", any(id(row) in rows for row in viewer.diagnostics_model.all_rows())),
                ("JSON", viewer._json_for is load), ("visor", viewer._load is load),
                ("documento", load.document is not None)) if used]
            handed.append((seen, load.path.name))
            original_release(load, dismantle)

        def dismantle(load):
            iterator = original_dismantle(load)
            while True:
                clock = time.perf_counter()
                try:
                    next(iterator)
                except StopIteration:
                    return
                finally:
                    steps.append((threading.get_ident(), clock, time.perf_counter()))
                yield

        for name, value in (("release_in_background", release), ("dismantle_load", dismantle)):
            patcher = mock.patch.object(clausewitz_viewer, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return handed, steps

    def test_an_analysis_that_arrives_already_superseded_is_released_off_the_interface_thread(self):
        """R2-STALE-RESULT-UI-THREAD: un análisis que terminó cuando ya se había pedido otro archivo se soltaba
        de una sola cascada en el hilo de la interfaz (0,5 s con 20 MB) al llegar su entrega ya superada."""
        viewer = self.viewer
        handed, _ = self.record_releases()
        big, small = self.folder / "grande.txt", self.folder / "b.txt"
        big.write_bytes(provinces_like(2000).encode("cp1252"))
        small.write_bytes(b"a = 1\n")
        viewer.load(big)
        # Sin procesar eventos: la tarea termina y su entrega queda en la cola del hilo de la interfaz.
        self.assertTrue(thread_pool(POOL_PREVIEW).waitForDone(LOAD_TIMEOUT_MS))
        viewer.load(small)  # supera al grande, que ya terminó
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None
                                       and viewer.current_load().path == small and not viewer.is_busy(),
                                       LOAD_TIMEOUT_MS))
        self.assertIn(([], "grande.txt"), handed, "el análisis superado no se soltó en segundo plano")

    def test_a_cancelled_analysis_is_dismantled_in_steps(self):
        """R2-CANCELLED-LOAD-CASCADE: al cancelar un análisis a medias (dejar el archivo mientras aún se
        indexaba), la excepción soltaba el árbol y el índice parcial de una sola cascada, con el GIL tomado
        (0,2-0,5 s de interfaz parada con 20 MB). Ahora se desmontan por pasos antes de salir."""
        path = self.folder / "grande.txt"
        path.write_bytes(provinces_like(9000).encode("cp1252"))  # ~72 000 entradas: pasa del control de 65 536
        seen = {}
        original_parse, original_index = clausewitz_viewer.parse_file, clausewitz_viewer.build_index

        def parse(*args, **kwargs):
            seen["result"] = original_parse(*args, **kwargs)
            return seen["result"]

        def build(block, cancelled=None, index=None):
            seen["index"] = index
            return original_index(block, cancelled, index)

        def cancelled():  # se cancela cuando el índice ya tiene entradas (en su segundo control)
            index = seen.get("index")
            return index is not None and len(index.entries) > 0

        with mock.patch.object(clausewitz_viewer, "parse_file", parse), \
                mock.patch.object(clausewitz_viewer, "build_index", build):
            with self.assertRaises(Cancelled):
                clausewitz_viewer.load_clausewitz(path, None, cancelled)
        result, index = seen["result"], seen["index"]
        self.assertEqual(result.document.entries, [], "el árbol no se desmontó")
        self.assertEqual(result.diagnostics, [])
        # Las listas retienen objetos (entradas, textos): se vacían por pasos. Los ``array`` de enteros se
        # liberan de una vez sin cascada, igual que en ``dismantle_load``.
        holders = [name for name in index.__dataclass_fields__ if isinstance(getattr(index, name), (list, dict))]
        self.assertIn("entries", holders)
        self.assertEqual({name: len(getattr(index, name)) for name in holders}, dict.fromkeys(holders, 0),
                         "el índice a medias no se desmontó")

    def test_an_analysis_no_longer_shown_is_released_off_the_interface_thread(self):
        """NF-TREE-RELEASE: al cambiar de archivo, al fallar la lectura y al vaciar el visor, el análisis
        anterior se suelta por pasos en el hilo de una tarea, y solo cuando ya no lo usa ninguna vista."""
        viewer = self.viewer
        handed, steps = self.record_releases()
        for name in ("a.txt", "b.txt", "c.txt"):
            (self.folder / name).write_bytes(b"a = {\n\tb = 1\n")  # con un diagnóstico
        viewer.select_tab(TAB_JSON)
        self.open("a.txt", "a = {\n\tb = 1\n")
        self.wait_json()
        self.load(self.folder / "b.txt")  # cambiar de archivo
        locked = self.folder / "c.txt"
        denied = PermissionError(errno.EACCES, os.strerror(errno.EACCES), os.fspath(locked))
        with mock.patch.object(clausewitz_viewer, "parse_file", side_effect=denied):
            viewer.load(locked)  # no se puede leer
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        self.assertEqual((viewer.structure_model.rowCount(), viewer.diagnostics_model.all_rows()), (0, []),
                         "con el fallo a la vista no queda nada del análisis anterior")
        self.load(self.folder / "a.txt")
        viewer.clear()  # vaciar el visor
        self.assertTrue(wait_for_tasks(LOAD_TIMEOUT_MS))
        self.assertEqual(handed, [([], "a.txt"), ([], "b.txt"), ([], "a.txt")])
        self.assertTrue(steps)
        self.assertNotIn(threading.get_ident(), {step[0] for step in steps}, "se soltó en el hilo de la interfaz")

    def test_switching_away_from_a_large_file_does_not_stall_the_interface(self):
        """NF-TREE-RELEASE: al pasar de un archivo de 20 MB a uno pequeño, soltar el árbol del primero paraba
        la interfaz ~0,9 s. Con ~5 MB: el mayor hueco del latido no llega a la mitad de lo que tarda en soltarse."""
        viewer = self.viewer
        _, steps = self.record_releases()
        big = self.folder / "grande.txt"
        big.write_bytes(provinces_like(46_000).encode("cp1252"))
        viewer.load(big)
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None and not viewer.is_busy(),
                                       6 * LOAD_TIMEOUT_MS), "el archivo grande no terminó de cargar")
        _qt.process_events(50)
        small = self.folder / "pequeño.txt"
        small.write_bytes(b"a = 1\n")
        with Heartbeat() as beat:
            viewer.load(small)
            self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None
                                           and viewer.current_load().path == small, LOAD_TIMEOUT_MS))
            # Sin bloquear el bucle de eventos (``wait_for_tasks`` lo haría): hasta que termine de soltarlo.
            self.assertTrue(_qt.wait_until(lambda: thread_pool(POOL_RELEASE).activeThreadCount() == 0,
                                           LOAD_TIMEOUT_MS))
        self.assertGreater(len(steps), 100)
        took = steps[-1][2] - steps[0][1]  # en el hilo que lo suelte: el de la interfaz, si se congela
        print(f"\n[ui] soltar {big.stat().st_size / 1e6:.1f} MB: {took * 1000:.0f} ms en {len(steps)} pasos; "
              f"mayor hueco del bucle de eventos {beat.worst * 1000:.0f} ms", file=sys.stderr)
        self.assertNotIn(threading.get_ident(), {step[0] for step in steps})
        self.assertLess(beat.worst, took / 2, "soltar el archivo grande congeló la interfaz")
        self.assertLess(beat.worst, STALL_LIMIT_SECONDS)

    def test_a_file_the_game_cannot_read_says_so_in_the_header(self):
        """NF-7: la cabecera mostraba «utf-16», «utf-16-be-bom»… tal cual y, sin avisos, «Sin errores»; y la
        pestaña Diagnósticos, con la cabecera ya en rojo, seguía con la marca verde de «Sin diagnósticos».
        Desde que parse_file da ``unreadable_encoding``, esa pestaña muestra el error en la tabla."""
        known = GAME_UNREADABLE | {"cp1252", "utf-8", "utf-8-sig"}
        self.assertLessEqual(known, set(clausewitz_viewer.ENCODING_NAMES))
        viewer = self.viewer
        empty, tab = viewer.diagnostics_empty, clausewitz_viewer.TABS.index(clausewitz_viewer.TAB_DIAGNOSTICS)

        def diagnostics_tab():
            return (viewer.tabs.tabIcon(tab).cacheKey(), viewer.diagnostics_stack.currentWidget() is empty,
                    empty.medallion.icon_name(), empty.title.text(), empty.text.text())

        text = "a = { b = 1 }\n"  # solo ASCII: el único diagnóstico es el de la codificación
        files = {"utf-16": b"\xff\xfe" + text.encode("utf-16-le"),
                 "utf-16-be-bom": b"\xfe\xff" + text.encode("utf-16-be"),
                 "utf-16-le": text.encode("utf-16-le"), "utf-16-be": text.encode("utf-16-be")}
        for encoding, data in files.items():
            path = self.folder / f"{encoding}.txt"
            path.write_bytes(data)
            load = self.load(path, root=self.folder)
            self.assertEqual(load.result.encoding, encoding)
            self.assertEqual([(row.severity, row.code, row.line, row.column) for row in load.rows],
                             [("error", "unreadable_encoding", 1, 1)])
            name = clausewitz_viewer.ENCODING_NAMES[encoding]
            # Literal, no sacado del propio diccionario: cruzar dos etiquetas tiene que hacer fallar la prueba.
            big, bom = {"utf-16": (False, True), "utf-16-be-bom": (True, True),
                        "utf-16-le": (False, False), "utf-16-be": (True, False)}[encoding]
            self.assertEqual(("BE" in name, "LE" in name, "BOM" in name), (big, not big, bom), encoding)
            for lang in ("es", "en"):
                set_language(lang)
                viewer.retranslate()
                # Que el juego no puede leerlo lo dice la insignia (y su ayuda), no la línea de detalles.
                self.assertEqual(viewer.header.details.text(), tr(
                    "viewer.details_one", path=path.name, encoding=name, lines="1", size=format_size(len(data))),
                    lang)
                self.assertEqual((viewer.header.badge.level, viewer.header.badge.label.text()),
                                 ("error", tr("viewer.summary_unreadable")), lang)
                self.assertEqual(viewer.header.badge.toolTip(), tr("viewer.unreadable_tooltip", encoding=name), lang)
                self.assertEqual(diagnostics_tab()[:2], (severity_icon("error").cacheKey(), False), lang)
            set_language("es")
        # Con algo que no es ASCII el parser avisa de la codificación; la pestaña sigue diciendo error.
        path = self.folder / "utf-16-acentos.txt"
        path.write_bytes(b"\xff\xfe" + 'a = { b = "Ñandú" }\n'.encode("utf-16-le"))
        self.assertTrue(self.load(path, root=self.folder).rows)
        self.assertEqual(viewer.tabs.tabIcon(tab).cacheKey(), severity_icon("error").cacheKey())
        self.open("ansi.txt", text + "c = 2\n")
        self.assertIn(" · Windows-1252 · 2 líneas · ", viewer.header.details.text())
        self.assertEqual(viewer.header.badge.level, "ok")
        self.assertEqual(diagnostics_tab(), (make_icon("check", "success").cacheKey(), True, "check",
                                             tr("viewer.no_diagnostics_title"), rich(tr("viewer.no_diagnostics_text"))))

    def test_a_narrow_header_shortens_the_path_first(self):
        """Con la ventana al mínimo, el recorte en medio de la cabecera se comía la codificación
        («decisions/somaliland_sha…52 · 2 líneas»): ahora se acorta antes la ruta, y si ni así cabe, el final."""
        details = self.viewer.header.details
        path = self.folder / "decisions" / "somaliland_shago_con_un_nombre_largo.txt"
        path.parent.mkdir()
        path.write_bytes(b"a = 1\nb = 2\n")
        self.load(path, root=self.folder)
        tail = f" · Windows-1252 · 2 líneas · {format_size(12)}"
        full = "decisions/somaliland_shago_con_un_nombre_largo.txt" + tail
        self.assertEqual((details.text(), details.toolTip(), details.displayed_text()), (full, full, full))
        metrics = details.fontMetrics()
        for room in (metrics.horizontalAdvance(full) // 2, metrics.horizontalAdvance("dec…txt" + tail) + 4):
            details.setFixedWidth(room)
            shown = details.displayed_text()
            self.assertTrue(shown.endswith(tail) and "…" in shown and shown[0] == "d", (room, shown))
            self.assertLessEqual(metrics.horizontalAdvance(shown), room)
        details.setFixedWidth(metrics.horizontalAdvance("… · Windows-1252 · 2 lí"))
        shown = details.displayed_text()
        self.assertTrue(shown.startswith("… · Windows-1252 · ") and shown.endswith("…"), shown)
        # Fuera de la cabecera (p. ej. el archivo de «Localización») se recorta como siempre.
        label = ElidedLabel(mode=Qt.TextElideMode.ElideRight)
        self.addCleanup(label.deleteLater)
        label.setText(full)
        label.setFixedWidth(metrics.horizontalAdvance(full) // 2)
        self.assertEqual(label.displayed_text(), label.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight,
                                                                              label.contentsRect().width()))

    def test_header_uses_the_latest_root(self):
        """NEW-2: con el mismo archivo, la cabecera seguía con la ruta relativa a la raíz de la carga anterior."""
        viewer = self.viewer
        mod = self.folder / "mod"
        path = mod / "common" / "a.txt"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"a = 1\nb = 2\nc = 3\n")
        release = threading.Event()
        self.addCleanup(release.set)
        original = clausewitz_viewer.try_load_clausewitz
        with mock.patch.object(clausewitz_viewer, "try_load_clausewitz",
                               lambda *args: release.wait(LOAD_TIMEOUT_MS / 1000) and original(*args)):
            viewer.load(path, root=mod)
            viewer.load(path, root=self.folder, line=3)  # mientras se analiza
            self.assertEqual(viewer.header.details.text(), tr("viewer.details_loading", path="mod/common/a.txt"))
            viewer.load(path, root=self.folder)  # pedirlo otra vez sin línea no anula la de antes
            release.set()
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        load = viewer.current_load()
        self.assertTrue(viewer.header.details.text().startswith("mod/common/a.txt · "), viewer.header.details.text())
        self.assertEqual(viewer.code.current_line(), 3)
        viewer.load(path, root=mod)  # sin cambios: reutiliza el análisis, pero con la nueva raíz
        self.assertIs(viewer.current_load(), load)
        self.assertTrue(viewer.header.details.text().startswith("common/a.txt · "), viewer.header.details.text())

    def test_roots_are_handed_to_the_view_in_batches(self):
        load = self.open("raices.txt", many_roots(2 * ROOT_BATCH + 500))
        model, tree = self.viewer.structure_model, self.viewer.tree
        self.assertEqual(model.rowCount(), ROOT_BATCH)
        bar = tree.verticalScrollBar()
        self.assertTrue(_qt.wait_until(lambda: bar.maximum() > 0), "la vista no maquetó las raíces")
        bar.setValue(bar.maximum())
        _qt.process_events(20)
        self.assertEqual(model.rowCount(), 2 * ROOT_BATCH, "llegar al final trae el siguiente lote")
        last = len(load.index) - 1
        self.assertEqual(model.node_of(self.viewer.reveal_node(last)), last)
        self.assertEqual(model.rowCount(), len(load.index.roots))
        self.assertEqual(self.viewer.current_node(), last)
        self.assertEqual(model.index(len(load.index.roots) - 1, 0).data(), f"clave_{2 * ROOT_BATCH + 499}")

    def test_expand_all_opens_every_root_that_fits(self):
        """REG-3: «Expandir todo» abre también las raíces que aún no se habían entregado a la vista."""
        load = self.open("medio.txt", many_roots(ROOT_BATCH + 500))
        model, tree = self.viewer.structure_model, self.viewer.tree
        self.assertEqual(model.rowCount(), ROOT_BATCH)
        self.viewer.expand_all()
        _qt.process_events(20)
        self.assertEqual(model.rowCount(), len(load.index.roots))
        self.assertTrue(all(tree.isExpanded(model.index(row, 0)) for row in range(model.rowCount())))
        # Si no caben todas, se entregan solo las que se abren y las filas visibles no pasan del límite.
        self.open("grande.txt", many_roots(3 * ROOT_BATCH))
        self.viewer.expand_all()
        _qt.process_events(20)
        expanded = [row for row in range(model.rowCount()) if tree.isExpanded(model.index(row, 0))]
        self.assertLessEqual(model.rowCount() + len(expanded), EXPAND_ALL_LIMIT)
        self.assertEqual(len(expanded), model.rowCount(), "se entregaron raíces que no se abren")

    def test_search_matches_are_painted(self):
        """El fondo de las coincidencias se ve aunque la hoja de estilo ignore ``BackgroundRole`` (CP-11)."""
        self.open("busca.txt", "".join(f"tag_{n} = TAG\notro_{n} = 1\n" for n in range(5)))
        viewer = self.viewer
        match = viewer.structure_model.index(4, 2)  # tag_2: coincide, pero no es la actual

        def pixel():
            _qt.process_events(20)
            rect = viewer.tree.visualRect(match)
            return viewer.tree.viewport().grab().toImage().pixelColor(rect.right() - 4, rect.center().y())

        before = pixel()
        viewer.set_search("tag")
        self.assertEqual(len(viewer.matches()), 5)
        self.assertNotEqual(viewer.current_node(), viewer.structure_model.node_of(match))
        self.assertNotEqual(pixel(), before)

    def test_crlf_file_shows_the_parser_lines_and_its_exact_json(self):
        """CP-15: casi todos los .txt del juego son CRLF; el código y el JSON conservan los espacios duros."""
        load = self.open("crlf.txt", 'owner = FRA\r\nname = "Café\u00a0Bar"\r\n1861.1.1 = { railroad = 3 }\r\n')
        viewer = self.viewer
        expected = display_text(to_source(load.result.document))
        self.assertNotIn("\r", expected)
        self.assertEqual(viewer.code.text_document().toRawText().replace("\u2029", "\n"), expected)
        viewer.select_tab(TAB_JSON)
        self.wait_json()
        shown = viewer.json_view.document().toRawText().replace("\u2029", "\n")
        self.assertEqual(json.loads(shown), to_json(load.result.document))

    def test_json_failure_replaces_the_pending_message(self):
        """MISSED-6: si el JSON falla, la vista no sigue diciendo que se está generando."""
        self.open("a.txt", "a = 1\n")
        with mock.patch.object(clausewitz_viewer, "_prepare_json", side_effect=RuntimeError("fallo de prueba")), \
                self.assertLogs("vic2studio.ui.tasks", "WARNING"):
            self.viewer.select_tab(TAB_JSON)
            self.wait_json()
        self.assertIn("fallo de prueba", self.viewer.json_note.text())
        self.assertEqual(self.viewer.json_view.placeholderText(), "")

    def test_deeply_nested_file_shows_its_json(self):
        depth = 5000
        self.open("hondo.txt", "a = { " * depth + "x = 1 " + "} " * depth)
        self.viewer.select_tab(TAB_JSON)
        self.wait_json()
        self.assertTrue(self.viewer.json_view.toPlainText().startswith("{"))
        self.assertNotIn("Recursion", self.viewer.json_note.text())

    def test_truncated_json_note_follows_the_language(self):
        """CP-13: el tamaño de la nota se formatea con el idioma actual, no con el de cuando se generó."""
        self.open("muchas.txt", many_roots(500))
        with mock.patch.object(clausewitz_viewer, "JSON_DISPLAY_LIMIT", 3000):
            self.viewer.select_tab(TAB_JSON)
            self.wait_json()
        shown = len(self.viewer.json_view.document().toRawText().replace("\u2029", "\n").encode("utf-8"))
        sizes = {}
        for lang in ("es", "en"):
            set_language(lang)
            self.viewer.retranslate()
            sizes[lang] = format_size(shown)
            self.assertIn(sizes[lang], self.viewer.json_note.text(), lang)
        self.assertNotEqual(sizes["es"], sizes["en"])

    def test_compact_mode_moves_the_json_caption_to_tooltips(self):
        viewer = self.viewer
        json_tab = TABS.index(TAB_JSON)
        viewer.set_compact(True)
        caption = viewer.json_caption.text()
        self.assertTrue(caption)
        self.assertTrue(viewer.json_caption.isHidden())
        self.assertEqual((viewer.json_view.toolTip(), viewer.tabs.tabToolTip(json_tab)), (caption, caption))
        viewer.set_compact(False)
        self.assertFalse(viewer.json_caption.isHidden())
        self.assertEqual((viewer.json_view.toolTip(), viewer.tabs.tabToolTip(json_tab)), ("", ""))


# --- con la ventana completa -------------------------------------------------------------------

class MainWindowViewerTests(IntegrationCase):
    """Latido del bucle de eventos con archivos grandes, pestañas a 1100x700 y recarga al validar."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        cls.large = []
        for name, text in (("positions.txt", positions_like(2700)), ("raices.txt", many_roots(40_000)),
                           ("decisiones.txt", decisions_like(6000))):
            path = folder / name
            path.write_bytes(text.encode("cp1252"))
            cls.large.append(path)

    def setUp(self):
        delete_pending()  # el trabajo de ventanas de otras pruebas aún vivas falsearía el latido
        super().setUp()
        self.addCleanup(delete_pending)

    def check_responsive(self, beat: Heartbeat, what: str) -> None:
        print(f"\n[ui] {what}: mayor hueco del bucle de eventos {beat.worst * 1000:.0f} ms", file=sys.stderr)
        self.assertLess(beat.worst, STALL_LIMIT_SECONDS, f"{what}: la interfaz se congeló")

    def test_large_files_keep_the_interface_responsive(self):
        """CP-1, CP-2, CP-4, FI-4: abrir, expandir todo, cambiar de idioma y ver el código y el JSON con
        ~1,5 MB: muchos bloques pequeños, 40 000 raíces o un único bloque con 6000 decisiones."""
        for path in self.large:
            size = f"{path.name}, {path.stat().st_size / 1e6:.1f} MB"
            with Heartbeat() as beat:
                viewer = self.open_clausewitz(path)
            self.check_responsive(beat, f"abrir {size}")
            with Heartbeat() as beat:
                viewer.expand_all()
                _qt.process_events(50)
            self.check_responsive(beat, f"expandir todo {size}")
            self.assertTrue(viewer.tree.isExpanded(viewer.structure_model.index(0, 0)))
            with Heartbeat() as beat:
                set_language("en")
                _qt.process_events(50)
            self.check_responsive(beat, f"cambiar de idioma {size}")
            self.assertEqual(viewer.tabs.tabText(0), "Structure")
            set_language("es")
            with Heartbeat() as beat:
                viewer.select_tab(TAB_SOURCE)
                _qt.process_events(50)
            self.check_responsive(beat, f"ver el código {size}")
            with Heartbeat() as beat:
                viewer.select_tab(TAB_JSON)
                self.wait(lambda: not viewer.is_busy() and viewer.json_view.document().characterCount() > 1,
                          "el JSON no terminó")
                _qt.process_events(50)
            self.check_responsive(beat, f"ver el JSON {size}")
            viewer.select_tab(TAB_STRUCTURE)  # el siguiente archivo se abre en la Estructura

    def test_viewer_tabs_fit_at_the_minimum_window_size(self):
        """CP-14: a 1100x700 las cuatro pestañas caben sin recortar «Estructura»."""
        mod = FIXTURE_ROOT / "VSM"
        self.window.resize(1100, 700)
        self.set_mod(mod)
        viewer = self.open_clausewitz(mod / "decisions" / "zulu_expancionshago.txt", tab=TAB_JSON)
        bar = viewer.tabs.tabBar()
        for lang in ("es", "en"):
            set_language(lang)
            _qt.process_events(50)
            needed = sum(bar.tabSizeHint(i).width() for i in range(bar.count()))
            self.assertLessEqual(needed, viewer.tabs.width(), lang)
            self.assertGreaterEqual(bar.tabRect(0).left(), 0, lang)

    def test_validation_table_fits_at_the_minimum_window_size(self):
        """REG-2: a 1100x700 la tabla de validación del mod de muestra cabe sin barra horizontal."""
        self.window.resize(1100, 700)
        self.set_mod(FIXTURE_ROOT / "VSM")
        self.assertTrue(self.project.validate_mod())
        self.wait(lambda: self.project.validation_report() is not None, "la validación no terminó")
        view = self.project.validation.view
        header = view.horizontalHeader()
        for lang in ("es", "en"):
            set_language(lang)
            _qt.process_events(50)
            sizes = [header.sectionSize(i) for i in range(header.count())]
            self.assertLessEqual(sum(sizes), view.viewport().width(), f"{lang}: {sizes}")
            self.assertFalse(view.horizontalScrollBar().isVisible(), f"{lang}: {sizes}")

    def test_validating_again_reloads_a_file_fixed_outside(self):
        """MISSED-1: tras corregir el archivo en otro editor y volver a validar, el visor lo relee."""
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "mod" / "Arreglo"
            (mod / "decisions").mkdir(parents=True)
            path = mod / "decisions" / "roto.txt"
            path.write_bytes(b"political_decisions = {\n\tcasa = { a = 1 }\n")
            self.set_mod(mod)
            viewer = self.open_clausewitz(path)
            self.assertEqual(len(viewer.current_load().result.errors), 1)
            path.write_bytes(b"political_decisions = {\n\tcasa = { a = 1 }\n}\n")
            self.assertTrue(self.project.validate_mod())
            self.wait(lambda: self.project.validation_report() is not None, "la validación no terminó")
            self.assertEqual(self.project.validation_report().files_with(), [])
            self.wait(lambda: not viewer.is_busy() and viewer.current_load() is not None
                      and not viewer.current_load().result.errors, "el visor sigue mostrando el archivo viejo")
            self.assertEqual(viewer.header.badge.level, "ok")


if __name__ == "__main__":
    unittest.main()


class RetryEndingInFailureTests(WidgetCase):
    """R2-ONFAILED-TIMER-UNTESTED: ningún reintento acababa por la señal ``failed``; sin el ``timer.stop()`` de
    ``_on_failed`` el visor se quedaba en «cargando…» para siempre, con el error borrado y sin tarea en curso."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_image_retry_ending_in_failed_keeps_the_failure(self):
        from PIL import Image

        from vic2studio.ui.viewers import image_viewer

        viewer = self.show(image_viewer.ImageViewer(), 600, 500)
        path = self.folder / "b.png"
        Image.new("RGB", (8, 6)).save(path)
        denied = PermissionError(errno.EACCES, os.strerror(errno.EACCES), os.fspath(path))
        with mock.patch.object(image_viewer, "open", side_effect=denied, create=True):
            viewer.load(path, root=self.folder)
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        with mock.patch.object(image_viewer, "try_load_image", side_effect=MemoryError("sin memoria")), \
                self.assertLogs("vic2studio.ui.tasks", "WARNING"):
            self.assertTrue(viewer.reload_if_changed())
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
            _qt.process_events(2 * LOADING_DELAY_MS)  # el temporizador de «cargando…» ya habría saltado
        self.assertIs(viewer.stack.currentWidget(), viewer.failure)
        self.assertEqual(viewer.error(), "sin memoria")

    def test_script_retry_ending_in_failed_keeps_the_failure(self):
        viewer = self.show(ClausewitzViewer(), 900, 600)
        path = self.folder / "b.txt"
        path.write_bytes(b"a = 1\n")
        denied = PermissionError(errno.EACCES, os.strerror(errno.EACCES), os.fspath(path))
        with mock.patch.object(clausewitz_viewer, "parse_file", side_effect=denied):
            viewer.load(path, root=self.folder)
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
        with mock.patch.object(clausewitz_viewer, "try_load_clausewitz", side_effect=MemoryError("sin memoria")), \
                self.assertLogs("vic2studio.ui.tasks", "WARNING"):
            self.assertTrue(viewer.reload_if_changed())
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), LOAD_TIMEOUT_MS))
            _qt.process_events(2 * LOADING_DELAY_MS)
        self.assertIs(viewer.stack.currentWidget(), viewer.failure)
        self.assertEqual(viewer.failure_text(), "MemoryError: sin memoria")


class CountTextTests(WidgetCase):
    """R2-SINGULAR-TEXT-UNTESTED y R2-PLURAL-BYTES: las pruebas de NF-SINGULAR-LINE sacaban lo esperado de la
    misma clave que usa el código; aquí el texto es literal (0, 1 y 2 líneas, y 1 byte)."""

    def test_line_and_byte_counts_read_naturally(self):
        viewer = self.show(ClausewitzViewer(), 1400, 600)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        expected = {"es": (" · 0 líneas · 0 bytes", " · 1 línea · 1 byte", " · 2 líneas · 12 bytes"),
                    "en": (" · 0 lines · 0 bytes", " · 1 line · 1 byte", " · 2 lines · 12 bytes")}
        for i, data in enumerate((b"", b"a", b"a = 1\nb = 2\n")):
            path = folder / f"f{i}.txt"
            path.write_bytes(data)
            viewer.load(path, root=folder)
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy() and viewer.current_load() is not None
                                           and viewer.current_load().path == path, LOAD_TIMEOUT_MS))
            for lang in ("es", "en"):
                set_language(lang)
                viewer.retranslate()
                self.assertTrue(viewer.header.details.text().endswith(expected[lang][i]),
                                (lang, viewer.header.details.text()))
            set_language("es")
