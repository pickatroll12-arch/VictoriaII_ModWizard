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


# --- ampliación de la iteración 3: mapa, reglas del juego, cultura, técnica, interfaz -------------------
# Todo inventado; los archivos de arriba no cambian (las pruebas de la iteración 2 y las de la interfaz los usan).

# Provincias: 8 de tierra (1–8) y 4 de mar (9–12). Colores únicos, ni negro ni blanco.
LAND = (1, 2, 3, 4, 5, 6, 7, 8)
SEA = (9, 10, 11, 12)
PROVINCE_COLORS = {
    1: (200, 10, 10), 2: (10, 200, 10), 3: (10, 10, 200), 4: (200, 200, 10), 5: (200, 100, 50),
    6: (10, 200, 200), 7: (120, 60, 30), 8: (60, 120, 30), 9: (20, 40, 160), 10: (30, 50, 170),
    11: (40, 60, 180), 12: (50, 70, 190),
}
PROVINCE_NAMES = {1: "Capital", 2: "Llanura", 3: "Costa", 4: "Colina", 5: "Quinta", 6: "Bosque", 7: "Vado",
                  8: "Cumbre", 9: "Mar Norte", 10: "Mar Este", 11: "Mar Sur", 12: "Mar Oeste"}
# Un color del BMP sin fila en definition.csv (como los 27 de vanilla, H4): sale heredado.
UNMAPPED_COLOR = (7, 7, 7)
MAP_SIZE = (64, 32)


def _definition_csv() -> str:
    rows = ["province;red;green;blue;x;x"]
    for province, (r, g, b) in PROVINCE_COLORS.items():
        # La 5 lleva un «50.» al estilo de la fila 1826 de vanilla (H4): se lee como 50.
        blue = f"{b}." if province == 5 else str(b)
        rows.append(f"{province};{r};{g};{blue};{PROVINCE_NAMES[province]};x")
    rows.append(";99;98;97;x;x")      # fila sin id al final (H4)
    return _crlf("\n".join(rows) + "\n")


def province_at(x: int, y: int) -> int | None:
    """Provincia del píxel (``y`` en coordenadas del juego, fila 0 = arriba en la imagen); None = sin id.

    Asimétrico: la tierra son 4×2 bloques de 10×16 a la izquierda, el mar cuatro franjas de 24×8 a la derecha
    y la esquina (0, 0)–(1, 1) tiene el color sin id."""
    if x < 2 and y < 2:
        return None
    if x < 40:
        return 1 + x // 10 + (4 if y >= 16 else 0)
    return 9 + y // 8


def provinces_bmp() -> bytes:
    """BMP de 24 bits, 64×32, de abajo arriba como los del juego (sin numpy ni Pillow)."""
    width, height = MAP_SIZE
    stride = (width * 3 + 3) & ~3
    rows = []
    for y in range(height - 1, -1, -1):          # la primera fila del archivo es la de abajo
        row = bytearray()
        for x in range(width):
            province = province_at(x, y)
            r, g, b = UNMAPPED_COLOR if province is None else PROVINCE_COLORS[province]
            row += bytes((b, g, r))
        row += b"\0" * (stride - len(row))
        rows.append(bytes(row))
    pixels = b"".join(rows)
    header = (b"BM" + (54 + len(pixels)).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little")
              + (40).to_bytes(4, "little") + width.to_bytes(4, "little") + height.to_bytes(4, "little")
              + (1).to_bytes(2, "little") + (24).to_bytes(2, "little") + b"\0" * 4 + len(pixels).to_bytes(4, "little")
              + (2835).to_bytes(4, "little") * 2 + b"\0" * 8)
    return header + pixels


def _loc(rows: list[tuple[str, str, str]]) -> str:
    """Filas ``clave;inglés;francés;alemán;;español;…;x`` (13 idiomas y el marcador, como vanilla)."""
    lines = [f"{key};{en};{en};{en};;{es}" + ";" * 9 + "x" for key, en, es in rows]
    return _crlf("\n".join(lines) + "\n")


