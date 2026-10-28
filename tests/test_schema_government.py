"""Contrato del esquema de gobiernos (arnés de §19.3)."""
import schema_harness
from vic2studio.core.schemas.government import GOVERNMENT


class GovernmentContract(schema_harness.SchemaContract):
    schema = GOVERNMENT
    corpus = "common/governments.txt"
    allowed = {}
