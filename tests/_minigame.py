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
    "map/terrain.txt": _crlf("terrain = 8\ncategories = {\n"
                             "\tocean = {\n\t\tis_water = yes\n\t\tcolor = { 0 0 255 }\n\t}\n"
                             "\tplains = {\n\t\tcolor = { 0 255 0 }\n\t}\n"
                             "\thills = {\n\t\tcolor = { 120 120 0 }\n\t}\n}\n"),
    "common/defines.lua": _crlf("defines = {\n\nstart_date = '1836.1.1',\nend_date = '1935.12.31',\n\ncountry = {\n"
                                "\tYEARS_OF_PEACE = 20, -- años sin guerra\n\tBASE_TAX = 0.25,\n},\n\n}\n"),
    "common/bookmarks.txt": _crlf('bookmark = {\n\tname = "MG_START"\n\tdesc = "MG_START_DESC"\n\tdate = 1836.1.1\n}\n'
                                  'bookmark = {\n\tname = "MG_LATE"\n\tdesc = "MG_LATE_DESC"\n\tdate = 1861.1.1\n}\n'),
    "common/cultures.txt": _crlf("north_folk = {\n\tleader = european\n\tunit = NorthGC\n\talander = {\n"
                                 "\t\tcolor = { 100 20 20 }\n\t}\n\tborlander = {\n\t\tcolor = { 20 100 20 }\n\t}\n}\n"
                                 "south_folk = {\n\tleader = european\n"
                                 "\tcorlander = {\n\t\tcolor = { 20 20 100 }\n\t}\n"
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
                               "\tcitizenship_policy = {\n\t\tlimited_citizenship = { }\n"
                               "\t\tfull_citizenship = { }\n\t}\n"
                               "\twar_policy = {\n\t\tpro_military = { }\n\t\tanti_military = { }\n\t}\n}\n"
                               "political_reforms = {\n\tslavery = {\n\t\tyes_slavery = { }\n\t\tno_slavery = { }\n"
                               "\t\tnext_step_only = yes\n\t}\n}\n"
                               "social_reforms = {\n\tsafety = {\n\t\tno_safety = { }\n"
                               "\t\tgood_safety = { }\n\t}\n}\n"),
    "common/nationalvalues.txt": _crlf("nv_order = {\n\tmobilisation_size = 0.04\n}\n"
                                       "nv_liberty = {\n\tmobilisation_size = 0.02\n}\n"),
    "common/technology.txt": _crlf("folders = {\n\tarmy_tech = {\n\t\tarmy_doctrine\n\t\tlight_arms\n\t}\n}\n"
                                   "schools = {\n\ttraditional_academic = {\n"
                                   "\t\tarmy_tech_research_bonus = 0\n\t}\n}\n"),
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
    # Colores de uniforme de todos los TAG (sin ellos, country_colors_missing informaría en el minijuego limpio).
    "common/country_colors.txt": _crlf("AAA = {\n\tcolor1 = { 10 20 30 }\n\tcolor2 = { 200 200 200 }\n"
                                       "\tcolor3 = { 0 0 0 }\n}\nBBB = {\n\tcolor1 = { 40 50 60 }\n}\n"
                                       "CCC = {\n\tcolor1 = { 70 80 90 }\n}\nD01 = {\n\tcolor1 = { 100 110 120 }\n}\n"),
    "history/units/BBB_oob.txt": _crlf('army = {\n\tname = "Borland Guard"\n\tlocation = 1\n'
                                       '\tregiment = { name = "1st Guard" type = infantry home = 1 }\n}\n'),
    "history/diplomacy/Alliances.txt": _crlf('alliance = {\n\tfirst = AAA\n\tsecond = CCC\n\tstart_date = "1830.1.1"\n'
                                             '\tend_date = "1900.1.1"\n}\n'),
    # El evento 1003 lanza el 1999, que no existe (como el 11108 de vanilla: event_ref_missing heredado).
    "events/minigame_more.txt": _crlf("country_event = {\n\tid = 1003\n\ttitle = \"EVT_1003_NAME\"\n"
                                      "\tdesc = \"EVT_1003_NAME\"\n\tis_triggered_only = yes\n"
                                      "\toption = {\n\t\tname = \"EVT_1003_A\"\n\t\tcountry_event = 1001\n"
                                      "\t\tcountry_event = { id = 1999 days = 3 }\n"
                                      "\t\tset_country_flag = mg_done\n\t}\n}\n"),
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

    def vfs(self, **kwargs):
        """``VirtualFS`` del juego y el mod ya escaneada (``kwargs``: ``replace_paths``…)."""
        from vic2studio.core.vfs import VirtualFS

        vfs = VirtualFS(self.game_root, self.mod_root, descriptor=self.descriptor, **kwargs)
        vfs.scan()
        return vfs

    def snapshot(self, **kwargs):
        return self.vfs(**kwargs).snapshot()

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
                   game_files: Mapping[str, bytes | str] | None = None, drop: Iterable[str] = ()) -> MiniGame:
    """Juego y mod en ``root`` (una carpeta temporal propia si es None; ``cleanup`` la borra).

    ``mod=False``: mod vacío. ``mod_copies``: archivos del juego que el mod trae
    copiados tal cual (un mod copia completa, como VSM). ``mod_files`` y
    ``game_files`` añaden o sustituyen archivos; ``drop`` quita archivos del juego (iteración 5).
    """
    game = dict(GAME_FILES)
    game.update(game_files or {})
    for rel in drop:
        game.pop(rel, None)
    files: dict[str, bytes | str] = dict(MOD_FILES) if mod else {}
    for rel in mod_copies:
        files[rel] = game[rel]
    files.update(mod_files or {})
    return MiniGame(build_layers(game=game, mod=files, mod_name=mod_name, base=root))