NAMES_ROWS = [
    ("AAA", "Aland", "Alandia"), ("AAA_ADJ", "Alandish", "alandés"), ("BBB", "Borland", "Borlandia"),
    ("BBB_ADJ", "Borlandish", "borlandés"), ("CCC", "Corland", "Corlandia"), ("CCC_ADJ", "Corlandish", "corlandés"),
    ("D01", "Dominion", "Dominio"), ("D01_ADJ", "Dominion", "del dominio"),
    *[(f"PROV{p}", n, n) for p, n in PROVINCE_NAMES.items() if p != 12],     # PROV12 falta a propósito
    ("EVT_1001_NAME", "First event", "Primer evento"), ("EVT_1001_DESC", "It happens", "Ocurre"),
    ("EVT_1001_A", "Fine", "Bien"), ("EVT_1002_NAME", "Second event", "Segundo evento"), ("EVT_1002_A", "Ok", "Vale"),
    ("EVT_1003_NAME", "Third event", "Tercer evento"), ("EVT_1003_A", "Go", "Adelante"),
    ("unite_lands_title", "Unite the lands", "Unir las tierras"), ("unite_lands_desc", "Unite them", "Unirlas"),
    ("alander", "Alander", "alandés"), ("north_folk", "Northern", "norteño"),
]

