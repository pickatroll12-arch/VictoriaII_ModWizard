"""Contrato del esquema de gobiernos (arnés de §19.3)."""
from schema_harness import SchemaContract
from vic2studio.core.schemas.government import GOVERNMENT


class GovernmentContract(SchemaContract):
    schema = GOVERNMENT
    corpus = "common/governments.txt"
    allowed = {}