# --- ampliación de la revisión de la iteración 3: dependencias --------------------------------------------


def build_minigame_with_deps(dependencies: Mapping[str, Mapping[str, bytes | str]], *,
                             mod_files: Mapping[str, bytes | str] | None = None,
                             game_files: Mapping[str, bytes | str] | None = None,
                             root: Path | None = None) -> MiniGame:
    """El minijuego con el mod vacío (o con ``mod_files``) sobre ``dependencies`` (``{nombre: archivos}``, en el
    orden en que se declaran: la última gana). ``deps_vfs``/``deps_snapshot`` las cargan."""
    game = dict(GAME_FILES)
    game.update(game_files or {})
    return MiniGame(build_layers(game=game, mod=dict(mod_files or {}), dependencies=dependencies, base=root))


def deps_vfs(game: MiniGame, **kwargs):
    """``VirtualFS`` escaneada del juego, las dependencias de ``game`` y el mod."""
    return game.vfs(dependencies=game.layers.dependencies, **kwargs)


def deps_snapshot(game: MiniGame, **kwargs):
    return deps_vfs(game, **kwargs).snapshot()


# --- ampliación de la iteración 4: fragmentos que solo usan los esquemas ---------------------------------------
# No entran en GAME_FILES (otras pruebas cuentan sus archivos y sus símbolos): el arnés de esquemas y las pruebas de
# la iteración 4 los pasan con ``build_minigame(game_files=SCHEMA_GAME_FILES)``. Todo inventado.

SCHEMA_GAME_FILES: dict[str, str] = {
    # Modificadores de evento: valores sueltos y un icono, como los de vanilla (sin copiar ninguno).
    "common/event_modifiers.txt": _crlf("good_harvest = {\n\ticon = 2\n\tfarm_rgo_eff = 0.1\n}\n"
                                        "bad_winter = {\n\ticon = 5\n\tpop_militancy_modifier = 0.02\n"
                                        "\tlocal_supply = -0.5\n}\n"),
    # Un tipo de modificador de otro archivo con el mismo «kind» del índice: no es un modificador de evento.
    "common/static_modifiers.txt": _crlf("mg_static = {\n\tprestige = 1\n}\n"),
}

# Un país con nombres de barcos (``unit_names``): para el compañero UnitNamesSlot.
UNIT_NAMES_COUNTRY = _crlf("""\
color = { 10 20 30 }
graphical_culture = Generic

unit_names = {
	frigate = {
		"Aland Star" "Northern Wind"
	}
}
""")


# --- ampliación de la iteración 5: el mapa completo (wizard §19.1) -------------------------------------------------
# Como SCHEMA_GAME_FILES, no entra en GAME_FILES (otras pruebas cuentan sus archivos, sus símbolos y sus
# problemas): las pruebas del mapa lo piden con ``build_map_minigame()``. Todo inventado y generado por código; lo
# único «real» es la forma (los nombres de las claves y de las columnas). Coordenadas del juego: ``y`` es la fila de
# la imagen leída de arriba abajo y el norte está en las ``y`` altas (H1): en la vista, las provincias 5–8 quedan
# encima de las 1–4.

MAP_BOOKMARK_DATES = ("1836.1.1", "1861.1.1")       # las de common/bookmarks.txt (GAME_FILES)

