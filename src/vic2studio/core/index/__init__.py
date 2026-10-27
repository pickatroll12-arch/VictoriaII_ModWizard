"""Índice de símbolos (wizard §7): qué existe en la vista efectiva y dónde se usa."""

from .builder import build_index, extract_bytes, extract_entry
from .cache import FactsCache
from .index import SymbolIndex
from .model import (
    EXTRACTORS,
    INDEX_FORMAT,
    ExtractorSpec,
    FileFacts,
    Symbol,
    SymbolRef,
    discover_extractors,
    extractor,
    extractors_for,
    fold,
)

__all__ = [
    "EXTRACTORS", "INDEX_FORMAT", "ExtractorSpec", "FactsCache", "FileFacts", "Symbol", "SymbolIndex", "SymbolRef",
    "build_index", "discover_extractors", "extract_bytes", "extract_entry", "extractor", "extractors_for", "fold",
]
