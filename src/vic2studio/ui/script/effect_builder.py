"""Constructor de efectos: el mismo modelo que ``TriggerBuilder`` con ámbitos de efecto (wizard §14.7).

Dentro de un efecto, ``limit = { … }`` es un bloque de condiciones (``ScriptKeyDef.body``): su fila se pinta
como un grupo de condiciones y su buscador ofrece condiciones, no efectos (457 ``limit`` en los efectos de
vanilla). Los iteradores (``any_pop``, ``random_state``, ``any_owned``…) son corchetes de ámbito.
"""

from __future__ import annotations

from ...core.script.scopes import ScriptKind
from ...i18n import N_
from .trigger_builder import TriggerBuilder


class EffectBuilder(TriggerBuilder):
    """Constructor de un bloque de efectos (``immediate``, el resto de un ``option``, ``effect``)."""

    kind = ScriptKind.EFFECT
    ADD_KEY = N_("script_ui.add_effect")