# default.map con todas sus claves y un sea_start repetido (el 10, dos veces seguidas: como el de vanilla, decisión 4
# del contrato de la iteración 5). ``SEA_STARTS`` es la lista tal cual, con el duplicado y en su orden.
SEA_STARTS = (9, 10, 10, 11, 12)
DEFAULT_MAP = _crlf(
    "max_provinces = 13\nsea_starts = {\n\t" + " ".join(map(str, SEA_STARTS)) + "\n}\n"
    'definitions = "definition.csv"\nprovinces = "provinces.bmp"\npositions = "positions.txt"\n'
    'terrain = "terrain.bmp"\nrivers = "rivers.bmp"\nterrain_definition = "terrain.txt"\n'
    'tree_definition = "trees.txt"\ncontinent = "continent.txt"\nadjacencies = "adjacencies.csv"\n'
    'region = "region.txt"\nregion_sea = "region_sea.txt"\nprovince_flag_sprite = "province_flag_sprites"\n\n'
    "border_heights = {\n\t40\n\t60\n\t80\n}\nterrain_sheet_heights = {\n\t50\n}\ntree = 35\n"
    "border_cutoff = 90.0\n")

# Índices de terrain.bmp: los de tierra apuntan a una categoría de terrain.txt; el mar usa el 254.
TERRAIN_PLAINS, TERRAIN_HILLS, TERRAIN_PEAKS, TERRAIN_SHORE, TERRAIN_OCEAN = 0, 1, 2, 4, 254
# Categoría mayoritaria de cada provincia según terrain.bmp (la 5 lleva además ``terrain = hills`` en su historia).
TERRAIN_OF = {1: "plains", 2: "plains", 3: "plains", 4: "hills", 5: "plains", 6: "hills", 7: "plains",
              8: "mountain", 9: "ocean", 10: "ocean", 11: "ocean", 12: "ocean"}
TERRAIN_TXT = _crlf(
    "terrain = 8\ncategories = {\n"
    "\tocean = {\n\t\tis_water = yes\n\t\tmovement_cost = 1.0\n\t\tcolor = { 0 0 255 }\n\t}\n"
    "\tplains = {\n\t\tmovement_cost = 1.0\n\t\tfarm_rgo_size = 0.1\n\t\tcolor = { 0 255 0 }\n\t}\n"
    "\thills = {\n\t\tmovement_cost = 1.2\n\t\tdefence = 1\n\t\tcolor = { 120 120 0 }\n\t}\n"
    "\tmountain = {\n\t\tmovement_cost = 1.5\n\t\tdefence = 2\n\t\tcolor = { 90 90 90 }\n\t}\n}\n\n"
    f"mg_plains = {{\n\ttype = plains\n\tcolor = {{ {TERRAIN_PLAINS} }}\n\tpriority = 3\n}}\n"
    f"mg_hills = {{\n\ttype = hills\n\tcolor = {{ {TERRAIN_HILLS} }}\n\tpriority = 2\n}}\n"
    f"mg_peaks = {{\n\ttype = mountain\n\tcolor = {{ {TERRAIN_PEAKS} }}\n\tpriority = 1\n\thas_texture = no\n}}\n"
    # Una entrada con varios índices (en vanilla hay una con 191).
    f"mg_shore = {{\n\ttype = plains\n\tcolor = {{ 3 {TERRAIN_SHORE} 5 }}\n\tpriority = 4\n}}\n"
    f"mg_ocean = {{\n\ttype = ocean\n\tcolor = {{ {TERRAIN_OCEAN} }}\n\tpriority = 0\n}}\n")

# Índices de rivers.bmp: 0 nacimiento, 1 confluencia, 2–4 anchos; 255 tierra sin río y 254 mar.
RIVER_SOURCE, RIVER_JOIN, RIVER_NARROW, RIVER_WIDE, RIVER_SEA, RIVER_NONE = 0, 1, 2, 3, 254, 255
# El río nace en la provincia 5, baja por la fila 20 hasta la 8 y recibe un afluente de la 7 (4-conexo).
RIVER_MAIN = tuple((x, 20) for x in range(4, 40))
RIVER_BRANCH = tuple((24, y) for y in range(28, 20, -1))


def terrain_index_at(x: int, y: int) -> int:
    """Índice de ``terrain.bmp`` en el píxel. La 6 es de colinas por mayoría (60 de sus 160 px son llanura) y la 3
    tiene una franja de costa (30 px con el índice 4, también llanura); el color sin provincia cuenta como llanura."""
    province = province_at(x, y)
    if province is None:
        return TERRAIN_PLAINS
    if province in SEA:
        return TERRAIN_OCEAN
    if province == 6:
        return TERRAIN_PLAINS if y >= 26 else TERRAIN_HILLS
    if province == 3 and y < 3:
        return TERRAIN_SHORE
    return {"plains": TERRAIN_PLAINS, "hills": TERRAIN_HILLS, "mountain": TERRAIN_PEAKS}[TERRAIN_OF[province]]


