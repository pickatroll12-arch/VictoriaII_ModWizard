"""Contrato del esquema de unidades (arnés de §19.3)."""
from schema_harness import SchemaContract
from vic2studio.core.schemas.unit import UNIT


class UnitContract(SchemaContract):
    schema = UNIT
    corpus = "units/infantry.txt"
    allowed = {}
