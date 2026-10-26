"""Cancelación cooperativa de los trabajos largos del núcleo (sin Qt).

Las funciones que pueden tardar (``parse``/``parse_file``, ``parse_csv``/
``read_csv_file``, ``check_mod``) aceptan ``cancelled``: una función sin
argumentos que devuelve True cuando hay que parar. La consultan cada poco
trabajo y, si devuelve True, lanzan ``Cancelled``. La interfaz pasa
``TaskContext.cancelled``; ``ui.tasks`` trata ``Cancelled`` como una
cancelación normal y no entrega nada.
"""

from __future__ import annotations

from typing import Callable, Optional

CancelCheck = Optional[Callable[[], bool]]


class Cancelled(Exception):
    """El trabajo se detuvo porque ``cancelled()`` devolvió True."""


def raise_if_cancelled(cancelled: CancelCheck) -> None:
    if cancelled is not None and cancelled():
        raise Cancelled()
