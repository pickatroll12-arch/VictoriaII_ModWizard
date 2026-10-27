"""Explicador de conflicto (wizard §11.1): por qué el juego verá lo que verá.

Reconstruye, con ``VfsSnapshot.stack``, el índice y ``LocalisationDB.definitions``,
qué capas definen lo mismo y en qué orden las carga el juego (archivo del mod que
sustituye al de vanilla, clave de localización que gana por orden de archivos,
``replace_path`` que oculta una carpeta, TAG detrás de ``dynamic_tags``…). Cada paso
lleva la línea real de su capa y su veredicto; la explicación termina en una frase
sobre el efecto en el juego y en los arreglos disponibles. Los heredados también
se explican. Hay una explicación para cada código del catálogo; uno sin
explicador propio da una genérica con la pila de capas del archivo.
"""

from __future__ import annotations

from .context import ValidationContext
from .model import Explanation, Problem


def explain(problem: Problem, ctx: ValidationContext) -> Explanation:
    raise NotImplementedError
