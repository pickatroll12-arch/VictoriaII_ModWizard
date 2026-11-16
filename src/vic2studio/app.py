"""Punto de entrada de la aplicación de escritorio."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORG_NAME, __version__

# Con VIC2STUDIO_SMOKE_TEST=1 la aplicación abre la ventana, comprueba sus textos y se cierra (código 0 si todo está,
# 3 si falta algo): lo usa el empaquetado para probar el ejecutable congelado (packaging/, .github/workflows).
SMOKE_ENV = "VIC2STUDIO_SMOKE_TEST"
# Una clave de cada catálogo de textos, de la interfaz y del núcleo. El .spec de PyInstaller copia los datos con
# patrones propios: si se le escapa un archivo, el programa enseña sus claves crudas. tests/test_packaging.py exige
# una clave por archivo de textos del repositorio.
SMOKE_KEYS = (
    "app.emblem_tooltip",              # i18n/<idioma>.json
    "conflict.cancel",                 # i18n/<idioma>/project.json
    "hall.events.plate",               # i18n/<idioma>/shell.json
    "checks.cancel",                   # i18n/<idioma>/validation.json
    "texts.add.area",                  # i18n/<idioma>/localisation.json
    "kind.bookmark",                   # i18n/<idioma>/palette.json
    "forms.undo_edit",                 # i18n/<idioma>/forms.json
    "entity.tab.form",                 # i18n/<idioma>/entity.json
    "pickers.goods.add",               # i18n/<idioma>/pickers.json
    "map.hover",                       # i18n/<idioma>/map.json
    "countries.new",                   # i18n/<idioma>/countries.json
    "war.new.button",                  # i18n/<idioma>/war.json
    "project.save_outside_mod",        # core/project/texts
    "issue.unclosed_block",            # core/validate/texts
    "issue.definition_bad_row",        # core/map/texts
    "issue.unknown_field",             # core/schemas/texts/schema
    "schema.government.section.elections",   # core/schemas/texts/government
    "schema.unit.field.attack",        # core/schemas/texts/unit
    "schema.casus_belli.field.months",       # core/schemas/texts/casus_belli
    "schema.bookmark.field.date",      # core/schemas/texts/bookmark
    "schema.culture.field.color",      # core/schemas/texts/culture
    "schema.event_modifier.field.icon",      # core/schemas/texts/event_modifier
    "schema.technology.field.year",    # core/schemas/texts/readonly
    "schema.province_history.field.owner",   # core/schemas/texts/province_history
    "schema.pops.title",               # core/schemas/texts/pops
    "schema.region.title",             # core/schemas/texts/region
    "schema.region_sea.title",         # core/schemas/texts/region_sea
    "schema.continent.field.provinces",      # core/schemas/texts/continent
    "schema.climate.title",            # core/schemas/texts/climate
    "schema.terrain.field.is_water",   # core/schemas/texts/terrain
    "schema.default_map.field.sea_starts",   # core/schemas/texts/default_map
    "schema.adjacency.field.through",  # core/schemas/texts/adjacency
    "undo.province_set",               # core/domain/texts
    "schema.country.title",            # core/schemas/texts/country
    "schema.country_colors.title",     # core/schemas/texts/country_colors
    "schema.country_history.title",    # core/schemas/texts/country_history
    "schema.country_registry.title",   # core/schemas/texts/country_registry
    "schema.diplomacy.title",          # core/schemas/texts/diplomacy
    "schema.oob.title",                # core/schemas/texts/oob
    "schema.war.title",                # core/schemas/texts/war
)


def create_application(argv: list[str] | None = None) -> QApplication:
    """Crea (o reutiliza) la ``QApplication`` con nombre, versión, tema e icono."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0] if sys.argv else APP_NAME, *(argv or [])])
    app.setOrganizationName(ORG_NAME)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)

    from .ui.main_window import app_icon
    from .ui.theme import apply_theme

    apply_theme(app)
    app.setWindowIcon(app_icon())
    return app


def refuse_broken_binding(python: str, pyside: str) -> int:
    """Explica que esta combinación de Python y PySide6 aborta, y devuelve el código de salida."""
    from PySide6.QtWidgets import QMessageBox

    from .compat import broken_binding_message
    from .i18n import tr

    print(broken_binding_message(python, pyside), file=sys.stderr)
    QMessageBox.critical(
        None,
        tr("compat.pyside_title"),
        tr("compat.pyside_text", python=python, pyside=pyside),
    )
    return 1


def smoke_problems() -> list[str]:
    """Lo que falta para la comprobación de humo: ``idioma:clave`` de cada clave de ``SMOKE_KEYS`` sin texto (vacía
    si el programa tiene todos sus textos)."""
    from .i18n import LANGUAGES, load_catalog

    missing = []
    for code, _ in LANGUAGES:
        catalog = load_catalog(code)
        missing.extend(f"{code}:{key}" for key in SMOKE_KEYS if key not in catalog)
    return missing


def _smoke_test(app: QApplication, window) -> None:
    """Dice por la salida estándar si la ventana se construyó con todos sus textos y cierra la aplicación."""
    missing = smoke_problems()
    print(f"{APP_NAME} {__version__}: " + ("textos completos" if not missing else "faltan " + ", ".join(missing)),
          flush=True)
    window.close()
    app.exit(0 if not missing else 3)


def main(argv: list[str] | None = None) -> int:
    """Arranca la interfaz; ``argv`` son los argumentos sin el nombre del programa."""
    from .compat import broken_qt_binding

    app = create_application(sys.argv[1:] if argv is None else argv)
    # Antes de la ventana y de cualquier tarea: con esa combinación el proceso aborta al rato.
    broken = broken_qt_binding()
    if broken is not None:
        return refuse_broken_binding(*broken)

    from .ui.main_window import MainWindow
    from .ui.tasks import cancel_all, wait_for_tasks

    window = MainWindow()
    window.show()
    if os.environ.get(SMOKE_ENV):
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: _smoke_test(app, window))
    code = app.exec()
    # Ningún hilo debe seguir ejecutando Python mientras se cierra el intérprete; canceladas, las tareas paran pronto.
    cancel_all()
    wait_for_tasks()
    return code
