"""Esquema ``culture`` con el arnés (wizard §19.3)."""

import schema_harness
from vic2studio.core.schemas.culture import CULTURE, CULTURE_GROUP


class CultureContract(schema_harness.SchemaContract):
    schema = CULTURE
    corpus = "common/cultures.txt"
    allowed = {}


class CultureGroupContract(schema_harness.SchemaContract):
    schema = CULTURE_GROUP
    corpus = "common/cultures.txt"
    allowed = {}
