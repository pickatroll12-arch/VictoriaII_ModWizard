"""Países (wizard §14.2, iteración 6): asistente «Nuevo país» (``wizard``), ficha nacional (``sheet``), taller de
banderas (``flag_studio``), cámara alta (``upper_house``) y editor de órdenes de batalla (``oob_editor``).

Todo pasa por las fachadas del núcleo (``core.domain.country``, ``core.domain.nation``, ``core.domain.war``) con
el ``DomainContext`` de la sesión (``domain_context``), y cada gesto es una transacción con ``Session.edit``.
"""

from __future__ import annotations


def domain_context(session):
    """``core.domain.country.DomainContext`` del proyecto abierto en ``session`` (None sin proyecto)."""
    from ...core.domain.country import DomainContext

    project = session.project
    if project is None:
        return None
    rules = session.map.rules() if hasattr(session, "map") else None
    return DomainContext(project.ws, project.vfs, session.index, session.locsync, session.entities, rules,
                         getattr(project, "settings", None))


def countries_facade(session):
    """``core.domain.nation.Countries`` del proyecto abierto (None sin proyecto)."""
    from ...core.domain.nation import Countries

    entities = session.entities
    if entities is None:
        return None
    return Countries(entities, session.map.rules() if hasattr(session, "map") else None)


def loc_text(session, key: str) -> str | None:
    """El texto de ``key`` en la localización del proyecto, en el idioma de la interfaz si la localización lo
    tiene y si no en inglés (None si no hay)."""
    from ...core.csvloc.model import InvalidFieldError
    from ...i18n import translator

    loc = getattr(session, "locsync", None)
    if loc is None or session.project is None:
        return None
    for lang in (translator().language(), "en"):
        try:
            return loc.text(key, lang)
        except InvalidFieldError:      # idioma de la interfaz sin columna en los CSV (el pseudoidioma de pruebas)
            continue
    return None
