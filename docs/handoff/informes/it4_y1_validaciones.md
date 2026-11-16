# Cierre de la iteración 4 — etapa Y1: seis validaciones que faltaban

Rama `wt/it4-y`. Todo el trabajo está en `core/` y en `tests/`; no se ha tocado `ui/**`,
`core/schema/record.py` ni `companions.py`.

## 1. Qué se ha hecho

Seis códigos nuevos del catálogo de validación (wizard §14.4, §14.10–§14.13), todos como reglas
globales `@rule` (salen en F7, en el panel de problemas y en la línea base como el resto):

| Código | Gravedad | Salta cuando… | Calla cuando… | Arreglo |
|---|---|---|---|---|
| `sprite_missing` | aviso | el modelo de una unidad (`sprite_override` si lo hay; si no, `sprite`) o su `sprite_mount` no es ningún actor de `interface/*.gfx`, ni con su nombre entero ni como `<cultura gráfica><sprite>` | la vista no tiene ningún actor; la unidad no tiene `sprite` | no |
| `unit_port_level_too_high` | error | `min_port_level` es mayor que el `max_level` del edificio de tipo `naval_base` (con varios, el más alto) | no hay puerto con `max_level` | `lower_min_port_level` |
| `government_flagtype_unknown` | aviso | ningún país tiene una bandera `gfx/flags/<TAG>_<flagType>.tga` | la vista no tiene ninguna bandera de país; el gobierno no tiene `flagType` | no |
| `culture_name_duplicate` | error | el mismo id de cultura está definido más de una vez en el `cultures.txt` efectivo (en dos grupos o dos veces en uno): un problema por cada definición de más | — | no |
| `bookmark_without_pops` | aviso | ninguna carpeta `history/pops/<fecha>` tiene una fecha igual o anterior a la del bookmark | el bookmark no tiene una fecha legible | no |
| `bookmark_camera_outside_map` | aviso | `cameraX`/`cameraY` caen fuera de `0…ancho` / `0…alto` del BMP de provincias (el borde cuenta como dentro): un problema por bookmark, en la primera coordenada que falla | no se puede leer el tamaño del mapa | `move_camera_into_map` |

Cada código tiene `issue.<código>`, `explain.title.<código>` y `explain.outcome.<código>` en español y
en inglés, un explicador («¿por qué?»), un caso en `tests/test_validate_rules.py` y sus pruebas propias
en `tests/test_validate_it4_y1.py`.

### Archivos

- `core/index/model.py`, `core/index/index.py`, `core/index/extractors/interface.py`: tipo de símbolo
  `ACTOR_KIND = "actor"` y extractor `actors` (`interface/*.gfx`, versión 1).
- `core/validate/rules/units.py` (nuevo): `sprite_missing` y `unit_port_level_too_high`.
- `core/validate/rules/bookmarks.py` (nuevo): `bookmark_without_pops` y `bookmark_camera_outside_map`.
- `core/validate/rules/cultures.py` (nuevo): `culture_name_duplicate`.
- `core/validate/rules/countries.py`: `government_flagtype_unknown` (junto a las otras de gobiernos).
- `core/validate/rules/localisation.py`: los actores no dan por usada una clave de texto.
- `core/validate/fixes.py`: `lower_min_port_level` y `move_camera_into_map`.
- `core/validate/explain.py`: cinco explicadores nuevos y `culture_name_duplicate` en el de duplicados.
- `core/validate/texts/issues.{es,en}.json`: 22 claves nuevas por idioma.
- `tests/test_validate_it4_y1.py` (nuevo, 66 pruebas), `tests/test_validate_rules.py` (6 casos y el
  heredado nuevo del minijuego), `tests/test_validate_fixes.py` (catálogo de arreglos).

## 2. Lo medido en el corpus (solo lectura)

Las reglas se escribieron después de medir, no antes:

- **Actores**: 19 archivos de `interface/` tienen `objectTypes`; dentro hay 294 entradas
  `EMFXActorType` con 285 nombres distintos. 22 culturas gráficas y 21 unidades.
