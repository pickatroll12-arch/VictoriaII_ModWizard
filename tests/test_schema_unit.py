"""Contrato del esquema de unidades (arnés de §19.3)."""
import schema_harness
from vic2studio.core.schemas.unit import UNIT


class UnitContract(schema_harness.SchemaContract):
    schema = UNIT
    corpus = "units/infantry.txt"
    allowed = {}
