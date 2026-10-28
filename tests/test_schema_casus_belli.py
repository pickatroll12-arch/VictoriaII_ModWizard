"""Esquema ``casus_belli`` con el arnés (wizard §19.3)."""

import schema_harness
from vic2studio.core.schemas.casus_belli import CASUS_BELLI


class CasusBelliContract(schema_harness.SchemaContract):
    schema = CASUS_BELLI
    corpus = "common/cb_types.txt"
    allowed = {}