- **`sprite`**: el nombre de la unidad se busca como `<cultura gráfica><sprite>`. Solo dos modelos
  tienen actor en las 22 culturas; uno, en 20; tres, en 3; uno, en 2; uno, en 1; y los diez barcos,
  solo en la cultura genérica. Por eso basta con que **una** cultura lo tenga: exigirlo en todas
  daría decenas de falsos positivos en vanilla.
- **`sprite_override`**: las 3 unidades que lo llevan tienen un `sprite` propio sin actor en ninguna
  cultura y un override con actor en las 22. Se comprueba el override y no el `sprite`.
- **`sprite_mount`**: 4 unidades, y el valor nombra el actor entero (no existe ninguno con prefijo de
  cultura). Se admiten las dos formas en todos los campos.
- **Puerto**: el edificio de tipo `naval_base` tiene `max_level = 6`; las 10 unidades navales piden
  de 0 a 5.
- **Banderas**: 4 tipos de bandera, cada uno con 271 países; 7 de los 8 gobiernos llevan `flagType`.
- **Culturas**: 226 en 34 grupos, ninguna repetida.
- **Bookmarks**: dos, con fechas 1836.1.1 y 1861.7.1; las carpetas de población son 1836.1.1 y
  1861.4.14. El segundo bookmark **no** tiene carpeta con su fecha exacta: el juego no exige que
  coincidan, y de ahí sale el criterio «igual o anterior». Las dos cámaras están dentro de 5616×2160.

Resultado: **vanilla da cero problemas de los seis códigos, y VSM (leído sin abrirlo como proyecto,
con `VirtualFS`) también**. Lo comprueba `CorpusTests`, que además planta los seis sobre vanilla en un
mod temporal y exige que se encuentren.

## 3. Decisiones

1. **Reglas globales y no validadores de esquema.** Los seis cruzan archivos (unidad ↔ `.gfx`, unidad
   ↔ edificio, gobierno ↔ banderas, bookmark ↔ carpetas y BMP). Como `@rule` llegan a F7 por el
   camino de siempre (`Validator`), entran en la línea base y se ocultan como heredados si ya están en
   el juego (I11). `F7Tests` comprueba que salen junto a los de esquema de la misma entidad
   (`with_schema_problems`), con el mismo id y con el campo, y que no se duplican.
2. **Un solo extractor nuevo.** Las unidades, los bookmarks, los gobiernos, los edificios, las
   culturas y las imágenes ya estaban en el índice. Los campos que no estaban en los `attrs`
   (`sprite`, `min_port_level`, `cameraX`…) se leen del archivo analizado con `ctx.parse`, que además
   da la línea exacta y ve lo que está sin guardar. Así no se sube la versión de ningún extractor
   existente y la caché del índice sigue valiendo: solo se calcula lo de `interface/*.gfx` para el
   extractor nuevo (`test_a_cache_written_before_the_extractor_existed_keeps_the_rest`).
3. **`ACTOR_KIND` sin el prefijo `KIND_`.** Las pruebas de la paleta y del índice recorren las
   constantes `KIND_*` y exigen una etiqueta visible para cada una; esa etiqueta vive en `ui/**`, que
   esta etapa no puede tocar. El tipo queda fuera del buscador por defecto (`index.NOT_SEARCHED`);
   pidiéndolo por su nombre sí se encuentra. Ver la petición 1.
4. **Guardas de vista incompleta.** Sin actores, sin puerto, sin banderas de país o sin tamaño de
   mapa no hay con qué comparar y la regla calla, en vez de marcar todo. Es lo mismo que ya hacen las
   reglas de imágenes.
5. **Comparación sin distinguir mayúsculas** en actores y tipos de bandera. En vanilla coinciden con
   sus mayúsculas; lo que haga el juego con otras es [verificar en juego], y así no hay falsos
   positivos.