def river_index_at(x: int, y: int) -> int:
    """Índice de ``rivers.bmp`` en el píxel."""
    if (x, y) == RIVER_MAIN[0] or (x, y) == RIVER_BRANCH[0]:
        return RIVER_SOURCE
    if (x, y) == (RIVER_BRANCH[-1][0], RIVER_MAIN[0][1]):
        return RIVER_JOIN
    if (x, y) in RIVER_MAIN:
        return RIVER_WIDE if x > RIVER_BRANCH[0][0] else RIVER_NARROW
    if (x, y) in RIVER_BRANCH:
        return RIVER_NARROW
    province = province_at(x, y)
    return RIVER_SEA if province in SEA else RIVER_NONE


def indexed_bmp(index_at) -> bytes:
    """BMP de 8 bits con paleta de 256 colores (cabecera de 1 078 B, como los del juego), 64×32, de abajo arriba y
    con 2 bytes de cola tras los píxeles (también como los del juego). La paleta es inventada."""
    width, height = MAP_SIZE
    stride = (width + 3) & ~3
    palette = b"".join(bytes(((i * 7) % 256, (i * 3 + 40) % 256, 255 - i, 0)) for i in range(256))
    rows = []
    for y in range(height - 1, -1, -1):
        row = bytes(index_at(x, y) for x in range(width))
        rows.append(row + b"\0" * (stride - len(row)))
    pixels = b"".join(rows)
    offset = 54 + len(palette)
    header = (b"BM" + (offset + len(pixels)).to_bytes(4, "little") + b"\0\0\0\0" + offset.to_bytes(4, "little")
              + (40).to_bytes(4, "little") + width.to_bytes(4, "little") + height.to_bytes(4, "little")
              + (1).to_bytes(2, "little") + (8).to_bytes(2, "little") + b"\0" * 4 + len(pixels).to_bytes(4, "little")
              + (2835).to_bytes(4, "little") * 2 + b"\0" * 8)
    return header + palette + pixels + b"\0\0"


def province_pixels(province: int) -> list[tuple[int, int]]:
    """Píxeles ``(x, y)`` de una provincia en coordenadas del juego."""
    width, height = MAP_SIZE
    return [(x, y) for y in range(height) for x in range(width) if province_at(x, y) == province]


def province_centroid(province: int) -> tuple[float, float]:
    """Centroide ``(x, y)`` exacto (media de los centros de sus píxeles, en coordenadas del juego)."""
    pixels = province_pixels(province)
    return (sum(x for x, _ in pixels) / len(pixels), sum(y for _, y in pixels) / len(pixels))


# Vecinos por lado (4-conexos). El mapa es cíclico en horizontal: con ``wrap_x`` la columna 63 toca la 0.
NEIGHBORS = {
    1: {2, 5}, 2: {1, 3, 6}, 3: {2, 4, 7}, 4: {3, 8, 9, 10}, 5: {1, 6}, 6: {2, 5, 7}, 7: {3, 6, 8},
    8: {4, 7, 11, 12}, 9: {4, 10}, 10: {4, 9, 11}, 11: {8, 10, 12}, 12: {8, 11},
}
NEIGHBORS_WRAP_X = {**NEIGHBORS, 1: {2, 5, 9, 10}, 5: {1, 6, 11, 12}, 9: {1, 4, 10}, 10: {1, 4, 9, 11},
                    11: {5, 8, 10, 12}, 12: {5, 8, 11}}

# Punto ``unit`` de cada provincia en positions.txt (dentro de ella, cerca del centroide). La 11 tiene el bloque
# vacío y la 12 solo datos del rótulo, como pasa en vanilla.
UNIT_POINTS = {p: (int(province_centroid(p)[0]), int(province_centroid(p)[1])) for p in range(1, 11)}


