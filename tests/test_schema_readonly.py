"""Catálogos de solo lectura con el arnés (wizard §19.3, §22): se listan, se leen y se documentan."""

import schema_harness
from vic2studio.core.schemas.readonly import BUILDING, GOODS, IDEOLOGY, INVENTION, ISSUE_GROUP, TECHNOLOGY


class TechnologyContract(schema_harness.SchemaContract):
    schema = TECHNOLOGY
    corpus = "technologies"
    allowed = {}


class InventionContract(schema_harness.SchemaContract):
    schema = INVENTION
    corpus = "inventions"
    allowed = {}


class IdeologyContract(schema_harness.SchemaContract):
    schema = IDEOLOGY
    corpus = "common/ideologies.txt"
    allowed = {}


class IssueGroupContract(schema_harness.SchemaContract):
    schema = ISSUE_GROUP
    corpus = "common/issues.txt"
    allowed = {}


class GoodsContract(schema_harness.SchemaContract):
    schema = GOODS
    corpus = "common/goods.txt"
    allowed = {}


class BuildingContract(schema_harness.SchemaContract):
    schema = BUILDING
    corpus = "common/buildings.txt"
    allowed = {}