6. **Los textos no afirman más de lo que se sabe.** En `sprite_missing`,
   `government_flagtype_unknown`, `culture_name_duplicate` y `bookmark_without_pops` el desenlace dice
   lo que puede pasar y que está sin comprobar en el juego. El explicador de la población enseña la
   fecha del bookmark y qué falta; no lista las carpetas posteriores con un veredicto, porque qué
   carpeta carga el juego no se sabe. Una prueba lo vigila en los dos idiomas.
7. **Arreglos solo donde son naturales y seguros.** Dos, los dos con confirmación (`safe=False`) y con
   el plan igual a la aplicación:
   - `lower_min_port_level`: cambia solo el valor de `min_port_level` por el máximo del puerto.
   - `move_camera_into_map`: lleva cada coordenada que cae fuera al borde más cercano (0 o el tamaño);
     la que está dentro no se toca, y solo se toca el bookmark del problema.
   Los dos van en una transacción `undo.fix_<arreglo>`, conservan el resto del archivo byte a byte y,
   si la entidad es del juego, copian antes el archivo al mod. Para los otros cuatro no hay un valor
   correcto que el programa pueda elegir (qué modelo, qué bandera, qué cultura sobra, qué fecha).
8. **Gravedades.** Error donde el efecto es seguro (una unidad que no se puede construir; un id
   repetido); aviso en lo demás.

## 4. Pruebas

Sin corpus:

- `tests.test_validate_it4_y1`: `Ran 66 tests … OK (skipped=4)` (las 4 de corpus).
- Validación, índice y reglas (`test_validate_it4_y1`, `test_validate_rules`, `test_validate_fixes`,
  `test_validate_explain`, `test_validate_baseline`, `test_validate_review_it3`,
  `test_index_extractors`, `test_index_cache`, `test_index_combine`, `test_index_review_it3`,
  `test_rules_game`, `test_rules_ids`, `test_locsync`): `Ran 259 tests … OK (skipped=9)`.
- Interfaz y extremo a extremo que usan la validación (`test_ui_real_project`, `test_e2e_it3`,
  `test_e2e_it4`, `test_ui_session`, `test_ui_validation`, `test_ui_review_it3`, `test_schema_it4`,
  `test_validate_review_it3`, `test_contract_it3`, `test_ui_palette`, `test_locsync`,
  `test_ui_entity`): `Ran 275 tests … OK (skipped=8)`.

Con corpus:

- `tests.test_validate_it4_y1.CorpusTests`: `Ran 4 tests … OK`.
- `test_validate_corpus`, `test_index_corpus`, `test_validate_review_it3`, `test_e2e_it3`,
  `test_e2e_it4`, `test_schema_criteria`, `test_schema_review_it4`, `test_locsync`, `test_ui_palette`,
  `test_rules_game`, `test_no_paradox_data`: `Ran 136 tests … OK`.

Las cuatro de reglas (`test_arch_writes`, `test_i18n`, `test_packaging`, `test_no_paradox_data`) y
`test_texts`: en verde. La batería completa no se ha pasado (la pasa el integrador).

## 5. Mutantes

49 mutantes hechos a mano (cada uno: cambiar el código, pasar `test_validate_it4_y1`,
`test_validate_rules` y `test_validate_fixes`, y restaurar). **Los 49 mueren.** Dos sobrevivieron a
la primera pasada (M23 y M24) y se añadieron los casos que los matan: una bandera cuyo prefijo no es
un TAG y una bandera en una subcarpeta de `gfx/flags`.

