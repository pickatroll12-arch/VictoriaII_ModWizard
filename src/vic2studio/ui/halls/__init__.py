"""Salas de la ventana principal (wizard §13.1): un paquete por sala, descubiertos por ``registry``."""

from .registry import HALL_KEYS, HallSpec, SectionSpec, discover_halls

__all__ = ["HALL_KEYS", "HallSpec", "SectionSpec", "discover_halls"]