def _positions_txt() -> str:
    blocks = []
    for province in sorted(PROVINCE_COLORS):
        if province == 11:
            blocks.append(f"{province} = {{\n}}\n")
            continue
        if province == 12:
            blocks.append(f"{province} = {{\n\ttext_position = {{\n\t\tx = 52.000\n\t\ty = 28.000\n\t}}\n"
                          "\ttext_rotation = 0.100\n\ttext_scale = 1.200\n}\n")
            continue
        x, y = UNIT_POINTS[province]
        lines = [f"{province} = {{", f"\tunit = {{\n\t\tx = {x}.000\n\t\ty = {y}.000\n\t}}",
                 f"\ttext_position = {{\n\t\tx = {x}.500\n\t\ty = {y + 2}.000\n\t}}", "\ttext_scale = 1.000"]
        if province in LAND:
            lines.append(f"\tbuilding_position = {{\n\t\tfort = {{\n\t\t\tx = {x + 1}.000\n\t\t\ty = {y - 2}.000\n"
                         f"\t\t}}\n\t\trailroad = {{\n\t\t\tx = {x - 1}.000\n\t\t\ty = {y - 1}.000\n\t\t}}\n\t}}")
            lines.append(f"\tfactory = {{\n\t\tx = {x + 2}.000\n\t\ty = {y + 1}.000\n\t}}")
            lines.append(f"\tbuilding_construction = {{\n\t\tx = {x - 2}.000\n\t\ty = {y + 1}.000\n\t}}")
            lines.append(f"\tmilitary_construction = {{\n\t\tx = {x}.000\n\t\ty = {y - 3}.000\n\t}}")
        if province in (4, 8):          # las dos costeras: base naval con su giro
            lines.append("\tbuilding_rotation = {\n\t\tnaval_base = 1.570\n\t}")
        if province == 1:
            lines.append(f"\tcity = {{\n\t\tx = {x + 1}.000\n\t\ty = {y + 1}.000\n\t}}")
        lines.append("}")
        blocks.append("\n".join(lines) + "\n")
    return _crlf("".join(blocks))


# adjacencies.csv: cabecera comentada, un estrecho (1–4 por el mar 9, vecinos de él solo con el mapa cíclico), un
# paso infranqueable, un canal, una fila comentada, un comentario de sección y una línea en blanco.
STRAIT = (1, 4, 9)
IMPASSABLE = (2, 6)
CANAL = (4, 8, 10, 1)                 # desde, hasta, a través de, número de canal
ADJACENCIES_CSV = _crlf(
    "#From;To;Type;Through;Data;Comment\n"
    f"{STRAIT[0]};{STRAIT[1]};sea;{STRAIT[2]};0;Estrecho del Norte\n"
    "#5;8;sea;12;0;Estrecho del Sur (desactivado)\n"
    "\n"
    "# Pasos cerrados\n"
    f"{IMPASSABLE[0]};{IMPASSABLE[1]};impassable;0;0;Cordillera central\n"
    f"{CANAL[0]};{CANAL[1]};canal;{CANAL[2]};{CANAL[3]};Canal del Este\n")


def _pop(pop_type: str, culture: str, religion: str, size: int, *extra: str) -> str:
    lines = [f"\t{pop_type} = {{", f"\t\tculture = {culture}", f"\t\treligion = {religion}", f"\t\tsize = {size}",
             *(f"\t\t{line}" for line in extra), "\t}"]
    return "\n".join(lines) + "\n"


def _pops(*blocks: tuple[int, str]) -> str:
    return _crlf("".join(f"{province} = {{\n{body}}}\n" for province, body in blocks))


