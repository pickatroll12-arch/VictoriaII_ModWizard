"""Registro de esquemas por descubrimiento (wizard §10, §20: sin listas centrales).

``registry`` descubre los módulos de ``core/schemas`` con ``pkgutil``: cada
módulo exporta ``SCHEMAS = (…)`` y, opcionalmente, ``RECIPES = (…)``. Dos
esquemas con el mismo ``kind`` son un error de programación y fallan al
importarlos (``ValueError``). Añadir una entidad no toca ningún archivo
compartido.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable

from .entity import EntitySchema


class SchemaRegistry:
    """Registro de esquemas y recetas, con descubrimiento perezoso por ``pkgutil``."""

    def __init__(self) -> None:
        self._schemas: dict[str, EntitySchema] = {}
        self._recipes: dict[str, object] = {}
        self._discovered = False

    def register(self, schemas: Iterable[EntitySchema], *, recipes: Iterable = ()) -> None:
        """Añade esquemas (y recetas) al registro; ``ValueError`` si un ``kind`` ya existe."""
        for schema in schemas:
            if schema.kind in self._schemas:
                raise ValueError(f"dos esquemas con el mismo kind: {schema.kind}")
            self._schemas[schema.kind] = schema
        for recipe in recipes:
            if recipe.key in self._recipes:
                raise ValueError(f"dos recetas con la misma clave: {recipe.key}")
            self._recipes[recipe.key] = recipe

    def discover(self) -> None:
        """Importa ``core/schemas/*`` una sola vez y registra sus ``SCHEMAS`` y ``RECIPES``."""
        if self._discovered:
            return
        self._discovered = True
        try:
            from vic2studio.core import schemas as package
        except ImportError:
            return
        for info in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package.__name__}.{info.name}")
            self.register(getattr(module, "SCHEMAS", ()), recipes=getattr(module, "RECIPES", ()))

    def get(self, kind: str) -> EntitySchema:
        """El esquema de ``kind``; ``KeyError`` si no existe (o no se ha descubierto)."""
        self.discover()
        return self._schemas[kind]

    def all_schemas(self) -> tuple[EntitySchema, ...]:
        """Todos los esquemas, por descubrimiento (orden de importación de ``core/schemas``)."""
        self.discover()
        return tuple(self._schemas.values())

    def recipes(self) -> tuple[object, ...]:
        """Todas las recetas descubiertas."""
        self.discover()
        return tuple(self._recipes.values())


registry = SchemaRegistry()