| N.º | Mutante | Lo mata |
|---|---|---|
| M01 | sprite: condición invertida | `test_a_model_that_is_no_actor_is_reported_on_its_line` y 13 más |
| M02 | sprite: sin la guarda de «ningún actor» | `test_without_any_actor_in_the_view_the_rule_is_silent` y 1 más |
| M03 | sprite: ignora `sprite_override` | `test_with_an_override_the_override_is_the_model` |
| M04 | sprite: sin el prefijo de cultura | `test_one_graphical_culture_with_the_actor_is_enough` y 11 más |
| M05 | sprite: sin el nombre entero | `test_the_name_alone_also_counts_and_case_does_not` |
| M06 | sprite: distingue mayúsculas | `test_the_name_alone_also_counts_and_case_does_not` y 11 más |
| M07 | sprite: no mira la montura | `test_the_mount_is_checked_and_its_attach_node_is_not` |
| M08 | puerto: condición invertida | `test_a_port_level_above_the_maximum_is_an_error_on_its_line` y 11 más |
| M09 | puerto: el máximo ya falla (`>=`) | `test_the_maximum_itself_and_lower_levels_are_fine` y 2 más |
| M10 | puerto: se queda con el puerto más bajo | `test_with_two_ports_the_highest_counts` |
| M11 | puerto: por nombre y no por tipo | `test_the_port_is_the_building_of_type_naval_base` y 1 más |
| M12 | puerto: sin la guarda de «sin puerto» | `test_without_a_naval_base_there_is_nothing_to_compare` y 1 más |
| M13 | población: condición invertida | `test_a_bookmark_before_every_pops_folder_is_a_warning_on_its_date` y 9 más |
| M14 | población: la misma fecha no vale (`<`) | `test_a_folder_of_the_same_date_or_an_earlier_one_is_enough` y 7 más |
| M15 | población: exige la fecha exacta (`==`) | `test_a_folder_of_the_same_date_or_an_earlier_one_is_enough` y 1 más |
| M16 | cámara: condición invertida | `test_a_camera_right_of_the_map_is_a_warning_on_that_field` y 10 más |
| M17 | cámara: el borde ya es fuera (`<`) | `test_inside_and_on_the_border_are_fine` y 3 más |
| M18 | cámara: el cero ya es fuera | `test_inside_and_on_the_border_are_fine` y 1 más |
| M19 | cámara: ejes cruzados | `test_each_axis_has_its_own_limit` y 5 más |
| M20 | cámara: sin la guarda de «sin mapa» | `test_without_the_provinces_bitmap_the_rule_is_silent` |
| M21 | flagType: condición invertida | `test_a_flag_type_no_country_has_is_reported_on_its_line` y 10 más |
| M22 | flagType: distingue mayúsculas | `test_case_does_not_matter` |
| M23 | flagType: cualquier prefijo vale como TAG | `test_only_tag_flags_count` (caso añadido) |
| M24 | flagType: las subcarpetas de `gfx/flags` cuentan | `test_without_any_country_flag_the_rule_is_silent` (caso añadido) |
| M25 | flagType: sin la guarda de «sin banderas» | `test_without_any_country_flag_the_rule_is_silent` |
| M26 | flagType: TAG de cuatro letras | `test_only_tag_flags_count` |
| M27 | flagType: línea del bloque y no del campo | `test_a_flag_type_no_country_has_is_reported_on_its_line` y 1 más |
| M28 | cultura: da la primera y no las repetidas | `test_the_same_culture_in_two_groups` y 9 más |
| M29 | cultura: solo una repetida | `test_three_definitions_give_two_problems` |
| M30 | índice: todo `objectTypes` es actor | `test_only_the_animated_actors_of_object_types_are_catalogued` y 1 más |
| M31 | índice: actores de cualquier raíz | `test_only_the_animated_actors_of_object_types_are_catalogued` |
| M32 | índice: el buscador ofrece actores | `test_actors_are_not_offered_by_the_search_unless_asked` |
| M33 | textos: un actor da por usada una clave | `test_a_text_named_like_an_actor_is_still_an_orphan` |
| M34 | arreglo del puerto: baja de más | `test_it_changes_only_that_value_in_one_undoable_step` y 1 más |
| M35 | arreglo del puerto: no rechaza lo ya arreglado | `test_label_safety_and_refusals` |
| M36 | arreglo de la cámara: el negativo va al borde lejano | `test_negative_and_both_axes` |
| M37 | arreglo de la cámara: toca todos los bookmarks | `test_only_the_bookmark_of_the_problem_is_touched` |
| M38 | arreglo de la cámara: pierde el comentario de la línea | `test_only_the_coordinate_outside_moves_to_the_nearest_border` |
| M39 | arreglo del puerto: marcado como seguro | `test_label_safety_and_refusals` |
| M40 | explicador: cultura sin sus definiciones | `test_the_explanation_shows_both_definitions` |
| M41 | explicador de población: da veredicto a las carpetas posteriores | `test_the_texts_do_not_claim_which_folder_the_game_uses` |
| M42 | texto de población: afirma qué carpeta usa el juego | `test_the_texts_do_not_claim_which_folder_the_game_uses` |
| M43 | cámara: solo mira `cameraX` | `test_each_axis_has_its_own_limit` y 1 más |
| M44 | índice: el actor sin su tipo en los `attrs` | `test_only_the_animated_actors_of_object_types_are_catalogued` |
| M45 | explicador del puerto: sin la línea del edificio | `test_the_explanation_shows_the_unit_and_the_building` |
| M46 | explicador de la cámara: sin el BMP | `test_the_explanation_shows_the_camera_and_the_bitmap` |
| M47 | cultura: el problema en la primera definición | `test_the_same_culture_in_two_groups` y 1 más |
| M48 | arreglo de la cámara: toma el tamaño al revés | `test_negative_and_both_axes` y 1 más |
| M49 | población: solo cuenta la última carpeta | `test_a_folder_of_the_same_date_or_an_earlier_one_is_enough` y 7 más |