MAP_GAME_FILES: dict[str, str | bytes] = {
    "map/default.map": DEFAULT_MAP,
    "map/terrain.txt": TERRAIN_TXT,
    "map/terrain.bmp": indexed_bmp(terrain_index_at),
    "map/rivers.bmp": indexed_bmp(river_index_at),
    "map/trees.txt": _crlf("# Arbolado del minijuego (inventado; el Studio no lo lee)\nterrain = 8\n"),
    "map/positions.txt": _positions_txt(),
    "map/adjacencies.csv": ADJACENCIES_CSV,
    # Historias de las provincias 4–8 (las de 1–3 están en GAME_FILES). Fechas de inicio: 1836.1.1 y 1861.1.1.
    # La 4 tiene un bloque dentro del intervalo del segundo bookmark, (1836.1.1, 1861.1.1]: editar en 1861.1.1
    # escribe en él y no crea otro (criterio 5).
    "history/provinces/north/4 - Colina.txt": _crlf(
        "owner = AAA\ncontroller = AAA\nadd_core = AAA\nadd_core = BBB\ntrade_goods = grain\nlife_rating = 30\n"
        "naval_base = 1\n\n1850.6.1 = {\n\towner = BBB\n\tcontroller = BBB\n}\n"),
    # Dos bloques con la misma fecha (137 archivos de vanilla los tienen), uno posterior al último bookmark y una
    # anulación de terreno.
    "history/provinces/south/5 - Quinta.txt": _crlf(
        "owner = BBB\ncontroller = BBB\nadd_core = BBB\ntrade_goods = grain\nlife_rating = 35\nrailroad = 1\n"
        "terrain = hills\n\n1845.3.1 = { railroad = 2 }\n1845.3.1 = { add_core = CCC }\n"
        "1870.1.1 = {\n\tfort = 1\n\tremove_core = CCC\n}\n"),
    # Solo LF (325 historias de vanilla) y un bloque party_loyalty.
    "history/provinces/south/6 - Bosque.txt": (
        "owner = BBB\ncontroller = BBB\nadd_core = BBB\ntrade_goods = grain\nlife_rating = 20\n"
        "party_loyalty = {\n\tideology = conservative\n\tloyalty_value = 10\n}\n"),
    "history/provinces/east/7 - Vado.txt": _crlf(
        "owner = CCC\ncontroller = CCC\nadd_core = CCC\ntrade_goods = fish\nlife_rating = 25\ncolonial = 1\n"
        "is_slave = yes\n"),
    # Un bloque justo en la fecha del segundo bookmark: cuenta en 1861.1.1 (el intervalo es cerrado por la derecha).
    "history/provinces/east/8 - Cumbre.txt": _crlf(
        "owner = CCC\ncontroller = CCC\nadd_core = CCC\ntrade_goods = fish\nlife_rating = 15\nfort = 1\n"
        "naval_base = 1\n\n1861.1.1 = {\n\tcontroller = AAA\n}\n"),
    # POPs del resto de provincias de tierra (las de 1 y 2 están en GAME_FILES, con la 1 repetida en 1836.1.1).
    # Un mismo tipo de POP repetido en una provincia (7 713 veces en vanilla) y los campos opcionales.
    "history/pops/1836.1.1/South.txt": _pops(
        (3, _pop("farmers", "corlander", "moonfaith", 900)),
        (4, _pop("farmers", "alander", "sunfaith", 700) + _pop("farmers", "borlander", "sunfaith", 300)
            + _pop("soldiers", "alander", "sunfaith", 50)),
        (5, _pop("farmers", "borlander", "sunfaith", 1500, "militancy = 2.5")),
        (6, _pop("farmers", "borlander", "moonfaith", 400)),
        (7, _pop("farmers", "corlander", "moonfaith", 600, "rebel_type = free_rebels")),
        (8, _pop("soldiers", "dominer", "moonfaith", 80))),
    # En la segunda fecha, la 7 aparece dos veces en el mismo archivo (como la 2482 de vanilla) y faltan la 3 y la 8.
    "history/pops/1861.1.1/South.txt": _pops(
        (4, _pop("farmers", "borlander", "sunfaith", 1100)),
        (7, _pop("farmers", "corlander", "moonfaith", 650)),
        (5, _pop("farmers", "borlander", "sunfaith", 1700)),
        (6, _pop("farmers", "borlander", "moonfaith", 450)),
        (7, _pop("soldiers", "corlander", "moonfaith", 40))),
    "localisation/minigame_map.csv": _loc([
        ("AAA_1", "Aland Lowlands", "Tierras Bajas de Alandia"), ("BBB_4", "Borland Hills", "Colinas de Borlandia"),
        ("CCC_7", "Corland Heights", "Altos de Corlandia"), ("west_land", "Westland", "Poniente"),
        ("east_land", "Eastland", "Levante"), ("mild_climate", "Mild", "Suave"), ("harsh_climate", "Harsh", "Duro"),
        ("ocean", "Ocean", "Océano"), ("plains", "Plains", "Llanura"), ("hills", "Hills", "Colinas"),
        ("mountain", "Mountain", "Montaña"),
    ]),
}

# El id 3 está en dos carpetas (GAME_FILES, H9): con ``clean=True`` se quita la copia de west/ para tener un mapa
# sin errores de coherencia (criterio 8). Los avisos conocidos se quedan: el color sin fila, el «50.», el sea_start
# repetido, PROV12 sin texto y el nombre irregular de la provincia 2.
MAP_CLEAN_DROPS = ("history/provinces/west/3 - Costa.txt",)

# Dueño vigente de cada provincia de tierra en las dos fechas de inicio (lo que debe dar ProvinceFacts).
OWNERS = {"1836.1.1": {1: "AAA", 2: "BBB", 3: "CCC", 4: "AAA", 5: "BBB", 6: "BBB", 7: "CCC", 8: "CCC"},
          "1861.1.1": {1: "AAA", 2: "BBB", 3: "CCC", 4: "BBB", 5: "BBB", 6: "BBB", 7: "CCC", 8: "CCC"}}
# Bloques de POP por (fecha, provincia): archivo y cuántos bloques tiene en él (2 = repetido).
POP_BLOCKS = {
    "1836.1.1": {1: ("North.txt", 2), 2: ("North.txt", 1), 3: ("South.txt", 1), 4: ("South.txt", 1),
                 5: ("South.txt", 1), 6: ("South.txt", 1), 7: ("South.txt", 1), 8: ("South.txt", 1)},
    "1861.1.1": {1: ("North.txt", 1), 4: ("South.txt", 1), 5: ("South.txt", 1), 6: ("South.txt", 1),
                 7: ("South.txt", 2)},
}
# Población total por provincia en cada fecha (suma de ``size`` de todos sus bloques, también los repetidos).
POPULATION = {
    "1836.1.1": {1: 1100, 2: 800, 3: 900, 4: 1050, 5: 1500, 6: 400, 7: 600, 8: 80},
    "1861.1.1": {1: 1200, 4: 1100, 5: 1700, 6: 450, 7: 690},
}


