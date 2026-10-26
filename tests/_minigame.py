"""Minijuego sintético: un juego base y un mod coherentes, todo inventado (wizard §19.1, versión de la iteración 2).

Lo que necesita esta iteración: ``common/cb_types.txt`` (``peace_order`` con un
valor que no es CB y tres CB con ``months``), ``common/countries.txt`` (con
``dynamic_tags``) y sus archivos de país, localización, historias de país y de
provincia (una solo con CR, otra con nombre irregular y un id repetido en dos
carpetas), eventos y decisiones. El mod puede ir vacío o con archivos propios, y
con copias de archivos del juego (``mod_copies``, como hace VSM).

Ningún texto viene de los archivos de Paradox: solo se imita su forma. Las
iteraciones siguientes lo amplían (mapa, unidades, interfaz…).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from _layers import Layers, build_layers

CRLF = "\r\n"


def _crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", CRLF)


CB_TYPES = _crlf("""\
# Casus belli del minijuego (inventados)
peace_order = {
	conquer_land
	free_people
	humble_rival
	annex
}

conquer_land = {
	sprite_index = 1
	months = 12
	is_triggered_only = no
	po_transfer_provinces = yes
	war_name = CONQUER_LAND_WAR
}

free_people = {
	sprite_index = 2
	months = 6
	po_release_puppet = yes
	war_name = FREE_PEOPLE_WAR
}

humble_rival = {
	sprite_index = 3
	months = 3
	po_remove_prestige = yes
	war_name = HUMBLE_RIVAL_WAR
}
""")

COUNTRIES = _crlf("""\
AAA = "countries/Aland.txt"
BBB = "countries/Borland.txt"
CCC = "countries/Corland.txt"

## Dominios del minijuego
dynamic_tags = yes
D01 = "countries/Dominion.txt"
""")


def _country(color: str, party: str) -> str:
    return _crlf(f"""\
color = {{ {color} }}
graphical_culture = Generic

party = {{
	name = "{party}"
	start_date = 1800.1.1
	end_date = 2000.1.1
	ideology = conservative
	economic_policy = interventionism
	trade_policy = protectionism
	religious_policy = moralism
	citizenship_policy = limited_citizenship
	war_policy = pro_military
}}
""")


GAME_FILES: dict[str, str] = {
    "common/cb_types.txt": CB_TYPES,
    "common/countries.txt": COUNTRIES,
    "common/countries/Aland.txt": _country("10 20 30", "AAA_conservative"),
    "common/countries/Borland.txt": _country("40 50 60", "shared_party"),
    "common/countries/Corland.txt": _country("70 80 90", "shared_party"),
    "common/countries/Dominion.txt": _country("100 110 120", "D01_conservative"),
    "history/countries/AAA - Aland.txt": _crlf("capital = 1\nprimary_culture = alander\ngovernment = monarchy\n"),
    "history/countries/BBB - Borland.txt": _crlf("capital = 3\nprimary_culture = borlander\n"),
    "history/provinces/north/1 - Capital.txt": _crlf("owner = AAA\ncontroller = AAA\nadd_core = AAA\n"
                                                    "1861.1.1 = { railroad = 1 }\n"),
    # Solo CR y nombre irregular (dos espacios, sin guion), como H2 y H9.
    "history/provinces/south/2  Llanura.txt": "owner = BBB\rcontroller = BBB\radd_core = BBB\r",
    # El mismo id en dos carpetas (H9).
    "history/provinces/east/3 - Costa.txt": _crlf("owner = CCC\ntrade_goods = fish\n"),
    "history/provinces/west/3 - Costa.txt": _crlf("owner = CCC\ntrade_goods = grain\n"),
    "events/minigame_events.txt": _crlf("""\
country_event = {
	id = 1001
	title = "EVT_1001_NAME"
	desc = "EVT_1001_DESC"
	option = { name = "EVT_1001_A" }
}

province_event = {
	id = 1002
	title = "EVT_1002_NAME"
	option = { name = "EVT_1002_A" }
}
"""),
    "decisions/minigame_decisions.txt": _crlf("""\
political_decisions = {
	unite_lands = {
		potential = { tag = AAA }
		allow = { prestige = 10 }
		effect = { prestige = 5 }
	}
}
"""),
    "localisation/minigame.csv": _crlf(
        "conquer_land;Conquer land;Conquérir;Erobern;;Conquistar;;;;;;;;x\n"
        "free_people;Free the people;Libérer;Befreien;;Liberar;;;;;;;;x\n"
        "humble_rival;Humble a rival;Humilier;Demütigen;;Humillar;;;;;;;;x\n"),
}

MOD_FILES: dict[str, str] = {
    "decisions/tst_decisions.txt": _crlf("political_decisions = {\n\ttst_reform = {\n\t\teffect = { prestige = 1 }\n"
                                         "\t}\n}\n"),
    "localisation/00_TST_decisions.csv": _crlf("tst_reform;Reform;Réforme;Reform;;Reforma;;;;;;;;x\n"),
}

# Los tres CB y sus meses en el juego base.
CB_MONTHS = {"conquer_land": 12, "free_people": 6, "humble_rival": 3}


@dataclass
class MiniGame:
    layers: Layers

    @property
    def game_root(self) -> Path:
        assert self.layers.game_root is not None
        return self.layers.game_root

    @property
    def mod_root(self) -> Path:
        return self.layers.mod_root

    @property
    def descriptor(self) -> Path | None:
        return self.layers.descriptor

    def game(self, rel: str) -> Path:
        return self.layers.game(rel)

    def mod(self, rel: str) -> Path:
        return self.layers.mod(rel)

    def tree(self, root: Path | None = None) -> dict[str, tuple[int, int, bytes]]:
        return self.layers.tree(root)

    def game_tree(self) -> dict[str, tuple[int, int, bytes]]:
        """Árbol del juego base sin ``mod/`` (los hashes del juego no deben cambiar nunca)."""
        return {rel: info for rel, info in self.layers.tree(self.game_root).items() if not rel.startswith("mod/")}

    def cleanup(self) -> None:
        self.layers.cleanup()

    def __enter__(self) -> MiniGame:
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()


def build_minigame(root: Path | None = None, *, mod: bool = True, mod_name: str = "TestMod",
                   mod_copies: Iterable[str] = (), mod_files: Mapping[str, bytes | str] | None = None,
                   game_files: Mapping[str, bytes | str] | None = None) -> MiniGame:
    """Juego y mod en ``root`` (una carpeta temporal propia si es None; ``cleanup`` la borra).

    ``mod=False``: mod vacío. ``mod_copies``: archivos del juego que el mod trae
    copiados tal cual (un mod copia completa, como VSM). ``mod_files`` y
    ``game_files`` añaden o sustituyen archivos.
    """
    game = dict(GAME_FILES)
    game.update(game_files or {})
    files: dict[str, bytes | str] = dict(MOD_FILES) if mod else {}
    for rel in mod_copies:
        files[rel] = game[rel]
    files.update(mod_files or {})
    return MiniGame(build_layers(game=game, mod=files, mod_name=mod_name, base=root))