Tras la última pasada, `git diff` no contiene ningún mutante (el guion restaura los bytes originales
de cada archivo).

## 6. Límites y dudas

- **[verificar en juego]**: qué enseña el juego cuando falta el actor de una cultura gráfica; qué
  bandera sale si un país no tiene la de su `flagType`; con qué definición de una cultura repetida se
  queda; qué carpeta de `history/pops` carga para cada fecha; qué hace con una cámara fuera del mapa.
  Los textos lo dicen así.
- `sprite_missing` solo salta si **ninguna** cultura tiene el actor. Una unidad con actor en una sola
  cultura no se marca, igual que la mayoría de las de vanilla.
- `government_flagtype_unknown` no mira país por país: basta con que un país tenga esa bandera.
- `bookmark_without_pops` no exige una carpeta con la fecha exacta (vanilla no la tiene). Si el juego
  la exigiera para fechas nuevas, la regla se quedaría corta.
- La lista de problemas en vivo del formulario de una entidad (los validadores de esquema) no enseña
  estos seis: salen en F7 y en el panel de problemas, con la entidad y el campo, y desde ahí abren su
  editor.
- El esquema del gobierno declara `flagType` como una lista cerrada: un tipo de bandera propio del mod
  da además un `bad_type` de esquema aunque sus banderas existan. No se ha tocado.
- El minijuego de pruebas solo trae una bandera sin tipo, así que sus dos gobiernos con `flagType` dan
  `government_flagtype_unknown` heredado. No se ha cambiado el minijuego (otras pruebas cuentan sus
  archivos): `ExpectedCleanTests` lo declara entre los plantados.
- `locsync.orphans` no se ha tocado: si cuenta los nombres del índice como uso implícito, un actor
  podría dar por usada una clave con su mismo nombre en esa pantalla. La regla `loc_orphan` sí lo
  excluye.

## 7. Peticiones

1. **Interfaz**: pasar `ACTOR_KIND` a `KIND_ACTOR` con su etiqueta `kind.actor` en la paleta (ES/EN) y
   quitar `NOT_SEARCHED`, si se quiere que los actores salgan en Ctrl+K.
2. **Esquema del gobierno**: que `flagType` acepte los tipos que tienen bandera en la vista, y no solo
   la lista cerrada.
3. **Integrador**: pasar la batería completa con y sin corpus; esta etapa solo ha pasado las de sus
   módulos y las cuatro de reglas.