def build_map_minigame(root: Path | None = None, *, clean: bool = False,
                       game_files: Mapping[str, bytes | str] | None = None, drop: Iterable[str] = (),
                       **kwargs) -> MiniGame:
    """El minijuego con el mapa completo de la iteración 5 (``GAME_FILES`` + ``MAP_GAME_FILES``).

    ``clean=True`` quita ``MAP_CLEAN_DROPS`` (la historia duplicada). ``game_files`` añade o sustituye encima y
    ``drop`` quita archivos; el resto de argumentos, como en ``build_minigame``."""
    files: dict[str, bytes | str] = dict(MAP_GAME_FILES)
    files.update(game_files or {})
    return build_minigame(root, game_files=files, drop=(*(MAP_CLEAN_DROPS if clean else ()), *drop), **kwargs)


# --- ampliación de la iteración 7: eventos y decisiones con guion de verdad ------------------------------------
# No entran en GAME_FILES ni en MOD_FILES (otras pruebas cuentan sus archivos y sus símbolos): las pruebas de la
# iteración 7 los pasan con ``build_script_minigame()``. Todo inventado, con la forma de los archivos reales:
# grupos AND/OR/NOT en mayúsculas y minúsculas, ámbitos, un MTTH con dos modificadores, ``ai_chance``,
# ``ai_will_do``, una clave que ningún catálogo conoce, textos reutilizados entre eventos y un título en prosa.

SCRIPT_EVENT_IDS = (2001, 2002, 2003)
SCRIPT_DECISIONS = ("mg_build_harbour", "mg_call_council")
SCRIPT_BROKEN_DECISIONS = "decisions/tst_broken.txt"          # sin la «}» final, como dos archivos del usuario
SCRIPT_BROKEN_IDS = ("tst_broken_one", "tst_broken_two")

SCRIPT_GAME_FILES: dict[str, str] = {
    # 2001: país. Dos países, «1842 o después», tres gobiernos y «antes de 1845» (la forma del criterio 5), con
    # MTTH de 6 meses × 0.75 × 0.95. 2002: provincia, con una condición de país fuera de sitio (criterio 6).
    # 2003: solo por otro evento, con el título en prosa y la descripción de 2001.
    "events/mg_flavor.txt": _crlf("""\
# Eventos del minijuego para el constructor de condiciones.
country_event = {
	id = 2001
	title = "EVTNAME2001"
	desc = "EVTDESC2001"
	picture = "mg_harbour"

	trigger = {
		OR = {
			tag = AAA
			tag = BBB
		}
		year = 1842 # desde ese año
		OR = {
			government = monarchy
			government = republic
			government = council
		}
		NOT = { year = 1845 }
		mg_made_up_check = 3
	}

	mean_time_to_happen = {
		months = 6
		modifier = {
			factor = 0.75
			prestige = 10
		}
		modifier = {
			factor = 0.95
			is_greater_power = yes
		}
	}

	immediate = { set_country_flag = mg_seen }

	option = {
		name = "EVTOPTA2001"
		prestige = 5
		any_owned = {
			limit = { owned_by = AAA }
			add_core = BBB
		}
		ai_chance = {
			factor = 70
			modifier = {
				factor = 0
				NOT = { tag = AAA }
			}
		}
	}
	option = {
		name = "EVTOPTB2001"
		BBB = { relation = { who = AAA value = 50 } }
		country_event = { id = 2003 days = 3 }
	}
}

province_event = {
	id = 2002
	title = "EVTNAME2002"
	desc = "EVTDESC2002"
	fire_only_once = yes

	trigger = {
		prestige = 5
		owner = { tag = AAA }
		not = { owned_by = CCC }
	}

	mean_time_to_happen = { months = 24 }

	option = {
		name = "EVTOPTA2002"
		owner = { prestige = 1.5 }
		3 = { add_core = AAA }
	}
}

country_event = {
	id = 2003
	title = "A plain title"
	desc = "EVTDESC2001"
	is_triggered_only = yes

	option = {
		name = "EVTOPTA2001"
		musket_drill = 1
	}
}
"""),
    "decisions/mg_decisions.txt": _crlf("""\
political_decisions = {
	mg_build_harbour = {
		potential = {
			tag = AAA
			NOT = { has_country_flag = mg_harbour_built }
		}
		allow = {
			prestige = 10
			musket_drill = 1
		}
		effect = {
			prestige = -5
			set_country_flag = mg_harbour_built
			capital_scope = { add_core = AAA }
		}
		ai_will_do = {
			factor = 1
			modifier = {
				factor = 0
				year = 1850
			}
		}
	}

	mg_call_council = {
		picture = mg_build_harbour
		alert = no
		potential = { }
		allow = { government = monarchy }
		effect = { government = council }
	}
}
"""),
    "localisation/mg_script.csv": _loc([
        ("EVTNAME2001", "The harbour question", "La cuestión del puerto"),
        ("EVTDESC2001", "Aland and Borland argue about the harbour.", "Aland y Borland discuten por el puerto."),
        ("EVTOPTA2001", "Build it", "Construirlo"), ("EVTOPTB2001", "Leave it", "Dejarlo"),
        ("EVTNAME2002", "A quiet province", "Una provincia tranquila"),
        ("EVTDESC2002", "Nothing happens here.", "Aquí no pasa nada."), ("EVTOPTA2002", "Good", "Bien"),
        ("mg_build_harbour_title", "Build the harbour", "Construir el puerto"),
        ("mg_build_harbour_desc", "A harbour for Aland.", "Un puerto para Aland."),
        ("mg_call_council_title", "Call the council", "Convocar el consejo"),
        ("mg_call_council_desc", "The council takes over.", "El consejo toma el mando."),
    ]),
}