RULES_FILES: dict[str, str | bytes] = {
    "map/definition.csv": _definition_csv(),
    "map/provinces.bmp": provinces_bmp(),
    "map/default.map": _crlf("max_provinces = 13\nsea_starts = {\n\t9 10 11 12\n}\n"
                             'definitions = "definition.csv"\nprovinces = "provinces.bmp"\nregion = "region.txt"\n'
                             'region_sea = "region_sea.txt"\ncontinent = "continent.txt"\n'
                             'terrain_definition = "terrain.txt"\n'),
    "map/region.txt": _crlf("AAA_1 = { 1 2 3 }\nBBB_4 = { 4 5 6 }\nCCC_7 = { 7 8 }\n"),
    # Solo CR, como map/region_sea.txt de vanilla (H2).
    "map/region_sea.txt": "north_sea_region = { 9 10 }\rsouth_sea_region = { 11 12 }\r",
    "map/continent.txt": _crlf("west_land = {\n\tprovinces = { 1 2 3 4 }\n\tassimilation_rate = 0.5\n}\n"
                               "east_land = {\n\tprovinces = { 5 6 7 8 }\n}\n"),
    # Claves emparejadas (H7): la 1.ª con los modificadores y la 2.ª con las provincias.
    "map/climate.txt": _crlf("mild_climate = {\n\tfarm_rgo_size = 0.0\n}\nmild_climate = { 1 2 3 4 }\n"
                             "harsh_climate = {\n\tmax_attrition = 5\n}\nharsh_climate = { 5 6 7 8 }\n"),
    "map/terrain.txt": _crlf("terrain = 8\ncategories = {\n\tocean = {\n\t\tis_water = yes\n\t\tcolor = { 0 0 255 }\n\t}\n"
                             "\tplains = {\n\t\tcolor = { 0 255 0 }\n\t}\n\thills = {\n\t\tcolor = { 120 120 0 }\n\t}\n}\n"),
    "common/defines.lua": _crlf("defines = {\n\nstart_date = '1836.1.1',\nend_date = '1935.12.31',\n\ncountry = {\n"
                                "\tYEARS_OF_PEACE = 20, -- años sin guerra\n\tBASE_TAX = 0.25,\n},\n\n}\n"),
    "common/bookmarks.txt": _crlf('bookmark = {\n\tname = "MG_START"\n\tdesc = "MG_START_DESC"\n\tdate = 1836.1.1\n}\n'
                                  'bookmark = {\n\tname = "MG_LATE"\n\tdesc = "MG_LATE_DESC"\n\tdate = 1861.1.1\n}\n'),
    "common/cultures.txt": _crlf("north_folk = {\n\tleader = european\n\tunit = NorthGC\n\talander = {\n"
                                 "\t\tcolor = { 100 20 20 }\n\t}\n\tborlander = {\n\t\tcolor = { 20 100 20 }\n\t}\n}\n"
                                 "south_folk = {\n\tleader = european\n\tcorlander = {\n\t\tcolor = { 20 20 100 }\n\t}\n"
                                 "\tdominer = {\n\t\tcolor = { 90 90 90 }\n\t\tprimary = D01\n\t}\n}\n"),
    "common/religion.txt": _crlf("faiths = {\n\tsunfaith = {\n\t\ticon = 1\n\t\tcolor = { 0.8 0.8 0 }\n\t}\n"
                                 "\tmoonfaith = {\n\t\ticon = 2\n\t\tcolor = { 0 0 0.7 }\n\t}\n}\n"),
    # «council» admite elecciones sin «duration» (sale heredado) y falta en una tabla de rebeldes.
    "common/governments.txt": _crlf("monarchy = {\n\tconservative = yes\n\tliberal = yes\n\telection = no\n"
                                    "\tappoint_ruling_party = yes\n\tflagType = monarchy\n}\n"
                                    "republic = {\n\tliberal = yes\n\tconservative = yes\n\tsocialist = yes\n"
                                    "\telection = yes\n\tduration = 48\n\tappoint_ruling_party = no\n}\n"
                                    "council = {\n\tsocialist = yes\n\telection = yes\n\tappoint_ruling_party = no\n"
                                    "\tflagType = communist\n}\n"),
    "common/ideologies.txt": _crlf("right_group = {\n\tconservative = {\n\t\tcolor = { 0 0 200 }\n\t}\n}\n"
                                   "centre_group = {\n\tliberal = {\n\t\tcolor = { 200 200 0 }\n\t}\n}\n"
                                   "left_group = {\n\tsocialist = {\n\t\tcolor = { 200 0 0 }\n\t}\n}\n"),
    "common/issues.txt": _crlf("party_issues = {\n"
                               "\teconomic_policy = {\n\t\tinterventionism = { }\n\t\tlaissez_faire = { }\n\t}\n"
                               "\ttrade_policy = {\n\t\tprotectionism = { }\n\t\tfree_trade = { }\n\t}\n"
                               "\treligious_policy = {\n\t\tmoralism = { }\n\t\tpluralism = { }\n\t}\n"
                               "\tcitizenship_policy = {\n\t\tlimited_citizenship = { }\n\t\tfull_citizenship = { }\n\t}\n"
                               "\twar_policy = {\n\t\tpro_military = { }\n\t\tanti_military = { }\n\t}\n}\n"
                               "political_reforms = {\n\tslavery = {\n\t\tyes_slavery = { }\n\t\tno_slavery = { }\n"
                               "\t\tnext_step_only = yes\n\t}\n}\n"
                               "social_reforms = {\n\tsafety = {\n\t\tno_safety = { }\n\t\tgood_safety = { }\n\t}\n}\n"),
    "common/nationalvalues.txt": _crlf("nv_order = {\n\tmobilisation_size = 0.04\n}\n"
                                       "nv_liberty = {\n\tmobilisation_size = 0.02\n}\n"),
    "common/technology.txt": _crlf("folders = {\n\tarmy_tech = {\n\t\tarmy_doctrine\n\t\tlight_arms\n\t}\n}\n"
                                   "schools = {\n\ttraditional_academic = {\n\t\tarmy_tech_research_bonus = 0\n\t}\n}\n"),
    "technologies/army_tech.txt": _crlf("musket_drill = {\n\tarea = army_doctrine\n\tyear = 1836\n"
                                        "\tactivate_unit = infantry\n}\n"
                                        "rifled_drill = {\n\tarea = light_arms\n\tyear = 1850\n"
                                        "\tactivate_building = fort\n}\n"),
    "inventions/army_inventions.txt": _crlf("field_kitchens = {\n\tlimit = { musket_drill = 1 }\n"
                                            "\teffect = { activate_unit = frigate }\n}\n"),
    "common/goods.txt": _crlf("raw_goods = {\n\tfish = {\n\t\tcost = 1.5\n\t\tcolor = { 10 10 200 }\n\t}\n"
                              "\tgrain = {\n\t\tcost = 2.0\n\t\tcolor = { 200 200 10 }\n\t}\n}\n"),
    "common/buildings.txt": _crlf("fort = {\n\ttype = fort\n\tmax_level = 6\n}\n"),
    "common/graphicalculturetype.txt": _crlf("NorthGC\nGeneric\n"),
    # La tabla de «loyal_rebels» no tiene «council» (government_missing_in_rebel_map, heredado).
    "common/rebel_types.txt": _crlf("free_rebels = {\n\tgovernment = {\n\t\tmonarchy = republic\n"
                                    "\t\trepublic = republic\n\t\tcouncil = council\n\t}\n}\n"
                                    "loyal_rebels = {\n\tgovernment = {\n\t\tmonarchy = monarchy\n"
                                    "\t\trepublic = monarchy\n\t}\n}\n"),
    "units/infantry.txt": _crlf("infantry = {\n\ttype = land\n\tactive = no\n\tsprite = Infantry\n}\n"),
    "units/frigate.txt": _crlf("frigate = {\n\ttype = naval\n\tactive = no\n\tsprite = Frigate\n}\n"),
    "poptypes/farmers.txt": _crlf("sprite = 1\nstrata = poor\n"),
    "poptypes/soldiers.txt": _crlf("sprite = 2\nstrata = poor\n"),
    # La provincia 1 aparece dos veces en el mismo archivo (H10).
    "history/pops/1836.1.1/North.txt": _crlf(
        "1 = {\n\tfarmers = {\n\t\tculture = alander\n\t\treligion = sunfaith\n\t\tsize = 1000\n\t}\n}\n"
        "2 = {\n\tfarmers = {\n\t\tculture = borlander\n\t\treligion = sunfaith\n\t\tsize = 800\n\t}\n}\n"
        "1 = {\n\tsoldiers = {\n\t\tculture = alander\n\t\treligion = moonfaith\n\t\tsize = 100\n\t}\n}\n"),
    "history/pops/1861.1.1/North.txt": _crlf(
        "1 = {\n\tfarmers = {\n\t\tculture = alander\n\t\treligion = sunfaith\n\t\tsize = 1200\n\t}\n}\n"),
    "history/wars/Old War.txt": _crlf('name = "Old War"\n1830.1.1 = {\n\tadd_attacker = AAA\n\tadd_defender = BBB\n'
                                      "\twar_goal = {\n\t\tcasus_belli = conquer_land\n\t\tactor = AAA\n"
                                      "\t\treceiver = BBB\n\t}\n}\n"),
    "history/diplomacy/Alliances.txt": _crlf('alliance = {\n\tfirst = AAA\n\tsecond = CCC\n\tstart_date = "1830.1.1"\n'
                                             '\tend_date = "1900.1.1"\n}\n'),
    # El evento 1003 lanza el 1999, que no existe (como el 11108 de vanilla: event_ref_missing heredado).
    "events/minigame_more.txt": _crlf("country_event = {\n\tid = 1003\n\ttitle = \"EVT_1003_NAME\"\n"
                                      "\tdesc = \"EVT_1003_NAME\"\n\tis_triggered_only = yes\n"
                                      "\toption = {\n\t\tname = \"EVT_1003_A\"\n\t\tcountry_event = 1001\n"
                                      "\t\tcountry_event = { id = 1999 days = 3 }\n\t\tset_country_flag = mg_done\n\t}\n}\n"),
    "interface/minigame.gfx": _crlf('spriteTypes = {\n\tspriteType = {\n\t\tname = "GFX_mg_icon"\n'
                                    '\t\ttexturefile = "gfx\\\\interface\\\\mg_icon.dds"\n\t\tnoOfFrames = 2\n\t}\n'
                                    '\ttextSpriteType = {\n\t\tname = "GFX_mg_button"\n'
                                    '\t\ttextureFile = "gfx/interface/mg_button.tga"\n\t}\n}\n'),
    "interface/minigame.gui": _crlf('guiTypes = {\n\twindowType = {\n\t\tname = "mg_window"\n'
                                    '\t\ticonType = {\n\t\t\tname = "mg_icon"\n\t\t\tspriteType = "GFX_mg_icon"\n'
                                    "\t\t}\n\t}\n}\n"),
    "gfx/interface/mg_icon.dds": b"DDS \x7c\x00\x00\x00minigame",
    "gfx/interface/mg_button.tga": b"\x00\x00\x02minigame",
    "gfx/flags/AAA.tga": b"\x00\x00\x02flag",
    "gfx/pictures/decisions/unite_lands.dds": b"DDS \x7c\x00\x00\x00picture",
    "localisation/minigame_names.csv": _loc(NAMES_ROWS),
}
GAME_FILES.update(RULES_FILES)

# Recuentos del minijuego (las pruebas del índice los comparan, como el criterio 1 con vanilla).
MINIGAME_COUNTS = {
    "tag": 4, "province": len(LAND), "sea_province": len(SEA), "region": 3, "sea_region": 2, "continent": 2,
    "climate": 2, "terrain": 3, "culture_group": 2, "culture": 4, "religion_group": 1, "religion": 2,
    "government": 3, "ideology": 3, "issue_group": 7, "national_value": 2, "technology": 2, "invention": 1,
    "goods": 2, "building": 1, "unit_type": 2, "pop_type": 2, "cb": 3, "bookmark": 2, "event": 3,
    "decision": 1, "war": 1, "sprite": 2, "gui_window": 1, "country_history": 2, "province_history": 3,
    "country_file": 4, "party": 4, "rebel_type": 2, "graphical_culture": 2, "tech_school": 1, "tech_folder": 1,
}


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
