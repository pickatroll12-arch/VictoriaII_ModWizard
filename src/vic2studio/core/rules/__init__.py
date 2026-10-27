"""Reglas del juego (wizard §9): datos de la vista efectiva (``GameRules``) e invariantes de identificadores,
nombres y colores. Python puro."""

from .game import DEFAULT_END, DEFAULT_START, GameRules
from .ids import DYNAMIC_TAG_RE, EVENT_ID_RANGE, RESERVED_TAGS, SCRIPT_WORDS, TAG_RE, tag_problem

__all__ = ["DEFAULT_END", "DEFAULT_START", "DYNAMIC_TAG_RE", "EVENT_ID_RANGE", "GameRules", "RESERVED_TAGS",
           "SCRIPT_WORDS", "TAG_RE", "tag_problem"]
