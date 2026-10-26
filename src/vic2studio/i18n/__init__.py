"""Traducción de la interfaz en tiempo real (español / inglés).

Los textos viven en catálogos JSON planos (``es.json``, ``en.json``) con claves
del tipo ``"nav.project"``. Toda cadena visible pasa por ``tr``; los widgets se
re-traducen al recibir ``Translator.languageChanged`` sin reiniciar la app.

Las claves que se guardan para traducir más tarde se marcan con ``N_`` para
que la búsqueda estática de las pruebas las encuentre.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QLocale, QObject, Signal

from ..settings import app_settings

log = logging.getLogger(__name__)

LANGUAGES = (("es", "Español"), ("en", "English"))
SETTINGS_KEY = "ui/language"
_CATALOG_DIR = Path(__file__).resolve().parent
_LOCALES = {"es": QLocale.Language.Spanish, "en": QLocale.Language.English}


def N_(key: str) -> str:
    """Marca una clave de traducción sin traducirla todavía."""
    return key


def catalog_path(code: str) -> Path:
    return _CATALOG_DIR / f"{code}.json"


def load_catalog(code: str) -> dict[str, str]:
    data = json.loads(catalog_path(code).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError(f"catálogo {code!r} mal formado: se espera un objeto plano de cadenas")
    return data


def system_language(locale_name: str | None = None) -> str:
    """``es*`` -> ``"es"``; cualquier otro idioma del sistema -> ``"en"``."""
    name = QLocale.system().name() if locale_name is None else locale_name
    return "es" if name.lower().startswith("es") else "en"


class Translator(QObject):
    languageChanged = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._catalogs = {code: load_catalog(code) for code, _ in LANGUAGES}
        self._warned: set[str] = set()
        self._missing: set[str] = set()
        saved = app_settings().value(SETTINGS_KEY, "", str)
        self._language = saved if saved in self._official() else system_language()

    @staticmethod
    def _official() -> tuple[str, ...]:
        return tuple(code for code, _ in LANGUAGES)

    def language(self) -> str:
        return self._language

    def available_languages(self) -> list[tuple[str, str]]:
        return list(LANGUAGES)

    def locale(self) -> QLocale:
        """Locale de formato (números, fechas) acorde al idioma de la interfaz."""
        return QLocale(_LOCALES.get(self._language, QLocale.Language.English))

    def catalog(self, code: str | None = None) -> dict[str, str]:
        return dict(self._catalogs[code or self._language])

    def register_catalog(self, code: str, mapping: dict[str, str]) -> None:
        """Añade un catálogo extra (pseudo-localización en pruebas); no se persiste."""
        self._catalogs[code] = dict(mapping)

    def missing_keys(self) -> frozenset[str]:
        return frozenset(self._missing)

    def set_language(self, code: str) -> None:
        if code not in self._catalogs:
            raise ValueError(f"idioma no disponible: {code!r}")
        if code in self._official():
            app_settings().setValue(SETTINGS_KEY, code)
        if code == self._language:
            return
        self._language = code
        self.languageChanged.emit(code)

    def tr(self, key: str, /, **fmt) -> str:
        text = self._catalogs[self._language].get(key)
        if text is None:
            self._missing.add(key)
            self._warn_once(key, "clave de traducción desconocida: %r", key)
            return key
        if not fmt:
            return text
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            self._warn_once(f"{self._language}:{key}", "formato inválido en %r (%s)", key, self._language)
            return text

    def _warn_once(self, token: str, message: str, *args) -> None:
        if token not in self._warned:
            self._warned.add(token)
            log.warning(message, *args)


_translator: Translator | None = None


def translator() -> Translator:
    global _translator
    if _translator is None:
        _translator = Translator()
    return _translator


def tr(key: str, /, **fmt) -> str:
    return translator().tr(key, **fmt)


def set_language(code: str) -> None:
    translator().set_language(code)


def language() -> str:
    return translator().language()


def available_languages() -> list[tuple[str, str]]:
    return translator().available_languages()
