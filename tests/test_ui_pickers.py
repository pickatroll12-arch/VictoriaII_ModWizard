"""Selectores básicos de la iteración 4 (wizard §13.7): valor, confirmación, validación y textos ES/EN."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402

APP = _qt.application()

from vic2studio.core.clausewitz.nodes import ClausewitzDate  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.pickers import (  # noqa: E402
    ColorField,
    DateEdit,
    GoodsAmountsField,
    NameListEditor,
    SpriteFramePicker,
    SymbolPicker,
    similar_colors,
)


class _Index:
    def __init__(self, names):
        self._names = names

    def names(self, kind):
        return list(self._names.get(kind, ()))

    def get(self, kind, name):
        return None


class _Session:
    def __init__(self, names):
        self.index = _Index(names)

    def display(self, symbol):
        return symbol.name


class PickerCase(unittest.TestCase):
    def setUp(self):
        set_language("es")
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.deleteLater()
        _qt.process_events()
        set_language("es")

    def keep(self, widget):
        self.widgets.append(widget)
        self.committed = []
        widget.value_committed.connect(self.committed.append)
        return widget


class SymbolPickerTests(PickerCase):
    def test_known_names_commit_and_unknown_ones_do_not(self):
        picker = self.keep(SymbolPicker(_Session({"tag": ["AAA", "BBB"]}), "tag"))
        self.assertEqual(picker.names(), ["AAA", "BBB"])
        picker.set_value("AAA")
        self.assertEqual(picker.value(), "AAA")
        picker.combo.setEditText("BBB")
        picker.combo.lineEdit().editingFinished.emit()
        self.assertEqual(self.committed, ["BBB"])
        picker.combo.setEditText("ZZZ")
        picker.combo.lineEdit().editingFinished.emit()
        self.assertEqual(self.committed, ["BBB"], "un id desconocido no se confirma")
        self.assertTrue(picker.combo.property("invalid"))
        picker.allow_new = True
        picker.combo.lineEdit().editingFinished.emit()
        self.assertEqual(self.committed, ["BBB", "ZZZ"])

    def test_empty_is_no_value(self):
        picker = self.keep(SymbolPicker(_Session({}), "tag"))
        picker.set_value(None)
        self.assertIsNone(picker.value())
        self.assertEqual(picker.combo.lineEdit().placeholderText(), tr("pickers.symbol.placeholder"))


class DateEditTests(PickerCase):
    def test_parse_commit_and_quick_dates(self):
        date = self.keep(DateEdit([ClausewitzDate(1836, 1, 1), ClausewitzDate(1861, 7, 1)]))
        self.assertEqual([b.text() for b in date._buttons], ["1836.1.1", "1861.7.1"])
        date.edit.setText("1850.3.4")
        date.edit.editingFinished.emit()
        self.assertEqual(self.committed, [ClausewitzDate(1850, 3, 4)])
        date.edit.setText("1850.2.29")
        date.edit.editingFinished.emit()
        self.assertEqual(len(self.committed), 1, "el juego no tiene 29 de febrero")
        self.assertIsNone(DateEdit.parse("1850.2.29"))
        date._buttons[1].click()
        self.assertEqual(self.committed[-1], ClausewitzDate(1861, 7, 1))


class ColorFieldTests(PickerCase):
    def test_value_commit_and_similar_warning(self):
        field = self.keep(ColorField({"alander": (100, 20, 20), "corlander": (20, 20, 100)}))
        field.set_value((10, 20, 30))
        self.assertEqual(field.value(), (10, 20, 30))
        self.assertTrue(field.warning.isHidden())
        field.set_from((101, 22, 18))
        self.assertEqual(self.committed, [(101, 22, 18)])
        self.assertFalse(field.warning.isHidden())
        self.assertEqual(field.warning.text(), tr("pickers.color.similar", names="alander"))
        self.assertEqual(similar_colors((20, 25, 95), {"x": (20, 20, 100), "y": (200, 0, 0)}), ["x"])
        field.set_value(None)
        self.assertIsNone(field.value())


class GoodsTests(PickerCase):
    def test_add_edit_remove(self):
        goods = self.keep(GoodsAmountsField(["grain", "fish"]))
        goods.set_value({"fish": 2.0})
        self.assertEqual(goods.value(), {"fish": 2.0})
        goods.good_combo.setCurrentIndex(goods.good_combo.findData("grain"))
        goods.add_button.click()
        self.assertEqual(self.committed[-1], {"fish": 2.0, "grain": 1.0})
        goods.table.item(1, 1).setText("4,5")
        self.assertEqual(self.committed[-1], {"fish": 2.0, "grain": 4.5}, "la coma también vale")
        goods.table.setCurrentCell(0, 1)
        goods.remove_button.click()
        self.assertEqual(self.committed[-1], {"grain": 4.5})
        self.assertEqual(goods.table.horizontalHeaderItem(0).text(), tr("pickers.goods.good"))


class NameListTests(PickerCase):
    def test_split_dedupe_and_cp1252(self):
        names = self.keep(NameListEditor())
        self.assertEqual(NameListEditor.split('Ana "Luis Mar" Pedro\nJuan'), ["Ana", "Luis Mar", "Pedro", "Juan"])
        names.set_value(["Ana", "Luis"])
        names.edit.setPlainText("Ana\nLuis\nAna\nŁukasz")
        self.assertEqual(names.invalid_names(), ["Łukasz"])
        self.assertFalse(names.warning.isHidden())
        names.commit_pending()
        self.assertEqual(self.committed, [], "con un nombre que el juego no muestra, no se confirma")
        names.edit.setPlainText("Ana\nLuis\nAna\nPedro")
        names.remove_duplicates()
        self.assertEqual(self.committed, [["Ana", "Luis", "Pedro"]])
        self.assertEqual(names.count_label.text(), tr("pickers.names.count", count=3))


class SpriteFrameTests(PickerCase):
    def test_frames_bound(self):
        frames = self.keep(SpriteFramePicker(12))
        self.assertEqual(frames.of_label.text(), tr("pickers.sprite.of", count=12))
        frames.edit.setText("5")
        frames.edit.editingFinished.emit()
        self.assertEqual(self.committed, [5])
        frames.edit.setText("13")
        frames.edit.editingFinished.emit()
        self.assertEqual(self.committed, [5], "más allá del último fotograma no se confirma")


class TranslationTests(PickerCase):
    def test_pickers_retranslate(self):
        goods = self.keep(GoodsAmountsField(["fish"]))
        names = NameListEditor()
        self.widgets.append(names)
        set_language("en")
        self.assertEqual(goods.add_button.text(), "Add")
        self.assertEqual(names.dedupe_button.text(), "Remove duplicates")
        set_language("es")
        self.assertEqual(goods.add_button.text(), "Añadir")
        self.assertEqual(names.dedupe_button.text(), "Quitar repetidos")


if __name__ == "__main__":
    unittest.main()
