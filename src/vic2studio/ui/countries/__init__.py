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
