"""Esquema ``bookmark`` con el arnés (wizard §19.3)."""

import schema_harness
from vic2studio.core.schemas.bookmark import BOOKMARK


class BookmarkContract(schema_harness.SchemaContract):
    schema = BOOKMARK
    corpus = "common/bookmarks.txt"
    allowed = {}
