"""Archivo de país (``common/countries/<Archivo>.txt``, wizard §14.2, H12). Iteración 6.

El documento entero es el registro y su id es el nombre del archivo sin ``.txt`` (como lo nombra
``countries.txt``): ``color``, ``graphical_culture``, los ``party`` (repetidos; sus nombres pueden repetirse entre
países, H12), ``unit_names`` por tipo de unidad y, opcionales, los colores por gobierno
(``fascist_dictatorship = { 40 40 40 }``). Lo crea el asistente «Nuevo país»; la ficha nacional (sala Naciones ›
Países) edita su color, su cultura gráfica y sus partidos.
"""

from __future__ import annotations

from ..schema import Color, Date, EntitySchema, Field, Group, IdSpec, KeyedFiles, Ref, Section, Text
from ..vfs.paths import VPath


def file_key(rel: VPath) -> str | None:
    """``common/countries/Prussia.txt`` → ``prussia.txt`` (el nombre de símbolo ``country_file`` del índice)."""
    name = VPath.of(rel).name
    return name.lower() if name.lower().endswith(".txt") else None


COUNTRY = EntitySchema(
    kind="country",
    layout=KeyedFiles("common/countries", new_name="{name}.txt", key=file_key),
    ident=IdSpec.FILE("{name}.txt"),
    provides="country_file",
    fields=(
        Section("identity", (
            Field("color", Color(), required=True),
            Field("graphical_culture", Ref("graphical_culture"), required=True),
        )),
        Section("parties", (
            Group("party", (
                Field("name", Text(), required=True),
                Field("start_date", Date()),
                Field("end_date", Date()),
                Field("ideology", Ref("ideology"), required=True),
                Field("economic_policy", Ref("issue_option")),
                Field("trade_policy", Ref("issue_option")),
                Field("religious_policy", Ref("issue_option")),
                Field("citizenship_policy", Ref("issue_option")),
                Field("war_policy", Ref("issue_option")),
            ), repeat=True, id_field="name", widget="table"),
        )),
    ),
    unknown="keep",
    hall="nations", section="countries", order=1, icon="countries",
    editable=True,
)

SCHEMAS = (COUNTRY,)