SCRIPT_MOD_FILES: dict[str, str] = {
    # Falta la llave que cierra ``political_decisions``: un único ``unclosed_block`` en 1:23 (D17).
    SCRIPT_BROKEN_DECISIONS: _crlf("""\
political_decisions = {
	tst_broken_one = {
		potential = { tag = AAA }
		allow = { year = 1840 }
		effect = { prestige = 1 }
	}
	tst_broken_two = {
		potential = { tag = BBB }
		allow = { prestige = 3 }
		effect = { prestige = 2 }
	}
"""),
    "localisation/00_TST_script.csv": _loc([
        ("tst_broken_one_title", "First broken", "Primera rota"), ("tst_broken_one_desc", "One", "Una"),
        ("tst_broken_two_title", "Second broken", "Segunda rota"), ("tst_broken_two_desc", "Two", "Dos"),
    ]),
}


def event_picture_tga(width: int = 521, height: int = 203, color: tuple[int, int, int] = (90, 110, 150)) -> bytes:
    """Un TGA de 24 bits sin comprimir y de un solo color, con el tamaño de las imágenes de evento."""
    header = bytes([0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, width & 255, width >> 8, height & 255, height >> 8, 24, 0])
    red, green, blue = color
    return header + bytes([blue, green, red]) * (width * height)


def decision_picture_dds(size: int = 95, color: tuple[int, int, int] = (150, 110, 60)) -> bytes:
    """Un DDS A8R8G8B8 sin comprimir de un solo color, con el tamaño de las imágenes de decisión."""
    import numpy as np

    from vic2studio.core.gfx.dds import write_dds

    rgba = np.empty((size, size, 4), dtype=np.uint8)
    rgba[:, :] = (*color, 255)
    return write_dds(rgba)


def script_pictures() -> dict[str, bytes]:
    """Las imágenes del evento 2001 y de la decisión ``mg_build_harbour`` (válidas, generadas aquí)."""
    return {"gfx/pictures/events/mg_harbour.tga": event_picture_tga(),
            "gfx/pictures/decisions/mg_build_harbour.dds": decision_picture_dds()}


def build_script_minigame(root: Path | None = None, *, broken: bool = True, pictures: bool = True,
                          mod_files: Mapping[str, bytes | str] | None = None,
                          game_files: Mapping[str, bytes | str] | None = None, **kwargs) -> MiniGame:
    """El minijuego con los fragmentos de esquemas (``SCHEMA_GAME_FILES``) y los de guion de la iteración 7.

    ``broken=False`` deja fuera el archivo de decisiones sin cerrar; ``pictures=False``, las imágenes. El resto
    de argumentos son los de ``build_minigame``.
    """
    game: dict[str, bytes | str] = dict(SCHEMA_GAME_FILES)
    game.update(SCRIPT_GAME_FILES)
    if pictures:
        game.update(script_pictures())
    game.update(game_files or {})
    mod: dict[str, bytes | str] = {rel: data for rel, data in SCRIPT_MOD_FILES.items()
                                   if broken or rel != SCRIPT_BROKEN_DECISIONS}
    mod.update(mod_files or {})
    return build_minigame(root, mod_files=mod, game_files=game, **kwargs)
