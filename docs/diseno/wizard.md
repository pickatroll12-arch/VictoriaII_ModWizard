# Victoria II Mod Studio — Diseño del Wizard (iteraciones 2 a 10)

> **Qué es.** La guía de diseño para construir sobre la iteración 1 las 15 capacidades del objetivo ampliado y los requisitos originales. Sustituye a las partes «planificadas» de `ARCHITECTURE.md` (§2.2–2.4, §3 y §6).
>
> **De dónde sale.** Es la síntesis de tres propuestas independientes. La base es «flujos del modder» (navegación, asistentes, mapa, taller de mapas, interfaz). Se le injertan el motor de esquemas declarativos de «esquemas primero» y la persistencia de «integridad primero» (VFS con reglas de carga, guardado con diario, recuperación, línea base de validación). Todas las cifras se han comprobado sobre el corpus real: `vanilla` (AHD/HoD completo), `Plantilla Mod` y `ShagoMod/VSM`.
>
> **Convenciones.** Identificadores en inglés; docstrings y comentarios en español, concisos. Núcleo sin Qt (`vic2studio.core`); interfaz en `vic2studio.ui`. Todo texto visible pasa por `tr()` con paridad ES/EN. Escritura atómica con `.bak`, en cp1252.
>
> **[verificar en juego]** marca una regla del motor que los archivos no demuestran. El código la modela como opción o como aviso, nunca como suposición silenciosa, y entra en la lista de comprobación manual que el usuario recibe al final del proyecto (iteración 10, §24).

---

## 0. El diseño en una página

1. **Se trabaja por flujos del modder, no por carpetas.** Hay 7 salas (Proyecto · Mapa · Naciones · Guerra · Eventos · Interfaz · Textos), cada una con un índice de secciones, más Inicio («¿Qué quieres hacer?») y un buscador universal (Ctrl+K). Los archivos del juego solo aparecen en «Archivos afectados», en «Cambios pendientes» y en la pestaña «Código».
2. **El CST sin pérdidas es la única fuente de verdad.** Formularios, mapa, árbol de condiciones y lienzo de interfaz son vistas sobre `Block`/`Entry` (`core/clausewitz/nodes.py`) y `LocRow` (`core/csvloc/model.py`). Guardar sin cambios no escribe nada; editar un campo cambia solo esa línea. Las vistas guardan referencias (`RecordRef`), nunca nodos.
3. **Herencia vanilla + mod con una VFS de reglas de carga.** El juego base es intocable: `WriteGuard` compara rutas reales y solo admite el subárbol del mod y su `.mod`, aunque el mod viva dentro de `<juego>/mod/`. La copia al mod se hace al guardar, a la misma ruta y con la misma mayúscula. Los textos de vanilla se sobrescriben en `00_<P>_overrides.csv`, nunca copiando `text.csv`.
4. **Proyecto transaccional.** Cada acción es una transacción con nombre («Crear país XYZ») con deshacer y rehacer por instantáneas de texto. Guardar es una transacción multiarchivo con diario: todo o nada, con recuperación tras un corte. Además hay `.bak`, detección de cambios externos, bloqueo entre instancias y autoguardado de recuperación.
5. **Una entidad nueva cuesta un esquema, sus textos y una prueba.** El marco `core/schema` (tipos ricos, disposición en archivos, historia fechada, colocación, compañeros) genera la lista, el formulario, la validación, las claves de localización, la documentación y las pruebas. La sección aparece sola en su sala.
6. **Índice de símbolos y validación con línea base.** Los selectores, «dónde se usa», el renombrado, el buscador y la validación salen del índice, que es incremental, se guarda en caché por huella e incluye los cambios sin guardar. Lo que ya falla en vanilla se marca como heredado y se oculta.
7. **El guion se describe con datos.** Un catálogo JSON de condiciones, efectos y ámbitos, con tipos y frases ES/EN. El árbol AND/OR/NOT edita el CST y conserva como «crudo» lo que no conoce.
8. **Mapa en coordenadas del juego.** Ráster `uint16` (la fila de Pillow es la `y` del motor; solo la vista se voltea), modos por LUT, edición por clic y por brocha, y regiones con invariantes. El Taller de mapas genera un mapa al estilo de Azgaar's Fantasy Map Generator o lo importa desde bitmaps, calcula en un proceso trabajador, exporta todos los archivos coherentes en una transacción y audita las dependencias.
9. **El arte del juego solo se usa en tiempo de ejecución.** Las vistas previas (ventanas `.gui`, eventos, banderas, iconos de CB) leen la instalación del usuario. La estética de la aplicación sigue siendo 100 % procedural y el repositorio no contiene nada de Paradox.
10. **Pensado para 2 agentes.** Cada iteración empieza con un commit de contrato y reparte archivos disjuntos. Esquemas, salas, reglas y extractores se registran por descubrimiento, y los textos van en fragmentos JSON.

---

## 1. Contradicciones entre las propuestas y cómo se resuelven

| # | Tema | Qué decían | Decisión | Motivo |
|---|---|---|---|---|
| D1 | Navegación | 7 salas por flujos / 7 páginas con una «Reglas del juego» o «Datos del juego» genérica | 7 salas por flujos. Cada esquema declara `hall` y `section`, y su sección se genera sola | El modder busca «Guerra», no «Reglas». Se mantiene el coste cero de interfaz por entidad. |
| D2 | Capa intermedia | `services/` con QtCore / `services/` sin Qt / sin `services/` | Sin paquete `services/`. El estado vive en `core/project/` (Python puro: `Project`, `Workspace`) y el único puente con Qt es `ui/session.py` | Una capa menos, y todo el estado se prueba sin Qt. |
| D3 | Deshacer | Instantáneas de texto / comandos con mementos de los slots del CST | Instantáneas por documento y transacción (comprimidas); parches por caja envolvente para los rásteres; las vistas re-resuelven su `RecordRef` cuando cambia `version` | La ida y vuelta byte a byte hace exacto el deshacer por reparseo. Los mementos dependen de slots privados y de la trivia de los vecinos, y son frágiles. |
| D4 | Copias de seguridad | `.bak` junto al archivo / `backups/<txid>` en lugar de `.bak` | Se mantiene `.bak` (convención del proyecto) y el diario lo usa como copia de reversión. `originals/` guarda una sola vez el estado previo a la primera escritura del Studio. La exportación excluye `*.bak` y `.vic2studio/` | Respeta la convención, da el todo o nada y protege lo que el usuario tenía antes de usar el Studio. |
| D5 | Cuándo se copia de vanilla | Al editar / al guardar | Al guardar. Al editar se marca el documento y se avisa; si se deshace, no queda rastro | Leer nunca escribe (I4). |
| D6 | Textos de vanilla | `00_<P>_overrides.csv` / sustituir en el archivo de su categoría | Clave nueva → `00_<P>_<área>.csv`. Clave cuyo ganador está en el mod → se edita en su sitio. Clave cuyo ganador está en el juego → `00_<P>_overrides.csv` | Un solo lugar para las sobrescrituras, fácil de revisar y de deshacer. |
| D7 | Dónde va un TAG nuevo | Antes de `dynamic_tags` / en orden alfabético antes de `dynamic_tags` | Justo antes de `dynamic_tags`, delante del bloque de comentarios que lo precede | El corpus refuta el orden alfabético: vanilla no está ordenado y el usuario añadió sus 6 TAG al final (H11). |
| D8 | Dónde viven los esquemas | `core/schema/kinds` / `core/schemas` / `core/schema/entities` | Marco en `core/schema/`, declaraciones en `core/schemas/<kind>.py` y textos en `core/schemas/texts/` | Separa el marco, que es estable, de las declaraciones, que crecen. El núcleo no puede importar `vic2studio.i18n` porque este importa QtCore. |
| D9 | Efectos colaterales | `links` / `on_create` + `Recipe` / `companions` | `Companion` (`on_create`, `on_delete`, `on_rename`, `check`) para registros dependientes, y `Recipe` para flujos multiarchivo con parámetros declarados | Un solo concepto para «mantener lo que depende de esta entidad». |
| D10 | Validación | Validadores en el esquema / reglas globales por familia / `semantic.py` | Las dos cosas: validadores por esquema y reglas globales por familia en `core/validate/rules/`, con un único tipo `Problem` y línea base por huella | Las reglas locales viven con su entidad; las globales (mapa, ids) no tienen dueño único. |
| D11 | BMP y DDS | Pillow / códec BMP propio | Códec BMP propio con numpy (ida y vuelta byte a byte). DDS: lectura con Pillow y escritor propio sin comprimir (A8R8G8B8). TGA con Pillow | Exactitud byte a byte, y no depender de la versión de Pillow: `Pillow>=10` no garantiza escribir DXT. |
| D12 | Arte del juego | Recursos y BMFont del usuario / fuentes del sistema | Recursos y BMFont de la instalación del usuario en tiempo de ejecución, con alternativa procedural. Las capturas del repositorio usan siempre la alternativa (`--no-game-art`) | Fidelidad para el modder sin meter copyright en el repositorio. |
| D13 | Revisión antes de escribir | Siempre por «Cambios pendientes» / solo si hay copias, papelera o conflictos | Ctrl+S guarda. El diálogo de revisión solo aparece si hay copias desde el juego base, papelera, conflictos o errores. El panel «Cambios pendientes» está siempre a mano y los asistentes terminan en un «Plan de cambios» | Seguridad sin fricción. |
| D14 | Escribir en una fecha | Bloque de la fecha / bloque vigente | Política de §10.6: en la fecha de inicio, entrada sin fecha; si no, el último bloque fechado del intervalo (bookmark anterior, D]; si no hay, se crea `D = { }` en orden | Editar en 1861.7.1 reutiliza el bloque `1861.1.1` de vanilla. |
| D15 | Ids de evento | Rango por proyecto con valores por defecto distintos | `project.json → id_ranges.event`. Por defecto, el primer bloque libre de 10 000 ids a partir de 200 000 000, comprobado contra vanilla y el mod | Queda por encima del máximo de vanilla (111 011 928) y dentro de 32 bits. |
| D16 | Carpeta de proyecto | `<mod>/.vic2studio/` | `<mod>/.vic2studio/` para ajustes, diario, papelera, originales y recuperación; se crea en el primer guardado. El bloqueo y las cachés (índice, ráster) van a la carpeta de datos del usuario | El juego ignora carpetas desconocidas [verificar en juego]. Abrir un mod no escribe en él, y las cachés no inflan el mod. |
| D17 | Archivos con errores de sintaxis | Sin tratamiento / solo lectura estructural | Modo solo texto con diagnósticos y arreglo rápido («Añadir `}` al final») | Evita `SourceMismatchError` y ediciones imprevisibles en las decisiones rotas del usuario. |
| D18 | Hilos | Sin regla / CST vivo solo en el hilo de la interfaz | El CST vivo solo se toca en el hilo de la interfaz. Los hilos de fondo reciben bytes o instantáneas inmutables | Sin condiciones de carrera. |
| D19 | Plan | 8 iteraciones / 9 | 9 iteraciones (2–10): cimientos de integridad primero, motor de esquemas en la 4, mapa antes que países | El asistente de países necesita el índice y el mapa (territorio). |

---

## 2. Hechos del corpus que condicionan el diseño

Medidos con el parser actual sobre el corpus local (`VIC2_CORPUS`: vanilla, `Plantilla Mod` y `ShagoMod`). Los que afectan a pruebas tienen una prueba de corpus (§19.4).

| # | Hecho (ruta y dato) | Consecuencia |
|---|---|---|
| H1 | **Orientación.** `map/provinces.bmp` (5616×2160, 24 bits) leído con Pillow da la `y` del motor en la fila del array: el centroide de Berlín (549) cae en la fila 1675,6 y `positions.txt` da `y=1676`; Londres (300), fila 1661 frente a `y=1663`. Visto tal cual, el mapa sale con el norte abajo. | El ráster se guarda en coordenadas del juego y hay una sola función de conversión para la vista (`to_display_row`). Al importar imágenes con el norte arriba se voltean. Una prueba con un fixture asimétrico fija la orientación. |
| H2 | **Saltos solo CR.** 11 archivos (10 historias de `south america/` y `usa/`, más `map/region_sea.txt`). Fallo latente, ya corregido: el lexer terminaba los comentarios solo en `\n` (`_TRIVIA` y `_COMMENT_SCAN_RE`), así que `parse("a = 1 # c\rb = 2\r")` daba solo `a`. Además todas las líneas contaban como 1 y `detect_newline` devolvía `"\n"`. Ninguno de los 11 tiene comentarios; el fallo habría aparecido al añadir uno o con un mod en CR. | **Hecho en la iteración 1**, antes de cualquier edición (`#[^\r\n]*`, líneas por `\r\n\|\r\|\n`, `detect_newline` → `"\r"`): ahora da `a` y `b` en las líneas 1 y 2. Lo fijan las pruebas `LineBreakTests.test_cr_only_files` y `EncodingTests.test_cr_only_newlines`, y la ida y vuelta del corpus la vigila `test_clausewitz_corpus`; la iteración 2 solo comprueba la regresión. |
| H3 | **Saltos y codificación.** De 4 220 `.txt/.gui/.gfx`: 3 397 CRLF, 347 mixtos, 444 LF, 11 CR y 21 sin salto. Por codificación: 4 038 ASCII, 181 cp1252 y 1 UTF-8 (`history/units/1861/HAI_oob.txt`). | Los archivos nuevos se escriben en cp1252 con CRLF. Un archivo editado conserva su salto predominante. `non_game_encoding` entra en la línea base. |
| H4 | **`definition.csv`.** Cabecera `province;red;green;blue;x;x`, ids 1–3248, 56 filas sin id al final y la fila 1826 `1825;208;17;223.;Zouar;x`. El BMP tiene 3 275 colores: 27 sin id (8 834 px; el mayor, (1,222,200), ocupa 8 345). Todo id tiene píxeles y no hay colores repetidos. | Tabla `;` tolerante y sin pérdidas (`core/tablecsv.py`). `223.` se lee al estilo `atoi` y se conserva tal cual. Los colores sin id son un aviso heredado. |
| H5 | **`default.map`.** `max_provinces = 3249`. `sea_starts` tiene 546 valores y 545 distintos (2800 está dos veces): 2703–3248 **salvo 3246** (Jan Mayen, de tierra, añadida en HoD después de los ids de mar). Hay 2 703 provincias de tierra y 545 de mar. Nombra `definition.csv`, `provinces.bmp`, `positions.txt`, `terrain.bmp`, `rivers.bmp`, `terrain.txt`, `trees.txt`, `continent.txt`, `adjacencies.csv`, `region.txt`, `region_sea.txt` y `province_flag_sprites`; además trae `border_heights`, `terrain_sheet_heights`, `tree` y `border_cutoff`. | Los nombres de archivo se leen de `default.map`. «Primero tierra y después mar» es una convención del generador, no una invariante: el validador acepta 3246. |
| H6 | **Regiones y continentes.** 549 estados en `region.txt` (`PRU_549 = { 549 550 551 552 681 }`, `USA_1 = { 1 2 3 4 5 2599 2630 2631 }`). Cada una de las 2 703 provincias de tierra está en exactamente 1 estado y en 1 de los 6 continentes (europe, asia, africa, north_america, south_america, oceania). Ninguna de mar está en un estado ni en un continente. | Son reglas de validación y, además, precondiciones de los comandos de regiones. |
| H7 | **`climate.txt`** repite cada clave: la 1.ª aparición tiene los modificadores y la 2.ª la lista de provincias. `continent.txt` tiene `provinces = { }` más modificadores. | Disposición `PairedKeys`. En ese archivo está prohibido usar `Block.set(nombre)`. |
| H8 | **Texturas del mapa.** `map/terrain/colormap.dds` mide 1880×720, que **no** es exactamente 5616/3 = 1872. `colormap_water.dds` mide 936×360 (W/6×H/6). Las dos son DDS sin comprimir. | Un mapa nuevo del tamaño de vanilla usa esas mismas medidas; otros tamaños son [verificar en juego]. |
| H9 | **Historia de provincias.** 2 705 archivos en subcarpetas, con nombres irregulares (`3246  JanMayen.txt`, `1337  Prome.txt`). 1396 y 1397 están en `asia/` y en `indonesia/`: las dos copias de 1396 difieren y las de 1397 son idénticas. Bloques fechados (`1861.1.1 = { railroad = 3 }`), a veces dos con la misma fecha. | El id es el entero inicial del nombre. La copia al mod va a la misma ruta. `province_history_duplicate` es un error en el mod y un problema heredado en vanilla; qué copia carga el juego es [verificar en juego]. |
| H10 | **POPs.** `history/pops/1836.1.1/` y `1861.4.14/`, 179 archivos por fecha, agrupados por provincia (`549 = { aristocrats = { culture religion size } }`). La provincia 2482 aparece dos veces en `1861.4.14/Australia.txt`. | Índice (fecha, provincia) → lista de ubicaciones. Nunca se fusionan bloques en silencio. |
| H11 | **Registro de países.** `common/countries.txt` tiene `dynamic_tags  = yes` en la línea 265, precedido por el comentario `##HoD Dominions`, y detrás vienen D01–D50. En VSM, los 6 TAG del usuario (AGC…WRL) están detrás de JAN y antes de ese bloque de comentarios. No siguen un orden alfabético. | `RegisterTag` inserta justo antes de `dynamic_tags`. La entrada nueva se escribe delante de la trivia que ese token lleva antes, como hizo el usuario. `Block.append` convertiría el TAG en un dominio dinámico (`tag_after_dynamic_tags`). |
| H12 | **Partidos.** `party = { name ideology start_date end_date economic_policy trade_policy religious_policy citizenship_policy war_policy }` en `common/countries/*.txt`. **Los nombres de partido se comparten entre archivos**: AUS y KUK, los dominios D01–D50, y MAJ y WRL en VSM. | Un partido se identifica por (archivo de país, nombre). Regla: `ruling_party` debe estar en el archivo del propio TAG y su ideología debe estar permitida por el gobierno. |
| H13 | **Incoherencias de vanilla.** 13 partidos gobernantes con una ideología que su gobierno no admite (p. ej. ARG_conservative con `presidential_dictatorship`) y 50 `civilized` repetidos (D01–D50). | Línea base: heredados y ocultos. |
| H14 | **Errores reales en VSM.** `nationalvalue = nv_tradition`, que no existe, en GEL, MAJ, SOM y WRL. `SOM - Somalia.txt` tiene `ruling_party = SOM_socialist` con `absolute_monarchy`, que solo admite liberal, conservative y reactionary. SIL tiene historia, archivo de país, banderas y dueño en 682–685, pero no está en `countries.txt`. El partido de Somalia usa `social_policy`, que no existe en `issues.txt`. `absolute_monarchy` tiene `election = yes` sin `duration`. 2 decisiones (`somaliland_shago.txt`, `zulu_expancionshago.txt`) no cierran `political_decisions`. | Son casos de aceptación reales para la validación y los arreglos rápidos. |
| H15 | **VSM es una copia completa.** De 8 563 archivos, 8 462 son idénticos a vanilla, 29 difieren y 72 son nuevos. Incluye `localisation/text.csv` (3,6 MB) y `text.csv.bak`. Ese `text.csv` (igual en `Plantilla Mod`) tiene 3 429 filas que difieren de vanilla, casi todas porque los caracteres acentuados pasaron a `?` (`Capacité` → `Capacit?`). Como un CSV del mod con el mismo nombre sustituye al de vanilla, esos textos salen rotos en francés, alemán y español. | Se soportan igual los mods copia completa y los mínimos. `mod_shadow_identical` (info) ofrece una limpieza opcional. Regla nueva `loc_copy_degraded` (aviso) con el arreglo «Recuperar las filas de vanilla». El Studio nunca reescribe un archivo que no ha editado. |
| H16 | **Gobiernos.** 8 en `governments.txt`: `<ideología> = yes`, `election`, `duration`, `appoint_ruling_party` y `flagType` ∈ {communist, republic, fascist, monarchy}. `democracy` no lo lleva y usa `TAG.tga`. `rebel_types.txt` tiene 14 tablas `government = { <gob> = <gob destino> }`. | Compañero `MappingTable` sobre las 14 tablas. |
| H17 | **Casus belli.** `cb_types.txt` empieza con `peace_order = { … }` (32 valores, incluido `annex`, que no es un CB). Le siguen 31 CB con 49 claves distintas, 18 de ellas `po_*`. Localización `<cb>`, `<cb>_desc`, `<cb>_setup` y `<cb>_short`, más `NORMAL_<war_name>` y `AGRESSION_<war_name>` (errata original, compartidas). `sprite_index` es un fotograma de `GFX_diplo_wargoal_icons`. | Compañero `AppendToList(peace_order)`. `annex` es un problema heredado. El selector de icono muestra los fotogramas. |
| H18 | **Culturas y unidades.** `cultures.txt`: 34 grupos (`leader`, `unit`, `union`, `is_overseas`) que contienen 226 culturas como bloques hijos sin clave fija. `units/`: 21 archivos, uno por tipo (11 `type = land` y 10 `type = naval`); se activan con `activate_unit` en tecnologías e invenciones. | `Children` por exclusión y `Variant` por `type`, con dos secciones sobre el mismo esquema. |
| H19 | **Historia de países.** 271 archivos `history/countries/<TAG> - <Nombre>.txt`. Además de los campos fijos, la raíz mezcla tecnologías (150; `flintlock_rifles = 1`), invenciones (387) y reformas (`slavery = no_slavery`; 30 grupos de `issues.txt`, que con los 5 de partido suman 35), dentro y fuera de bloques fechados. `oob = "PRU_oob.txt"` y, en `1861.1.1`, `oob = "/1861/PRU_oob.txt"` (relativas a `history/units`). | Tipo `DynamicKeys` (claves sacadas del índice de símbolos). Resolución de rutas por tipo de campo. |
| H20 | **Guerras, diplomacia y bookmarks.** `history/wars/`: 5 archivos (`ACW.txt`, `Taiping Rebellion.txt`…) con `name` y bloques fechados (`add_attacker`, `add_defender`, `rem_*`, `war_goal = { casus_belli actor receiver [state_province_id] [country] }`). `history/diplomacy/`: 4 archivos: `Alliances.txt` (2 `alliance`, con valores entre comillas: `start_date="1836.1.1"`), `PuppetStates.txt` (30 `vassal` y 6 `substate`), `Unions.txt` (3 `union`, sin comillas) y `Guarantees.txt` (vacío). `bookmarks.txt`: 2 bloques `bookmark = { name = "GC_NAME" desc = "GC_DESC" date = 1836.1.1 cameraX = 2950 cameraY = 1550 }` (y 1861.7.1). `defines.lua`: `start_date = '1836.1.1'` y `end_date = '1935.12.31'`; VSM lo cambia a `'2300.1.1'`. | Historia en modo LOG para las guerras. `Block.set` ya conserva las comillas. Editor mínimo de `defines.lua` sin pérdidas. |
| H21 | **Eventos y decisiones.** 82 archivos con 1 064 eventos (882 `country_event` y 182 `province_event`), ids de 100 a 111 011 928. Imágenes: 286 TGA de 521×203. Decisiones: 29 archivos con 151 decisiones bajo `political_decisions`; 150 no llevan `picture` y, de ellas, 146 tienen `gfx/pictures/decisions/<id>.dds` (95×95). | La imagen de una decisión vale por defecto su id. El aviso de imagen ausente tiene 4 casos heredados. |
| H22 | **Banderas.** 1 362 TGA: 1 345 de 93×64 (1 030 de 32 bits y 315 de 24 bits), 12 de 64×64 y 5 atlas `flagfiles` de 2048×1024. 1 038 usan RLE y 1 357 tienen el origen abajo a la izquierda. | El generador escribe TGA de 32 bits, 93×64, con origen abajo a la izquierda, y las relee con Pillow para verificar. |
| H23 | **Interfaz.** 59 `.gui` y 66 `.gfx`. Las claves no respetan mayúsculas (`Orientation`/`orientation`, `texturefile`/`textureFile`) y hay erratas (`UPPERL_LEFT`). 434 referencias a texturas existen con otra extensión (`.tga`↔`.dds`) y 27 no existen. En `gfx/interface/` hay 1 228 DDS: 1 003 sin comprimir, 201 DXT3, 19 DXT5 y 5 DXT1. | Claves de GUI sin distinguir mayúsculas, resolución de texturas con extensión alternativa y línea base. Los sprites nuevos se importan como DDS sin comprimir. |
| H24 | **El mod vive dentro del juego** (`<juego>/mod/VSM` y `<juego>/mod/VSM.mod`). | La protección no puede ser «nada dentro de `<juego>`»: es «solo el subárbol del mod y su descriptor», comparando rutas reales. |
| H25 | **Coste.** Parsear todo vanilla lleva unos 3 s (POPs 1,2 s, `map/*.txt` 0,6 s), y mantener todos sus CST en memoria cuesta unos 357 MB. | Índice compacto en caché por huella. Los CST se cargan bajo demanda, con LRU. |

---

## 3. Principios e invariantes

Cada invariante tiene pruebas (§19).

- **I1. Solo el mod.** Los archivos del proyecto solo se escriben en `<mod>/` y en su descriptor `<juego>/mod/<carpeta>.mod`. Fuera de ahí solo se escribe en las carpetas de datos y caché de la aplicación (bloqueo y cachés), nunca en el juego base ni en otros mods.
- **I2. Todo o nada.** Un guardado de N archivos deja todos en el estado anterior o todos en el nuevo, aunque el proceso muera.
- **I3. Sin pérdidas.** Lo que no se edita se conserva byte a byte: CST, CSV, `definition.csv`, BMP y Lua.
- **I4. Leer no escribe.** Abrir, explorar, indexar o validar no escribe nada en el mod; guardar sin cambios tampoco. Un archivo del juego base solo se copia al mod si cambió.
- **I5. Todo es reversible.** Toda modificación entra en la pila de deshacer, y los asistentes se deshacen en un paso.
- **I6. Nada desaparece.** Las claves que el esquema no conoce se conservan y se muestran en «Otros campos». Borrar un archivo lo manda a `.vic2studio/trash/`.
- **I7. Vista efectiva.** El editor muestra lo que cargaría el juego, cambios sin guardar incluidos.
- **I8. No se pierde trabajo.** Autoguardado de recuperación, `.bak` y originales prístinos.
- **I9. Errores antes del disco.** Codificación, verificación por reparseo, conflictos externos, nombres inválidos en Windows y longitud de ruta se comprueban antes de tocar el disco.
- **I10. Validar no bloquea guardar.** Solo bloquean los errores de seguridad de escritura (I9). Los de validación avisan.
- **I11. Lo heredado no cuenta.** Un problema que ya tiene vanilla se marca como heredado y no se atribuye al mod.
- **I12. Un CST vivo no cambia de hilo.** Los hilos de fondo reciben bytes, texto o instantáneas inmutables.

Principios de producto:

- **P1. Flujos antes que archivos.** Cada asistente termina con un plan de cambios legible (archivo · acción · resumen).
- **P2. Declarar antes que programar.** Esquemas, catálogos JSON y especificaciones de sección.
- **P3. Errores en el idioma del modder.** Mensajes ES/EN concretos y, cuando se puede, un arreglo de un clic.
- **P4. Modo sencillo por defecto.** Los campos `advanced` se ocultan hasta pasar a modo avanzado. Las etiquetas muestran el nombre técnico: «Dueño (owner)».

---

## 4. Arquitectura por capas

```text
ui (PySide6) ──► ui/session.py (único puente Qt: señales, TaskRunner, idioma, fecha de trabajo)
                      │
                      ▼
core (Python puro, sin Qt)
  project/   Project, Workspace, deshacer, guardado con diario, recuperación      ← estado
  vfs/       capas juego/dependencias/mod, reglas de carga, WriteGuard
  index/     índice de símbolos (hechos por archivo, caché por huella)
  schema/ + schemas/   marco declarativo + declaraciones (una por tipo de entidad)
  validate/  reglas, línea base, arreglos rápidos
  locsync.py, script/, map/, mapforge/, gfx/, gui/, domain/
  clausewitz/ csvloc/ encoding.py fileio.py modfile.py modcheck.py             ← iteración 1
```

Reglas de dependencia (las comprueban pruebas de arquitectura):

- `vic2studio.core` y todos sus subpaquetes se importan sin PySide6; la prueba de subproceso actual se amplía.
- **Quién escribe en disco.** Las primitivas de escritura cruda (`open(..., "w"/"wb"/"a"/"x")`, `Path.write_*`, `os.replace/rename/remove/unlink`, `shutil.copy*/move/rmtree`, `tempfile.mkstemp`) solo aparecen en `core/fileio.py`. **Dentro del mod** solo escribe `core/project/journal.py` (guardado, papelera, `originals/` y autoguardado de `recovery/`), siempre después de `WriteGuard.check`. **Fuera del mod** escriben, a través de `fileio` y con rutas de `core/appdirs.py`, el bloqueo (`core/project/lock.py`) y las cachés (`core/index/cache.py`, `core/map/cache.py`). `tests/test_arch_writes.py` lo comprueba con un recorrido AST de `src/`: ninguna primitiva cruda fuera de `fileio.py`, y las funciones de escritura (las de `fileio` y sus envoltorios `serializer.write_file` y `csvloc.write_csv_file`) solo se llaman desde esos módulos y desde los propios envoltorios. Las excepciones se declaran y justifican en la propia prueba: `ui/theme.py` (glifos PNG en una carpeta temporal del proceso), las CLI (`core/csvloc/cli.py`, `core/schema/__main__.py`), que escriben donde indica el usuario, y `settings.py` (QSettings, sin primitivas). `tools/` queda fuera de `src/`.
- Ningún widget abre archivos: todo pasa por `Session` → `Project`.
- **Trabajos largos.** Toda función del núcleo que pueda tardar acepta `progress=` y `cancelled=` y lanza `core.cancel.Cancelled`. El contrato ya está en el repositorio (`core/cancel.py`: `CancelCheck`, `Cancelled`, `raise_if_cancelled`), y la interfaz les pasa `TaskContext.cancelled`.
- Los textos del núcleo (etiquetas de esquema, mensajes de validación, catálogo de guion) están en JSON dentro de `core` y los carga `core/texts.py` sin Qt; `i18n.Translator` los fusiona con sus catálogos.

### 4.1 Árbol de módulos

```text
src/vic2studio/
├── core/
│   ├── encoding.py            EXISTE  detect_newline ya reconoce "\r" (hecho en la iteración 1)
│   ├── cancel.py              EXISTE  CancelCheck, Cancelled y raise_if_cancelled (cancelación cooperativa)
│   ├── fileio.py              CAMBIA  stage_bytes, commit_staged, fsync_dir (atomic_write_bytes encima, misma firma)
│   ├── appdirs.py             NUEVO   cache_dir(), data_dir() sin Qt (VIC2STUDIO_CACHE_DIR / VIC2STUDIO_DATA_DIR)
│   ├── texts.py               NUEVO   load_texts(lang) y text(key, lang, **fmt) para los JSON del núcleo
│   ├── lua_defines.py         NUEVO   defines.lua sin pérdidas (get/set de `CLAVE = valor,`)
│   ├── tablecsv.py            NUEVO   tablas ';' sin pérdidas (definition.csv, adjacencies.csv)
│   ├── modfile.py             CAMBIA  DescriptorSpec, render_descriptor, descriptor_problems, create_mod_skeleton
│   ├── modcheck.py            CAMBIA  Issue(+entity, +fixes) compatible; check_mod pasa a ser la familia «syntax»
│   ├── clausewitz/            CAMBIA  serializer (render_checked); lexer (CR) y nodes (insert_before) ya están (iteración 1, §21)
│   ├── csvloc/                CAMBIA  render_csv_checked, LocalisationDB.from_entries
│   ├── vfs/        paths.py model.py rules.py guard.py vfs.py
│   ├── project/    model.py documents.py codecs.py workspace.py undo.py journal.py recovery.py lock.py
│   │               settings.py diffing.py project.py
│   ├── index/      model.py cache.py builder.py index.py extractors/*.py
│   ├── locsync.py
│   ├── rules/      game.py (GameRules) ids.py names.py colors.py
│   ├── schema/     types.py fields.py entity.py layouts.py record.py history.py placement.py companions.py
│   │               recipes.py validate.py texts.py docgen.py registry.py __main__.py
│   ├── schemas/    <kind>.py (una declaración por familia) · texts/<kind>.es.json · texts/<kind>.en.json
│   ├── validate/   model.py registry.py context.py baseline.py fixes.py rules/*.py (también rules/mapforge.py)
│   │               texts/issues.{es,en}.json texts/mapforge.{es,en}.json
│   ├── script/     catalog.py tree.py scopes.py phrases.py mtth.py idalloc.py data/{triggers,effects,scopes}.json
│   ├── domain/     province.py pops.py country.py tags.py
│   ├── map/        bmp.py definition.py raster.py cache.py facts.py modes.py borders.py geometry.py
│   │               adjacency.py positions.py groups.py coherence.py
│   ├── mapforge/   params.py world.py pipeline.py worker.py edits.py project.py install.py graph.py relief.py
│   │               climate.py hydro.py biomes.py partition.py rasterize.py reconcile.py textures.py names.py
│   │               society.py economy.py validate.py export.py audit.py overlay.py paint.py
│   │               steps/*.py imports/{bitmaps,heightmap,fmg_template,fmg_json}.py
│   │               data/{templates,name_bases,biome_table}.py   (§18.7)
│   ├── gfx/        flags.py images.py dds.py
│   └── gui/        gfxdb.py guimodel.py layout.py bmfont.py textures.py
├── i18n/           __init__.py (fusiona i18n/<lang>/*.json + textos del núcleo) es.json en.json es/*.json en/*.json
└── ui/
    ├── session.py  main_window.py
    ├── shell/      hall.py section_rail.py command_palette.py pending_changes.py problems_dock.py history_dock.py
    ├── halls/      registry.py project/ map/ nations/ war/ events/ interface/ localisation/
    ├── dialogs/    save_review.py conflict.py recovery.py new_mod.py rename.py
    ├── forms/      builder.py editors.py refpicker.py repeated.py dynamic.py locfield.py scriptfield.py states.py
    ├── entity/     browser.py editor_page.py usages.py
    ├── pickers/    symbol_picker.py tag_picker.py province_picker.py culture_picker.py tech_tree.py
    │               issue_picker.py date_edit.py color_field.py goods_field.py name_list.py sprite_frame.py
    ├── map/        canvas.py layers.py modes_bar.py legend.py province_panel.py pops_editor.py brush.py
    │               region_tool.py straits_tool.py timeline.py
    ├── countries/  wizard/ sheet/ flag_studio.py upper_house.py oob_editor.py
    ├── script/     trigger_builder.py effect_builder.py catalog_picker.py mtth_editor.py option_cards.py
    │               event_preview.py decision_preview.py picture_picker.py phrase_view.py
    ├── interface/  gui_canvas.py gui_tree.py sprite_browser.py import_dialog.py picture_manager.py
    ├── mapforge/   wizard.py preview.py brushes.py province_tools.py entity_tables.py import_panel.py
    │               review.py audit_view.py flag_gallery.py worker_client.py steps/*.py
    ├── widgets/    (actuales) + icons_extra/<sala>.py + layer_badge.py
    └── viewers/    (actuales; ClausewitzViewer pasa a ser la pestaña «Código»)
```

En la raíz del repositorio, `THIRD_PARTY_NOTICES.md` recoge el texto MIT de Azgaar's Fantasy Map Generator para los módulos portados del taller (§18.13).

`pyproject.toml` amplía `package-data` con `i18n/*/*.json`, `core/schemas/texts/*.json`, `core/validate/texts/*.json` y `core/script/data/*.json`.

---

## 5. VFS: herencia vanilla + mod (`core/vfs`)

### 5.1 API

```python
# core/vfs/paths.py
class VPath(str):
    """Ruta relativa normalizada: '/', sin '/' inicial, sin '.', '..' ni unidad; conserva las mayúsculas."""
    @classmethod
    def of(cls, raw: str) -> "VPath": ...         # '\\' → '/', colapsa '//', rechaza '..' (InvalidPathError)
    @property
    def key(self) -> str: ...                     # upper(): comparación y orden estilo Windows (= load_order_key)

WINDOWS_DEVICES: frozenset[str]                   # CON PRN AUX NUL COM1-9 LPT1-9
def windows_name_problems(name: str) -> list[str] # dispositivo (también "CON.tga"), <>:"|?*, punto o espacio final
def long_path_problem(path: Path) -> str | None   # > 240 caracteres: aviso por MAX_PATH

# core/vfs/model.py
class LayerKind(Enum): GAME = "game"; DEPENDENCY = "dependency"; MOD = "mod"
@dataclass(frozen=True)
class Layer: kind: LayerKind; root: Path; label: str
@dataclass(frozen=True)
class Fingerprint: size: int; mtime_ns: int; sha256: str | None = None   # sha perezoso
@dataclass(frozen=True)
class FileEntry: rel: VPath; layer: Layer; path: Path; fingerprint: Fingerprint

# core/vfs/guard.py
class WriteOutsideModError(PermissionError): ...
class WriteGuard:
    def __init__(self, mod_root: Path, *, extra_files: Sequence[Path] = (),
                 extra_roots: Sequence[Path] = ()) -> None
    def check(self, target: Path) -> Path
        """realpath(target) si está bajo realpath(mod_root), es uno de extra_files (el .mod) o está bajo
        extra_roots (la carpeta de proyecto cuando el mod es de solo lectura, §5.4); si no, o si
        atraviesa un enlace que sale de esas raíces, lanza WriteOutsideModError."""

# core/vfs/vfs.py
class VirtualFS:
    def __init__(self, game_root: Path | None, mod_root: Path, *, descriptor: Path | None = None,
                 replace_paths: Sequence[str] = (), replace_recursive: bool = True,
                 dependencies: Sequence[Path] = ()) -> None
    @classmethod
    def from_descriptor(cls, game_root: Path, descriptor: ModDescriptor) -> "VirtualFS"
    guard: WriteGuard
    def scan(self, *, progress=None, cancelled=None) -> None        # os.scandir de las capas; no lee contenidos
    def resolve(self, rel: str | VPath) -> FileEntry | None          # ganador efectivo
    def stack(self, rel: str | VPath) -> list[FileEntry]             # todas las capas, ganador primero
    def list(self, folder: str, pattern: str = "*.txt", *, recursive: bool | None = None) -> list[FileEntry]
    def hidden_by_replace_path(self, entry: FileEntry) -> bool
    def mod_target(self, rel: str | VPath) -> Path   # destino en el mod; reutiliza la mayúscula de carpetas existentes
    def read_bytes(self, rel_or_entry) -> bytes
    def same_as_game(self, rel: str | VPath) -> bool                 # mods copia completa
    def snapshot(self) -> "VfsSnapshot"                              # inmutable: apto para hilos (I12)
    def refresh(self, rels: Iterable[VPath] | None = None) -> set[VPath]   # rutas cuya huella cambió
    def case_collisions(self) -> list[tuple[FileEntry, FileEntry]]
```

`evaluate_game`, `evaluate_mod`, `inspect_folder`, `same_folder` y `_is_under` de `ui/pages/project_page.py` ya son Python puro: se mudan a `core/vfs/guard.py` y la página los importa desde allí.

### 5.2 Reglas de carga (`core/vfs/rules.py`)

```python
class LoadMode(Enum):
    WHOLE_FILE      # un archivo; si el mod lo tiene, sustituye entero al del juego
    UNION_BY_PATH   # se cargan todos; el mod sustituye archivo a archivo por ruta
    KEYED_UNION     # UNION_BY_PATH + clave en el nombre (TAG o id); dos rutas con la misma clave = conflicto
    REFERENCED      # solo se carga si otro archivo lo nombra (countries/*.txt, oob, texturefile)
    LOCALISATION    # *.csv por nombre + orden alfabético + gana la primera clave (csvloc/db.py)
    MAP_BUNDLE      # nombres leídos de map/default.map; coherencia entre ellos
    ASSET           # binarios referenciados (gfx/**): resolución sin mayúsculas y con extensión alternativa

@dataclass(frozen=True)
class LoadRule:
    pattern: str; mode: LoadMode; doc_kind: "DocKind"; recursive: bool = False
    key_of: Callable[[VPath], str | None] | None = None   # p. ej. entero inicial del nombre
    new_file: str | None = None                           # plantilla de archivo nuevo del mod
    verified: bool = True                                  # False = [verificar en juego]

LOAD_RULES: tuple[LoadRule, ...]
def rule_for(rel: VPath) -> LoadRule
```

| Patrón | Modo | Consecuencia en el editor |
|---|---|---|
| `common/*.txt`, `common/defines.lua` | WHOLE_FILE | Editar una entrada copia el archivo entero al mod (aviso previo: «Se copiará common/cb_types.txt completo, 31 CB»). |
| `common/countries/*.txt` | REFERENCED (desde `countries.txt`) | País nuevo = archivo nuevo. `country_file_missing` si la referencia falla. |
| `history/countries/*.txt` | KEYED_UNION (TAG = 3 primeros caracteres) | Dos archivos con el mismo TAG = `country_history_duplicate`. |
| `history/provinces/**/*.txt` | KEYED_UNION recursivo (entero inicial) | La copia va a la misma ruta (H9). |
| `history/pops/<fecha>/*.txt` | UNION_BY_PATH | Se edita el bloque concreto; se copia el archivo de zona entero. Si se suman los bloques repetidos es [verificar en juego]. |
| `history/units/**/*.txt` | REFERENCED (`oob`) | `oob_file_missing`. |
| `history/wars/*.txt`, `history/diplomacy/*.txt` | UNION_BY_PATH | Guerra nueva = archivo nuevo. |
| `events/*.txt`, `decisions/*.txt`, `units/*.txt`, `news/*.txt` | UNION_BY_PATH | Editar una entidad de vanilla copia el **archivo entero a la misma ruta**: extraerla a otro archivo duplicaría su id. |
| `technologies/*.txt`, `inventions/*.txt` | REFERENCED (`technology.txt → folders`) [verificar en juego] | Activar una unidad copia el archivo de tecnología. |
| `poptypes/*.txt` | UNION_BY_PATH | Solo lectura en esta versión. |
| `interface/*.gfx` | UNION_BY_PATH [verificar en juego] | Sprites nuevos en `interface/<p>_studio.gfx`. |
| `interface/*.gui` | WHOLE_FILE por nombre | Editar copia el `.gui` entero. |
| `localisation/*.csv` | LOCALISATION | §8. Nunca se copia `text.csv`. |
| `map/default.map` y lo que nombra, `map/climate.txt` | MAP_BUNDLE | Invariantes cruzadas (§16.6). `map/cache` del mod va a la papelera al cambiar el mapa. |
| `gfx/**` | ASSET | Banderas por TAG, `gfx/pictures/{events,decisions}`, texturas. |

### 5.3 `replace_path`

`VirtualFS(..., replace_paths=..., replace_recursive=True)` oculta los archivos del juego bajo esas rutas: siguen accesibles con `stack()` para comparar, pero nunca se resuelven. Si afecta a las subcarpetas es [verificar en juego]; la opción es explícita y las pruebas cubren los dos valores. **No oculta los archivos del propio mod:** los que el mod tenga bajo una ruta reemplazada se siguen cargando (el taller los manda a la papelera; regla `replace_path_mod_files_remain`, §18.11). Reglas asociadas: `replace_path_empty` (error: el mod deja vacía una carpeta reemplazada; con `history/provinces` el juego se quedaría sin provincias; es info cuando la carpeta se vació de forma intencionada y el taller la registró, como `history/wars` en «Solo mapa», §18.8) y `replace_path_hides_referenced` (error: p. ej. se reemplaza `history/units` y las historias siguen apuntando a OOB de vanilla).

### 5.4 Carpeta de proyecto `<mod>/.vic2studio/`

Se crea en el primer guardado. El juego solo recorre sus carpetas conocidas [verificar en juego] y la exportación la excluye.

```text
.vic2studio/
  project.json          {"format": 1, "prefix": "VSM", "languages": ["en", "es"], "id_ranges": {"event": [200000000, 200009999]},
                         "working_date": "1836.1.1", "mode": "simple", "backup_bak": true}
  journal/<txid>.json   diario del guardado en curso (§6.5)
  originals/<rel>       estado de un archivo del mod antes de la primera escritura del Studio (nunca se sobrescribe)
  trash/<txid>/<rel>    «borrados»: nada se elimina de verdad
  recovery/<sesión>/    autoguardado de documentos sucios
  mapforge/<nombre>/    proyecto del Taller de mapas (§18.7): project.json, entities.json, edits.jsonl,
                        cells.npz e imports/
```

El bloqueo entre instancias (`<data_dir>/locks/<sha1(realpath(mod))>.lock`, con pid, host y hora) y las cachés (`<cache_dir>/index/…`, `<cache_dir>/raster/…` y, para el taller, el perfil de la instalación y el ráster final en `<cache_dir>/mapforge/…`) viven fuera del mod. Si el mod es de solo lectura, `.vic2studio/` pasa a `<data_dir>/projects/<sha1>/`.

---

## 6. Proyecto: documentos, transacciones, deshacer y guardado (`core/project`)

### 6.1 Documentos

```python
class DocKind(Enum): CLAUSEWITZ; LOCALISATION; TABLE; LUA; BMP; IMAGE; BINARY

class DocCodec(Protocol):                          # core/project/codecs.py
    kind: DocKind
    def load(self, data: bytes, rel: VPath) -> tuple[object, list]   # modelo + diagnósticos
    def render(self, model) -> bytes               # comprobado: verificación + codificación; lanza antes del disco
    def snapshot(self, model) -> bytes             # para deshacer, hilos e índice

@dataclass
class DocHandle:
    rel: VPath; kind: DocKind; model: object
    origin: FileEntry | None                       # capa de origen; None = nuevo
    base: Fingerprint | None                       # huella al leer (cambios externos)
    version: int = 0; saved_version: int = 0
    diagnostics: list = field(default_factory=list)
    read_only_reason: str | None = None            # "parse_errors" | "binary" | "locked" | None
    deleted: bool = False
    @property
    def dirty(self) -> bool
    @property
    def copies_from_game(self) -> bool             # origen en la capa del juego y sucio
```

| Códec | Base | Notas |
|---|---|---|
| CLAUSEWITZ | `parse`, `to_source`, `serializer.render_checked` | `render_checked` se extrae de `write_file(verify=True)` sin cambiar su comportamiento. |
| LOCALISATION | `csvloc`, `render_csv_checked` | — |
| TABLE | `core/tablecsv.py` | `definition.csv`, `adjacencies.csv`: filas crudas; solo se regeneran las editadas. |
| LUA | `core/lua_defines.py` | Sustituye solo el token del valor (`end_date = '2300.1.1',`). |
| BMP | `core/map/bmp.py` | 24 bits y 8 bits con paleta; `write(read(b)) == b`. |
| IMAGE | Pillow (lectura), `core/gfx/dds.py` y TGA (escritura) | Solo se escriben archivos nuevos o reemplazados; se releen para verificar. |

**Documentos con errores de sintaxis.** Se abren con `read_only_reason="parse_errors"`: los formularios se desactivan para ese archivo y queda el editor de texto con diagnósticos. Hay un arreglo rápido «Añadir `}` al final» para `unclosed_block`, guiado por la pista `suspicious_close_brace`. Tras corregir se vuelve a parsear y se habilita la edición estructural.

### 6.2 Workspace

```python
class Workspace:                                   # Python puro; un solo hilo (assert, I12)
    def __init__(self, vfs: VirtualFS, *, settings: "ProjectSettings", lru_bytes: int = 300 * 2**20) -> None
    def open(self, rel, *, kind: DocKind | None = None, create: bool = False) -> DocHandle   # instancia única por rel.key
    def peek(self, rel) -> DocHandle | None
    @contextmanager
    def transaction(self, label: str, *, merge_key: str | None = None, **fmt) -> Iterator["Txn"]
    def touch(self, handle: DocHandle) -> None     # antes de mutar: instantánea (una vez por transacción) y version += 1
    def replace_model(self, handle: DocHandle, model: object) -> None    # edición de texto libre y recargas
    def create(self, rel, kind: DocKind, model: object) -> DocHandle
    def delete(self, rel) -> None                  # lápida → papelera al guardar
    def undo(self) -> "UndoStep | None"
    def redo(self) -> "UndoStep | None"
    def dirty(self) -> list[DocHandle]
    def changeset(self) -> "ChangeSet"             # PlannedWrite por documento: CREATE | MODIFY | COPY_FROM_GAME | TRASH, con diff
    def save(self, rels: Iterable[VPath] | None = None) -> "SaveReport"
    def revert(self, rel) -> None                  # vuelve al disco; también se deshace
    def check_external_changes(self) -> list["ExternalChange"]   # al recuperar el foco y antes de guardar
    def write_recovery(self) -> None               # autoguardado (cada 60 s y cada 20 transacciones)
    def subscribe(self, fn: Callable[["WorkspaceEvent"], None]) -> Callable[[], None]
```

- Los documentos limpios que no referencia la pila de deshacer se pueden expulsar (LRU). Los sucios y los referenciados quedan fijados.
- Varias vistas (mapa, ficha de provincia, pestaña «Código») comparten el mismo `DocHandle` y escuchan `DocChanged(rel, version)` y `DocReplaced(rel)`.
- Las transacciones anidadas se funden en la exterior. Si una lanza una excepción, sus documentos vuelven a la instantánea y no se apila nada.

### 6.3 Deshacer por instantáneas (`undo.py`)

```python
@dataclass
class Snapshot:
    rel: VPath
    before: bytes | None        # snapshot() comprimido con zlib; None = no existía
    after: bytes | None         # se rellena al cerrar la transacción
    before_path: Path | None = None   # instantáneas de más de 8 MB y archivos movidos a la papelera: en disco

@dataclass
class RasterPatch:              # BMP: solo la caja envolvente, no la imagen
    rel: VPath; y0: int; x0: int; before: np.ndarray; after: np.ndarray

@dataclass
class UndoStep:
    label: str                  # clave i18n con formato ("undo.create_country", tag="XYZ")
    snapshots: list[Snapshot]
    patches: list[RasterPatch]
    merge_key: str | None       # teclear en el mismo campo en menos de 1 s se funde en un paso

class UndoStack:
    def __init__(self, *, limit: int = 500, max_bytes: int = 256 * 2**20) -> None
    def push(self, step: UndoStep) -> None
    def undo(self) -> UndoStep | None
    def redo(self) -> UndoStep | None
    def labels(self) -> list[str]   # panel «Historial»
```

- Deshacer sustituye el modelo del documento por `load(before)`: es exacto gracias a la ida y vuelta byte a byte, y no obliga a programar la inversa de cada mutación.
- Hay una sola pila global: «Crear país» toca unos 10 archivos y se deshace de una vez.
- «Sucio» se calcula por documento comparando `version` con `saved_version`: deshacer hasta el punto guardado deja el documento limpio. Se puede deshacer después de guardar; el documento vuelve a estar sucio.
- **Contrato con la interfaz.** La interfaz guarda `RecordRef`, nunca `Record`, `Block` ni `Entry`, y re-resuelve la referencia cuando cambia `version`.

### 6.4 Ajustes y fachada del proyecto

```python
@dataclass
class ProjectSettings:                              # <mod>/.vic2studio/project.json
    prefix: str                                     # por defecto la carpeta del mod en mayúsculas: "VSM", "DAM"
    languages: tuple[str, ...] = ("en", "es")       # columnas que rellenan los editores
    copy_en_to: tuple[str, ...] = ()                # p. ej. ("fr", "de"): el juego también muestra FR/DE
    id_ranges: dict[str, tuple[int, int]] = ...     # "event": primer bloque libre de 10 000 desde 200 000 000
    working_date: ClausewitzDate = ClausewitzDate(1836, 1, 1)
    mode: str = "simple"                            # "simple" | "advanced"
    backup_bak: bool = True

class Project:                                      # core/project/project.py
    @classmethod
    def open(cls, game_root: Path, mod_root: Path, *, descriptor: Path | None = None,
             progress=None, cancelled=None) -> "Project"
    vfs: VirtualFS; ws: Workspace; settings: ProjectSettings; rules: "GameRules"
    index: "SymbolIndex"; loc: "LocSync"; entities: "Entities"; validator: "Validator"
    def edit(self, label: str, *, merge_key: str | None = None, **fmt) -> ContextManager["Txn"]
    def save(self, rels=None) -> SaveReport
    def close(self) -> None
```

```python
class Session(QObject):                             # ui/session.py: único puente con Qt
    projectOpened = Signal(object); projectClosed = Signal()
    documentsChanged = Signal(object)               # set[VPath]
    symbolsChanged = Signal(object)                 # set[str] de tipos
    dirtyChanged = Signal(int)
    problemsChanged = Signal()
    workingDateChanged = Signal(object)             # ClausewitzDate
    def open_project(self, game: Path, mod: Path) -> None   # en segundo plano: escaneo, índice, línea base
    def edit(self, label: str, **fmt) -> ContextManager     # Project.edit + señales al cerrar
    def save(self) -> None; def undo(self) -> None; def redo(self) -> None
    project: Project | None
    working_date: ClausewitzDate
```

### 6.5 Guardado multiarchivo con diario (`journal.py`, `recovery.py`)

```python
class WriteAction(Enum): CREATE; MODIFY; COPY_FROM_GAME; TRASH
@dataclass(frozen=True)
class PlannedWrite:
    rel: VPath; target: Path; action: WriteAction; data: bytes | None
    expected: Fingerprint | None    # huella esperada del destino (conflictos externos)
    diff: str                       # difflib.unified_diff para «Cambios pendientes»

class SaveTransaction:
    def __init__(self, guard: WriteGuard, journal_dir: Path, *, label: str, backup_bak: bool = True) -> None
    def add(self, write: PlannedWrite) -> None
    def prepare(self) -> list["SaveProblem"]   # guard, nombres de Windows, longitud, conflicto de huella, espacio
    def commit(self) -> "SaveResult"

def pending_journals(journal_dir: Path) -> list["JournalState"]
def recover(journal_dir: Path, guard: WriteGuard, txid: str, *, prefer: str = "auto") -> "RecoveryResult"
```

Secuencia:

0. **Renderizar** en memoria todos los documentos sucios con `render_checked`. Aquí saltan `UnencodableTextError` (con línea y columna) y `SourceMismatchError`. Todavía no se ha tocado el disco.
1. **Preparar.** Se escribe cada temporal `.<nombre>.<txid>.tmp` en su carpeta de destino, con `fsync`. Después se escribe el diario `journal/<txid>.json` con `state="prepared"` y, por archivo, `rel, target, temp, action, before_sha256 | null, after_sha256, bak`. Luego `fsync` del diario y de su carpeta.
2. **Copias.** Cada destino que ya existe se copia a `<destino>.bak` (convención) y, la primera vez, a `originals/<rel>`. El diario pasa a `state="backed_up"`.
3. **Confirmar.** `os.replace(temp, destino)` en orden. TRASH mueve a `trash/<txid>/`. Ante un `PermissionError` (antivirus u otro programa con el archivo abierto en Windows) se reintenta 3 veces cada 100 ms; si sigue fallando, se revierte con las `.bak` y se borran los archivos creados (a la papelera). Al terminar, `state="committed"` y `fsync_dir`.
4. **Cerrar.** Se borra el diario, se marcan los documentos como guardados y se actualizan sus huellas `base`.

**Recuperación** al abrir el proyecto o tras una excepción: si el diario está en `prepared`, se borran los temporales. Si está en `backed_up` o confirmando, se compara el sha de cada destino: si todos coinciden con `after`, se cierra; si faltan algunos y sus temporales existen con `after_sha256`, se avanza; en otro caso se retrocede con las `.bak` (los CREATE van a la papelera). Es idempotente, y `ui/dialogs/recovery.py` explica lo que se hizo.

**Otras salvaguardas.**
- **Conflictos externos.** Antes de confirmar, la huella actual del destino debe ser igual a `expected`. Si no, el diálogo ofrece «Conservar mis cambios», «Recargar del disco» o «Comparar».
- **Bloqueo.** Una segunda instancia abre el proyecto en solo lectura; un bloqueo cuyo pid ya no existe se considera caducado.
- **Autoguardado de recuperación.** Escribe los `snapshot()` de los documentos sucios en `recovery/<sesión>/` con `journal.py` y a través del guard. Al arrancar, si hay una sesión huérfana, ofrece restaurarla como documentos sucios. El historial de deshacer no se persiste, y así se documenta.

---

## 7. Índice de símbolos (`core/index`)

```python
@dataclass(frozen=True)
class Symbol:
    kind: str; name: str; rel: VPath; line: int | None; layer: LayerKind
    attrs: Mapping[str, object]     # party: {"country_file", "ideology", "start", "end"}; technology: {"folder", "area", "year"};
                                    # unit_type: {"type": "land"|"naval", "active"}; province: {"color", "is_sea", "coastal"}
@dataclass(frozen=True)
class SymbolRef:
    kind: str; name: str; rel: VPath; line: int | None; column: int | None
    role: str                       # "owner", "add_core", "casus_belli", "texturefile", "scope"…
@dataclass(frozen=True)
class FileFacts:
    rel: VPath; layer: LayerKind; fingerprint: Fingerprint
    defs: tuple[Symbol, ...]; refs: tuple[SymbolRef, ...]; extractor: str; version: int

def extractor(pattern: str, *, version: int): ...   # decorador; registro por descubrimiento

class SymbolIndex:
    def names(self, kind: str) -> list[str]
    def get(self, kind: str, name: str) -> Symbol | None           # definición efectiva
    def lookup(self, kind: str, name: str) -> list[Symbol]         # todas (> 1 = duplicado o compartido)
    def exists(self, kind: str, name: str, *, ignore_case: bool = False) -> bool
    def attrs(self, kind: str, name: str, attr: str, default=None) -> object
    def search(self, text: str, *, kinds: Collection[str] = (), loc: "LocalisationDB | None" = None,
               lang: str = "es", limit: int = 50) -> list[Symbol]   # id, nombre localizado, «549 Berlín»
    def display(self, kind: str, name: str, loc: "LocalisationDB", lang: str) -> str   # «Prusia (PRU)»
    def refs_to(self, kind: str, name: str) -> list[SymbolRef]     # «dónde se usa», impacto de renombrar o borrar
    def refs_from(self, rel: VPath) -> list[SymbolRef]
    def entities(self, schema_kind: str) -> list["EntitySummary"]  # listas sin abrir archivos
    def apply(self, facts: Iterable[FileFacts], removed: Iterable[VPath] = ()) -> None
    generation: int

def build_index(snapshot: VfsSnapshot, cache: "FactsCache", overrides: Mapping[VPath, bytes], *,
                progress=None, cancelled: CancelCheck = None) -> SymbolIndex   # lanza core.cancel.Cancelled
```

| Tipo | Fuente | Datos |
|---|---|---|
| `tag` | `common/countries.txt` | archivo, `dynamic` (detrás de `dynamic_tags`), color del archivo de país |
| `party` | `party.name` de `common/countries/*.txt` | **(archivo de país, nombre)**, ideología, fechas, políticas (H12) |
| `province`, `sea_province` | `definition.csv` + `default.map: sea_starts` | color, nombre de la fila, `is_sea`, `coastal` (del ráster) |
| `province_history`, `pop_block` | `history/provinces/**`, `history/pops/<fecha>/*` | rutas; (fecha, id) → ubicaciones |
| `region`, `sea_region`, `continent`, `climate` | `map/region.txt`, `region_sea.txt`, `continent.txt`, `climate.txt` | miembros |
| `culture`, `culture_group`, `religion`, `religion_group` | `common/cultures.txt`, `common/religion.txt` | grupo, color (religión en 0–1) |
| `government`, `ideology`, `issue_group`, `issue_option` | `governments.txt`, `ideologies.txt`, `issues.txt` | ideologías permitidas, `flagType`, categoría (`party_issues`, `political_reforms`…) |
| `technology`, `invention`, `tech_school`, `tech_folder` | `technologies/*.txt`, `inventions/*.txt`, `technology.txt` | carpeta, área, año, `activate_unit` |
| `goods`, `building`, `pop_type`, `unit_type`, `graphical_culture`, `national_value`, `terrain`, `rebel_type`, `trait`, `modifier` | su archivo | color de bien, `max_level`, `type` de unidad… |
| `cb`, `bookmark`, `war`, `event`, `decision` | `cb_types.txt` (sin `peace_order`), `bookmarks.txt`, `history/wars`, `events`, `decisions` | en `peace_order`, fecha, tipo de evento |
| `sprite`, `gui_window`, `asset`, `event_picture`, `decision_picture`, `font` | `interface/*.gfx`, `interface/*.gui`, `gfx/**` | textura resuelta, fotogramas |
| `loc_key` | `LocalisationDB` efectiva | archivo y línea ganadores |
| `country_flag`, `global_flag`, `province_flag` | `set_*_flag` | definidos por uso (nunca «inexistentes») |

- **Extractores.** Los que se derivan de los esquemas (`provides` + `symbol_attrs`, y cada campo `Ref` deja una referencia) más extractores especiales en `core/index/extractors/` (`definition.csv`, `default.map`, sprites, imágenes, localización, flags, y las referencias tipadas del catálogo de guion: `owns = 832`, ámbitos `TUR_860 = { }`).
- **Caché.** Un archivo de hechos JSON-lines comprimido por capa (no pickle): `<cache_dir>/index/game-<sha1(realpath)>/facts.v<N>.jsonl.gz`, compartido entre mods, y `…/mod-<sha1>/`. Se invalida por `INDEX_FORMAT` y por la versión de cada extractor.
- **Incremental.** Al abrir se compara `(size, mtime_ns)` con la caché y solo se parsea lo cambiado. Durante la sesión, cada `DocChanged` programa, con 300 ms de espera, la reextracción de ese documento a partir de su `snapshot()` en segundo plano. `apply` combina según §5.2: en WHOLE_FILE solo cuenta el archivo ganador; en UNION, todos los no ocultos. `index.flush()` es síncrono para las pruebas.
- **Construcción** en segundo plano con `ui/tasks.TaskRunner`, en un grupo de hilos propio del índice, y `gc.freeze()` del resultado tras la pasada en frío.

---

## 8. Sincronización de localización (`core/locsync.py`)

```python
class LocSync:
    def __init__(self, ws: Workspace, vfs: VirtualFS, *, prefix: str, languages: Sequence[str] = ("en", "es"),
                 copy_en_to: Sequence[str] = ()) -> None
    def text(self, key: str, lang: str = "es") -> str | None        # vista efectiva (I7)
    def where(self, key: str) -> tuple[VPath, int] | None           # archivo y línea ganadores
    def keys_for(self, record: "Record") -> list[tuple["LocSpec", str]]   # LocSpec del esquema + campos LocKey
    def ensure(self, keys: Mapping[str, Mapping[str, str]], *, area: str) -> list[str]   # crea las que falten
    def set_text(self, key: str, lang: str, text: str, *, area: str) -> None
    def rename(self, old: str, new: str) -> None                    # ignora LocSpec(shared=True)
    def delete(self, key: str) -> None                              # solo filas del mod; nunca borra de vanilla
    def missing(self, keys: Iterable[str], langs: Sequence[str] = ("en", "es")) -> dict[str, list[str]]
    def orphans(self) -> list[str]                                  # claves del mod que nada usa (info)
    def target_file(self, area: str) -> VPath                       # localisation/00_<P>_<area>.csv
    def localisation_db(self) -> "LocalisationDB"                   # mod + juego + documentos sucios
```

Política (gana la primera clave cargada; los archivos se cargan en orden alfabético por `load_order_key`, y un CSV del mod sustituye al del juego con el mismo nombre):

- **Clave nueva** → fila en `00_<P>_<área>.csv` (`countries`, `events`, `decisions`, `cb`, `governments`, `units`, `cultures`, `map`…). Si ya existe un archivo que sigue el patrón (`00_VSM_countries.csv`), se reutiliza.
- **Clave cuyo ganador está en un archivo del mod** → se edita en su sitio con `LocRow.set`. En VSM esto incluye su copia de `text.csv`.
- **Clave cuyo ganador está en el juego** → fila en `00_<P>_overrides.csv`, que carga antes que `text.csv` y gana. Nunca se copia `text.csv`.
- **Formato.** El archivo nuevo imita a los del mod: cabecera `key;English;…` si los del usuario la llevan (VSM la lleva) y la misma convención de marcador `x`. Si no hay ninguno, se usa el formato de vanilla: `clave;13 idiomas;x`, cp1252 y CRLF. Un `;` o un salto de línea dentro de un texto se rechazan antes de escribir (`check_text`, `InvalidFieldError`).
- **Idiomas.** Se rellenan las columnas de `settings.languages` (por defecto inglés y español, como hace el usuario). La opción `copy_en_to` copia el inglés a francés o alemán, porque el juego solo muestra EN, FR, DE y ES.
- Todas las operaciones son ediciones dentro de la transacción de quien las pide: crear un país y sus claves se deshace en un paso.

En la sala Textos hay filtros «creadas por el Studio», «sin traducir al español», «sustituye a vanilla» (`LocalisationDB.overrides()`) y «degradadas» (`loc_copy_degraded`, H15).

---

## 9. Reglas del juego (`core/rules`)

```python
TAG_RE = re.compile(r"[A-Z][A-Z0-9]{2}")
RESERVED_TAGS = frozenset({"REB"}); SCRIPT_WORDS = frozenset({"AND", "NOT", "ALL", "ANY", "OR", "THIS", "FROM"})
FLAG_SUFFIXES = ("", "_communist", "_fascist", "_monarchy", "_republic"); FLAG_SIZE = (93, 64)
GOV_FLAG_TYPES = ("monarchy", "republic", "communist", "fascist")
EVENT_ID_RANGE = (1, 2**31 - 1)
NEW_FILE_ENCODING, NEW_FILE_NEWLINE = "cp1252", "\r\n"

@dataclass(frozen=True)
class GameRules:
    start_date: ClausewitzDate; end_date: ClausewitzDate     # defines.lua
    bookmarks: tuple[ClausewitzDate, ...]                    # bookmarks.txt
    max_provinces: int; sea: frozenset[int]                  # default.map
    map_size: tuple[int, int]                                # cabecera de provinces.bmp, sin decodificar
    party_policies: Mapping[str, tuple[str, ...]]            # issues.txt → party_issues
    government_ideologies: Mapping[str, frozenset[str]]
    @classmethod
    def from_vfs(cls, vfs: VirtualFS) -> "GameRules"
```

Otras reglas: el calendario no tiene años bisiestos (`ClausewitzDate` ya lo implementa); un id de provincia cumple `1 ≤ id < max_provinces`; los colores de provincia son únicos, distintos de negro y de blanco y de todo color presente en el BMP; los colores son enteros 0–255 salvo en `religion.txt` (0–1); los nombres de archivo de país se limpian de `<>:"/\|?*` y de punto o espacio final; rangos habituales (`plurality` 0–100, `literacy` 0–1, `life_rating` 0–100, `colonial` 0–2): fuera de rango es un aviso, nunca un bloqueo.

---

## 10. Motor de esquemas (`core/schema` + `core/schemas`)

Toda la API pública está en `core/schema/__init__.py`. Son dataclasses congeladas sin E/S, de modo que el agente de interfaz puede importarlas desde el commit de contrato.

### 10.1 Tipos de valor (`types.py`)

```python
class ValueType:
    widget: str                                    # pista: int|float|bool|date|word|text|enum|ref|color|list|path|lockey|sprite|picture
    def read(self, node: Scalar | Block) -> object               # CST → Python; ValueError si no encaja
    def write(self, value: object, old: Scalar | Block | None) -> object   # Python → valor que acepta Block.set
    def check(self, node, ctx: "CheckContext") -> Iterable["Problem"]
    def example(self, ctx: "CheckContext") -> object              # valor válido (arnés de pruebas)
    def describe(self, lang: str) -> str                          # docgen: «entero de 0 a 100»

Int(min=None, max=None, unit=None)       # min/max pueden ser FromSymbol(K.BUILDING, "railroad", "max_level")
Float(min=None, max=None, step=0.1)      # write conserva los decimales del texto anterior ("25.0" → "30.0")
Bool()                                   # yes/no
Date()                                   # ClausewitzDate; conserva comillas si las había
Word(pattern=None)                       # palabra sin comillas (ids, flags)
Text(quoted=True)                        # cadena entre comillas
Enum(*values)                            # valores fijos del motor (flagType, Orientation…)
Ref(kind, *, filter=None, allow_new=False)   # símbolo del índice; filter(sym, record) -> bool
Color(scale=255)                         # { r g b }; scale=1.0 en religion.txt
ListOf(item, *, unique=False)            # { 1 2 3 } o { "a" "b" }
Path(base, suffixes=(".txt",))           # oob = "ARG_oob.txt" relativo a history/units
LocKey(suggest=None)                     # el VALOR es una clave (title = "EVTNAME16000")
SpriteFrame(sprite)                      # sprite_index → fotograma de GFX_diplo_wargoal_icons
Picture(folder, default="{id}")          # picture = X → gfx/pictures/<folder>/X.(tga|dds)
FromSymbol(kind, name, attr)             # cota dinámica
```

Los tipos se construyen también desde JSON (`types.from_spec({"type": "ref", "kind": "tag"})`): el catálogo de guion usa exactamente los mismos.

### 10.2 Campos (`fields.py`)

```python
MISSING = object()

@dataclass(frozen=True)
class Field:
    key: str; type: ValueType
    required: bool = False
    default: object = MISSING            # lo que asume el juego si falta: se muestra en gris y NO se escribe
    repeat: bool = False                 # clave repetible (add_core, culture, regiment)
    accumulate: "SetOps | None" = None   # SetOps(add="add_core", remove="remove_core") en historia
    ignore_case: bool = False            # .gui: Orientation/orientation
    aliases: tuple[str, ...] = ()
    visible_if: "Condition | None" = None   # When("election", True)
    advanced: bool = False               # oculto en modo sencillo
    ui: str | None = None                # "slider", "chips", "map_pick", "matrix"
    label: str = ""; help: str = ""      # por defecto "schema.<kind>.<key>" y ".help"

@dataclass(frozen=True)
class Group:                             # bloque anidado con subcampos (party, war_goal, position)
    key: str; fields: tuple["FieldLike", ...]
    repeat: bool = False; required: bool = False
    id_field: str | None = None          # party → "name"
    widget: str = "auto"                 # "table" si todo son escalares; si no, "cards"
    dynamic: "DynamicKeys | None" = None # upper_house = { fascist = 0 liberal = 20 … }

@dataclass(frozen=True)
class DynamicKeys:                       # claves sacadas del índice (H19)
    name: str; key_kind: str             # "technology", "invention", "issue_group", "ideology", "tag", "government", "goods"
    value: ValueType | Callable[[str], ValueType]
    key_filter: Callable | None = None   # solo reformas políticas y sociales, solo unidades navales…
    widget: str = "auto"                 # checklist | grid | table | sliders
    group_by: str | None = None          # tecnologías por "folder" y "area"
    only_true: bool = False              # escribe solo las claves = yes/1 y borra en vez de escribir "= no"

@dataclass(frozen=True)
class Values:   item: ValueType          # el bloque ES una lista (region.txt: USA_1 = { 1 2 3 })
@dataclass(frozen=True)
class Children: schema: "EntitySchema"; match: Callable = REMAINING_BLOCKS   # culturas dentro del grupo
@dataclass(frozen=True)
class Script:                            # condiciones y efectos: los edita core.script
    key: str                             # o REST: el resto del bloque (modifier = { factor = 2 <condiciones> })
    kind: "ScriptKind"; scope: "Scope" = Scope.COUNTRY; repeat: bool = False; required: bool = False
@dataclass(frozen=True)
class Opaque:   key: str                 # se conserva y se edita como código
@dataclass(frozen=True)
class Section:  name: str; items: tuple["FieldLike", ...]; collapsed: bool = False   # tarjeta del formulario

FieldLike = Field | Group | DynamicKeys | Values | Children | Script | Opaque
```

### 10.3 Entidad (`entity.py`)

```python
@dataclass(frozen=True)
class LocSpec:
    template: str          # "{id}", "{id}_desc", "PROV{id}", "EVTNAME{id}", "NORMAL_{war_name}"
    area: str              # archivo destino: localisation/00_<P>_<area>.csv
    required: bool = True
    shared: bool = False   # la comparten varias entidades: no se renombra ni se borra con ellas

@dataclass(frozen=True)
class HistorySpec:
    mode: str = "state"    # "state": valor vigente por fecha (provincias, países); "log": cada bloque es un suceso (guerras)

@dataclass(frozen=True)
class Variant:  field: str; cases: Mapping[str, tuple[FieldLike, ...]]   # unit: {"land": …, "naval": …}
@dataclass(frozen=True)
class View:     key: str; filter: Callable[["Record"], bool]; section: str  # dos secciones sobre un esquema

@dataclass(frozen=True)
class EntitySchema:
    kind: str
    layout: "FileLayout"
    fields: tuple[FieldLike | Section, ...]
    ident: "IdSpec" = IdSpec.KEY            # KEY | FIELD("name") | FILE("id") | COMPOSITE(("first", "second", "start_date"))
    ident_rule: "IdRule" = IdRule.WORD      # IdRule.TAG, IdRule.SNAKE, IdRule.INT_RANGE("event")…
    provides: str | None = None             # tipo de símbolo que define
    symbol_attrs: Callable[["Record"], dict] | None = None
    history: HistorySpec | None = None
    variants: Variant | None = None
    views: tuple[View, ...] = ()
    loc: tuple[LocSpec, ...] = ()
    validators: tuple["RecordValidator", ...] = ()
    companions: tuple["Companion", ...] = ()
    template: Callable[[str, "SymbolIndex"], dict] | None = None   # valores iniciales de «Nuevo»
    unknown: str = "keep_warn"              # claves no declaradas: se conservan, se listan en «Otros campos» y avisan
    ignore_case: bool = False
    hall: str | None = None; section: str | None = None; order: int = 100   # dónde aparece en la interfaz
    icon: str = "file_text"; preview: str | None = None   # "event", "decision", "unit_card", "flag"…
    editable: bool = True                   # False: solo se indexa (tecnologías, ideologías, issues…)
```

### 10.4 Disposición en archivos (`layouts.py`)

```python
class FileLayout(Protocol):
    merge: LoadMode
    def files(self, vfs: VirtualFS) -> list[FileEntry]
    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]   # (id, bloque, entrada dueña)
    def target_for_new(self, ctx, ident: str, values: dict) -> tuple[VPath, "BlockPath"]        # archivo del mod y contenedor
    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry
```

| Disposición | Archivos reales | Notas |
|---|---|---|
| `SingleFile(path, skip=())` | `common/governments.txt`, `common/cb_types.txt` (sin `peace_order`), `common/country_colors.txt`, `common/nationalvalues.txt`, `map/region.txt`, `map/region_sea.txt`, `map/continent.txt` | WHOLE_FILE |
| `PairedKeys(path)` | `map/climate.txt` | Una entidad, dos entradas (H7) |
| `RepeatedKey(path, key, id_field)` | `common/bookmarks.txt` (`bookmark`, id = `name`), `history/diplomacy/*.txt` (`alliance`…, id compuesto) | — |
| `GroupedIn(path)` | `common/cultures.txt`, `common/religion.txt` | Padre e hijos |
| `Registry(path, before="dynamic_tags")` | `common/countries.txt` | H11 |
| `NestedIn(glob, container, new_file)` | `decisions/*.txt` → `political_decisions = { X = { … } }` | Lo nuevo va a `decisions/<P>_decisions.txt` |
| `TypedEntries(glob, keys, id_field, new_file)` | `events/*.txt` (`country_event`/`province_event`, `id`) | Lo nuevo va a `events/<P>_events.txt` |
| `OnePerFile(folder, regex, new_name, recursive)` | `history/provinces/**/{id} - {name}.txt` (regex `^(?P<id>\d+)\s*(?:-\s*)?(?P<name>.*)\.txt$`), `history/countries/{TAG} - {name}.txt`, `common/countries/{name}.txt`, `units/{id}.txt`, `history/wars/{name}.txt`, `history/units/**/*.txt` | Un documento por entidad |
| `KeyedAcross(glob, key_regex)` | `history/pops/<fecha>/*.txt`, `map/positions.txt` | Entidad repartida: el `RecordRef` lleva `rel` |
| `Table(path, columns)` | `map/definition.csv`, `map/adjacencies.csv` | Filas como registros |
| `Descriptor()` | `<juego>/mod/<carpeta>.mod` | Lo resuelve la VFS, fuera de las rutas relativas |

### 10.5 Registros y servicio de entidades (`record.py`)

```python
@dataclass(frozen=True)
class RecordRef:
    kind: str; ident: str; rel: VPath | None = None   # rel: entidades repartidas (POPs de una provincia en un archivo)

class Record:                                          # vista sobre el Block real; nunca copia datos
    schema: EntitySchema; ref: RecordRef; block: Block; handle: DocHandle; origin: LayerKind
    def get(self, key: str, default=MISSING) -> object          # valor tipado o default del esquema
    def get_all(self, key: str) -> list
    def node(self, key: str) -> Entry | None                     # «ir al código»
    def set(self, key: str, value: object) -> None               # None/MISSING elimina la entrada
    def add(self, key: str, value: object) -> Entry              # repetibles: tras la última de la misma clave
    def remove(self, key: str, value: object = MISSING) -> int
    def group(self, key: str, index: int = 0) -> "Record"
    def groups(self, key: str) -> list["Record"]
    def add_group(self, key: str, values: dict) -> "Record"
    def dynamic(self, name: str) -> dict[str, object]            # {"flintlock_rifles": 1, …}
    def set_dynamic(self, name: str, key: str, value: object) -> None
    def children(self) -> list["Record"]
    def script(self, key: str) -> "ScriptTree"
    def at(self, date: ClausewitzDate | None) -> "HistoryView"
    def unknown(self) -> list[Entry]                             # se conservan (I6)
    def issues(self, ctx: "CheckContext") -> list["Problem"]
    def loc_keys(self) -> list[tuple[LocSpec, str]]

class Entities:
    def __init__(self, ws: Workspace, index: SymbolIndex, loc: LocSync) -> None
    def list(self, kind: str, *, query: str = "", view: str | None = None) -> list["EntitySummary"]   # del índice
    def open(self, ref: RecordRef) -> Record
    def create(self, kind: str, ident: str, values: dict | None = None, *,
               texts: Mapping[str, Mapping[str, str]] | None = None, target_rel: VPath | None = None) -> RecordRef
    def duplicate(self, ref: RecordRef, new_ident: str) -> RecordRef      # «basar en…»
    def rename(self, ref: RecordRef, new_ident: str, *, update_refs: bool = True) -> "ChangePlan"
    def delete(self, ref: RecordRef, *, force: bool = False) -> "ChangePlan"   # bloquea si hay usos
    def restore_vanilla(self, ref: RecordRef) -> None
    def where_used(self, ref: RecordRef) -> list[SymbolRef]
```

Toda mutación de un `Record` llama antes a `ws.touch(handle)`. `create`, `rename` y `delete` corren en una sola transacción: el almacén, los compañeros, LocSync (las claves de `loc`) y la actualización del índice. `rename` y `delete` devuelven antes un `ChangePlan` para mostrar los usos y confirmar.

### 10.6 Historia fechada (`history.py`)

```python
@dataclass(frozen=True)
class Effective: value: object; entry: Entry | None; date: ClausewitzDate | None   # None = sin fecha

class HistoryView:
    def __init__(self, record: Record, date: ClausewitzDate | None, bookmarks: Sequence[ClausewitzDate]) -> None
    def get(self, key: str) -> Effective
    def get_set(self, key: str) -> list[Effective]     # acumulativos: add_core/remove_core
    def set(self, key: str, value: object) -> Entry
    def add(self, key: str, value: object) -> Entry    # tras el inicio escribe add_core en el bloque vigente
    def remove(self, key: str, value: object) -> None  # tras el inicio escribe remove_core; en el inicio borra add_core
    def dated_blocks(self) -> list[tuple[ClausewitzDate, Block]]
```

- **Lectura en la fecha D**: primero las entradas sin fecha en orden de archivo; después los bloques con fecha ≤ D, por fecha. Dos bloques con la misma fecha cuentan en orden de archivo.
- **Escritura en la fecha D**: si D es la fecha de inicio (o `None`), se escribe la entrada sin fecha. Si no, el destino es el **último bloque fechado existente con fecha en el intervalo (bookmark anterior, D]**. Si no hay ninguno, se crea `D = { }` en su posición cronológica.
- **Modo LOG** (guerras): cada bloque fechado es un suceso con su propio subformulario y la interfaz muestra una línea temporal.

### 10.7 Política de colocación (`placement.py`)

Al añadir una entrada, en este orden:

1. **Repetible con hermanos**: justo tras el último de la misma clave (`add_core = DEN` tras `add_core = GER`).
2. **Orden del esquema**: tras la última entrada existente cuyo campo va antes en el esquema; si no hay, antes de la primera cuyo campo va después.
3. **Bloques fechados**: una entrada sin fecha nunca se coloca detrás del primer bloque fechado (`append` dejaría `fort = 2` detrás de `1861.1.1 = { … }`).
4. **Claves dinámicas**: tras la última del mismo catálogo; si no hay, al final de su sección.
5. **Registro**: `Registry(before=K)` inserta en el índice de `K` (`Block.index_of`); la entrada nueva se escribe delante de la trivia (comentarios) que precede a `K`.
6. **Documento nuevo**: orden completo del esquema con `format_canonical`, en cp1252 y con el salto de línea de los demás archivos del mod (CRLF por defecto).

### 10.8 Compañeros y recetas (`companions.py`, `recipes.py`)

```python
class Companion(Protocol):
    def on_create(self, ctx: "EditContext", rec: Record) -> None: ...
    def on_delete(self, ctx: "EditContext", rec: Record) -> None: ...
    def on_rename(self, ctx: "EditContext", rec: Record, old: str, new: str) -> None: ...
    def check(self, ctx: "CheckContext", rec: Record) -> Iterable["Problem"]: ...

RegisterTag(registry="common/countries.txt", before="dynamic_tags", value="countries/{file}.txt")
AppendToList(rel="common/cb_types.txt", path=("peace_order",))
MappingTable(rel="common/rebel_types.txt", table="government", default=Ask())   # 14 tablas (H16)
ActivateUnit(optional=True)          # ver o cambiar la tecnología o invención que la activa
UnitNamesSlot()                      # al crear una unidad naval, ofrece su clave en unit_names

@dataclass(frozen=True)
class Recipe:                        # flujos multiarchivo; los parámetros también son campos de esquema
    key: str; label: str
    params: tuple[FieldLike, ...]
    steps: tuple["Step", ...]
    pages: tuple[tuple[str, tuple[str, ...]], ...] = ()   # pasos del asistente
    def plan(self, ctx: "RecipeContext", values: dict) -> "ChangePlan"    # vista previa: archivos, acciones y diff
    def apply(self, ctx: "RecipeContext", values: dict) -> list[RecordRef]  # una transacción

# Pasos: CreateRecord, CopyRecord, RegistryLine, AppendToList, EnsureLoc, WriteImages, AssignProvinces, Conditional
```

`Entities.create` ejecuta una receta implícita (`CreateRecord` + `EnsureLoc` + compañeros). Las recetas con nombre (`new_country`, `new_war`, `new_map`) añaden pasos y tienen asistente propio cuando la interfaz lo merece.

### 10.9 Textos, documentación y CLI

- **Textos.** `core/schemas/texts/<kind>.es.json` y `.en.json` con claves derivadas (`schema.<kind>.<field>`, `.help`, `schema.section.<name>`, `schema.enum.<enum>.<value>`). `core/texts.load_texts(lang)` los fusiona y falla ante duplicados. Las etiquetas de catálogos dinámicos (tecnologías, reformas, culturas) salen de la **localización del propio juego** con `LocalisationDB.lookup(name, "es", fallback="en")` y no se duplican en los JSON.
- **Documentación.** `python -m vic2studio.core.schema doc --lang es|en -o docs/referencia/` genera, por esquema: archivos y disposición, tabla de campos (clave, tipo, por defecto, obligatorio, descripción), claves de localización y un ejemplo mínimo. La misma ayuda se ve en la app (botón «?», `QTextBrowser.setMarkdown`).
- **CLI.** `python -m vic2studio.core.schema check JUEGO [MOD] [--kind K] [--lang es]`, `list` y `show KIND`.

### 10.10 Ejemplo completo: gobierno

```python
# core/schemas/government.py
"""Formas de gobierno (common/governments.txt). Vanilla: 8, sin problemas. Sin flagType el juego usa TAG.tga."""
from ..schema import (Bool, DynamicKeys, EntitySchema, Enum, Field, Int, LocSpec, MappingTable, Section,
                      SingleFile, When, issue, validator)

@validator("government_without_ideology", "error")
def at_least_one_ideology(rec, ctx):
    if not any(rec.dynamic("ideology").values()):
        yield issue("government_without_ideology", rec)

@validator("government_election_without_duration", "warning")      # caso real: VSM absolute_monarchy
def election_needs_duration(rec, ctx):
    if rec.get("election", False) and rec.get("duration", None) is None:
        yield issue("government_election_without_duration", rec, field=("duration",))

GOVERNMENT = EntitySchema(
    kind="government", layout=SingleFile("common/governments.txt"), provides="government",
    symbol_attrs=lambda rec: {"ideologies": tuple(k for k, v in rec.dynamic("ideology").items() if v),
                              "flag_type": rec.get("flagType", None)},
    fields=(
        Section("ideologies", (DynamicKeys("ideology", "ideology", Bool(), widget="checklist", only_true=True),)),
        Section("elections", (
            Field("election", Bool(), required=True),
            Field("duration", Int(1, 600, unit="months"), visible_if=When("election", True)),
            Field("appoint_ruling_party", Bool(), required=True),
        )),
        Section("flag", (Field("flagType", Enum("monarchy", "republic", "communist", "fascist")),)),
    ),
    loc=(LocSpec("{id}", "governments"), LocSpec("{id}_ruler", "governments")),
    validators=(at_least_one_ideology, election_needs_duration),
    companions=(MappingTable("common/rebel_types.txt", table="government"),),
    template=lambda ident, idx: {"election": False, "appoint_ruling_party": True, "ideology": {"conservative": True}},
    hall="nations", section="governments", order=30, icon="crown",
)
SCHEMAS = (GOVERNMENT,)
```

### 10.11 Qué cuesta una entidad nueva

1. `core/schemas/<kind>.py` (40–120 líneas) que exporta `SCHEMAS = (...)` y, si hace falta, `RECIPES = (...)`.
2. `core/schemas/texts/<kind>.es.json` y `.en.json`.
3. `tests/test_schema_<kind>.py`: una subclase de 3 líneas de `SchemaContract` (§19.3) y, si el minijuego no lo trae, su fragmento sintético en `tests/_minigame.py`.

La sección aparece sola en su sala gracias a `hall` y `section`, y la ayuda sale de docgen. Solo se escribe interfaz a mano para una vista previa opcional o un control especial. El registro es por descubrimiento (`pkgutil.iter_modules` sobre `core/schemas`): añadir una entidad no toca ningún archivo compartido.

---

## 11. Validación cruzada (`core/validate`)

```python
@dataclass(frozen=True)
class Problem:
    code: str; severity: Severity; rel: VPath | None; line: int | None; column: int | None
    ref: RecordRef | None = None; field: tuple[str, ...] = (); args: Mapping = MappingProxyType({})
    inherited: bool = False                     # también ocurre en la capa del juego (I11)
    fixes: tuple[str, ...] = ()                 # claves de FIXES; la primera es el SimpleFix
    def message(self, lang: str) -> str         # core/validate/texts/issues.{es,en}.json
    def fingerprint(self) -> tuple              # (code, rel, field, args sin línea)

def rule(code: str, severity: Severity, *, scope: str = "project", fixes: tuple[str, ...] = ()): ...   # decorador
@dataclass
class ValidationContext:
    snapshot: VfsSnapshot; index: SymbolIndex; loc: "LocalisationDB"; rules: GameRules
    date: ClausewitzDate | None; mapdata: "MapData | None"
class Validator:
    def validate(self, *, codes=None, files=None, progress=None, cancelled=None) -> "ValidationReport"
    def validate_record(self, rec: Record) -> list[Problem]   # en vivo, con 300 ms de espera
def compute_baseline(game_only: ValidationContext) -> frozenset[tuple]   # caché por instalación
FIXES: dict[str, Callable[[Problem, "Project"], None]]          # cada arreglo es una transacción deshacible
```

- Se ejecutan los validadores de cada esquema, las reglas globales de `core/validate/rules/{syntax,files,descriptor,countries,provinces,map,events,decisions,localisation,units,military,interface,history,mapforge}.py` (`mapforge`: los códigos del taller, §18.11) y la sintaxis actual (`modcheck.check_file` pasa a ser la familia «syntax»).
- **Línea base.** Las reglas se ejecutan en segundo plano sobre la capa del juego sola, con caché por instalación. En el informe del proyecto se marca `inherited=True` cuando la huella coincide. El panel oculta los heredados por defecto, con el conmutador «Mostrar heredados del juego base (n)».
- **Integración.** `modcheck.Issue` gana `entity` y `fixes` con valores por defecto (compatible). «Validar mod» (F7) usa el validador global. Doble clic abre el editor de la entidad con el campo enfocado o, si no hay formulario, el código en esa línea.

### 11.1 SimpleFix y explicador de conflicto (decisión del usuario, §24)

Cada problema lleva dos botones: **[Arreglar]** (SimpleFix) y **[¿Por qué?]** (explicador de conflicto).

```python
@dataclass(frozen=True)
class FixSpec:
    key: str; label: str                         # «Registrar SIL en countries.txt»
    safe: bool                                   # True: solo añade o restaura; False: borra o sustituye
    plan: Callable[[Problem, "Project"], "ChangePlan"]    # vista previa: archivo · acción · diff
    apply: Callable[[Problem, "Project"], None]           # una transacción con nombre, deshacible

@dataclass(frozen=True)
class ExplainStep:
    layer: str                                   # "game" | "mod" | "replace_path" | "studio (sin guardar)"
    rel: VPath | None; line: int | None; excerpt: str     # la línea real de cada capa
    verdict: str                                 # "gana" | "pierde" | "oculto" | "no se carga" | "falta"

@dataclass(frozen=True)
class Explanation:
    title: str; steps: tuple[ExplainStep, ...]   # en el orden en que el juego carga las capas
    outcome: str                                 # qué verá el jugador, en frases ES/EN
    fixes: tuple[FixSpec, ...]

def explain(problem: Problem, ctx: ValidationContext) -> Explanation   # core/validate/explain.py
```

- **SimpleFix.** El botón aplica el primer arreglo de `fixes` (el más seguro). Antes muestra su plan de cambios (archivo · acción · diff) y espera confirmación; los demás arreglos van en el desplegable del botón. Nunca se aplica nada solo, ni siquiera al validar. Cada arreglo es una transacción deshacible en un paso. Un arreglo `safe=False` (borrar, sustituir) pide confirmación explícita y manda lo borrado a la papelera.
- **Explicador de conflicto.** Reconstruye, con `VfsSnapshot.stack()`, el índice de símbolos y `LocalisationDB.source_of/overrides()`, qué capas definen lo mismo y en qué orden las carga el juego: archivo del mod que sustituye al de vanilla con la misma ruta, primera clave de localización que gana por orden alfabético de archivos, `replace_path` que oculta una carpeta, dos historias con el mismo id, TAG detrás de `dynamic_tags`, id de evento repetido… Cada capa se muestra con su línea real y su veredicto, y termina en una frase sobre el efecto en el juego («En partida verás "Capacit?" en francés porque tu text.csv sustituye al del juego») y en los arreglos disponibles.
- Los problemas heredados (I11) también se explican, para que el modder entienda por qué se ocultan.

Catálogo inicial (las capacidades añaden las suyas):

| Código | Gravedad | Comprueba | Caso real |
|---|---|---|---|
| `tag_not_registered` | error | TAG usado (historia, dueño, bandera) que no está en `countries.txt`. Arreglo: registrar antes de `dynamic_tags` | SIL en VSM |
| `tag_after_dynamic_tags` | error | TAG del mod detrás de `dynamic_tags = yes` | lo que haría `Block.append` |
| `tag_invalid` / `tag_taken` | error | patrón, REB, palabra de guion, dispositivo de Windows / ya usado (D01–D50 incluidos) | `CON.tga` no se puede crear |
| `country_file_missing`, `country_history_missing`/`_duplicate` | error/aviso/error | referencias del registro y una historia por TAG | — |
| `ruling_party_not_of_country` | error | el partido no está en el archivo del propio TAG | — |
| `ruling_party_ideology_not_allowed` | aviso | el gobierno no admite su ideología | SOM_socialist; 13 heredados |
| `party_unknown_policy` | aviso | política fuera de `party_issues` | `social_policy` en Somalia |
| `nationalvalue_unknown` y demás `*_unknown` | error | referencias rotas por tipo (cultura, religión, gobierno, tecnología, reforma, bien, edificio, tipo de POP, CB, unidad) | `nv_tradition` ×4 |
| `upper_house_sum` | aviso | `upper_house` no suma 100 | — |
| `government_missing_in_rebel_map` | error | gobierno ausente en alguna de las 14 tablas de `rebel_types.txt` | — |
| `government_election_without_duration` | aviso | `election = yes` sin `duration` | VSM `absolute_monarchy` |
| `cb_not_in_peace_order` / `peace_order_unknown` | aviso | CB fuera de `peace_order` / valor que no es un CB | `annex` (heredado) |
| `province_history_duplicate` | error | dos archivos con el mismo id | 1396/1397 (heredados) |
| `bmp_color_unmapped` | aviso | color del BMP sin fila en `definition.csv` | 27 (heredados) |
| `land_province_without_region` / `_multiple_regions` / `sea_in_region` / `_without_continent` | error | invariantes H6 | vanilla: 0 |
| `event_id_duplicate` | error | id repetido en la vista efectiva | vanilla: 0 |
| `event_ref_missing` | aviso | `country_event = X` sin evento X | 11108 (heredado) |
| `loc_key_missing` / `loc_untranslated` / `loc_key_orphan` | aviso/info/info | claves de títulos, opciones, TAG, `PROV<id>`, regiones… | `AGC;Angoche;;;…` sin español |
| `loc_copy_degraded` | aviso | CSV del mod con el nombre de uno de vanilla cuyas filas solo difieren por `?` en lugar de letras acentuadas. Arreglo: recuperar esas filas | `text.csv` de VSM (3 429 filas) |
| `non_game_encoding` | aviso | archivo en UTF-8 (arreglo: convertir a cp1252) | `HAI_oob.txt` (heredado) |
| `mod_shadow_identical` | info | archivo del mod idéntico al del juego (limpieza opcional a la papelera, salvo en carpetas `replace_path`) | 8 462 en VSM |
| `case_collision`, `windows_reserved_name`, `path_too_long` | error/error/aviso | rutas inválidas o ambiguas en Windows | — |
| `descriptor_*`, `replace_path_*` | error/aviso | §14.1 | `VSM.mod` |

---

## 12. Guion: catálogo, árbol sin pérdidas, frases y MTTH (`core/script`)

### 12.1 Catálogo (`core/script/data/*.json`: datos propios, solo nombres, tipos y frases)

```json
{"name": "year", "role": "condition", "scopes": ["any"], "value": {"type": "int", "min": 1700, "max": 2100},
 "category": "time", "label": {"es": "Año", "en": "Year"},
 "phrase": {"es": "estamos en {value} o después", "en": "it is {value} or later"},
 "negated": {"es": "antes de {value}", "en": "before {value}"}}
{"name": "owns", "role": "condition", "scopes": ["country"], "value": {"type": "ref", "kind": "province"}, "category": "territory"}
{"name": "relation", "role": "condition", "scopes": ["country"],
 "block": {"who": {"type": "ref", "kind": "tag"}, "value": {"type": "int"}}}
{"family": "tech", "key_kind": "technology", "role": "condition", "scopes": ["country"], "value": {"type": "enum", "values": ["0", "1"]}}
{"family": "tag_scope", "key_kind": "tag", "role": "scope", "scope_change": "country"}
{"family": "province_scope", "key_kind": "province", "role": "scope", "scope_change": "province"}
{"name": "any_owned_province", "role": "iterator", "scope_change": "province"}
```

```python
class Role(Enum): CONDITION; EFFECT; LOGIC; SCOPE; ITERATOR
@dataclass(frozen=True)
class ScriptKeyDef:
    name: str; role: Role; kinds: frozenset["ScriptKind"]; scopes: frozenset["Scope"]
    value: ValueType | None; block: tuple[FieldLike, ...] | None; scope_change: "Scope | None"
    label: Mapping[str, str]; phrase: Mapping[str, str]; negated: Mapping[str, str]
class ScriptCatalog:
    @classmethod
    def load(cls) -> "ScriptCatalog"
    def lookup(self, name: str, kind: "ScriptKind", scope: "Scope") -> ScriptKeyDef | None   # sin distinguir mayúsculas
    def suggestions(self, kind, scope, text: str, lang: str) -> list[ScriptKeyDef]
```

- `tools/catalog_census.py --corpus <vanilla>` recorre los bloques de condición y efecto del juego instalado y propone claves, recuentos y tipos inferidos (yes/no → `Bool`, números → `Float`, `^[A-Z][A-Z0-9]{2}$` → `Ref(tag)`). El JSON se depura a mano y no contiene texto del juego.
- Las familias dinámicas (tecnologías, bienes, TAG, provincias, tipos de POP) cubren claves como `electricity = 1`, `FRA = { }` o `369 = { }`. Se acepta la grafía en minúsculas de `and/or/not` y de claves como `Prestige`.
- Una prueba exige etiqueta ES y EN en cada entrada.

### 12.2 Árbol (`tree.py`)

```python
class ScriptNode:                         # vista sobre una Entry del CST (sin copia)
    entry: Entry; definition: ScriptKeyDef | None; scope: "Scope"; children: list["ScriptNode"]
    @property
    def raw(self) -> bool                 # clave no catalogada: se conserva y se edita como línea de código
    def set_value(self, value) -> None
    def add_child(self, name: str, value=None, *, index: int | None = None) -> "ScriptNode"
    def wrap(self, op: str = "OR") -> "ScriptNode"     # envolver en AND/OR/NOT
    def unwrap(self) -> None
    def remove(self) -> None
    def summary(self, lang: str, index: SymbolIndex, loc) -> str   # «El país posee Londres (300)»
class ScriptTree:
    def __init__(self, block: Block, kind: "ScriptKind", scope: "Scope", catalog: ScriptCatalog) -> None
    root: ScriptNode                      # AND implícito
    def issues(self, ctx: "CheckContext") -> list[Problem]   # clave desconocida, ámbito incorrecto, ref inexistente
```

Cada nodo apunta a su `Entry`, así que editar el árbol es editar el CST, dentro de una transacción. Prueba de aceptación sobre los 82 archivos de eventos y los 29 de decisiones de vanilla: construir el árbol y `to_source` dan los mismos bytes, y cambiar el valor de un nodo cambia solo su línea.

### 12.3 Frases, MTTH e ids

- `phrases.py` genera «Se dispara si: el país es Austria o Austria-Hungría, y estamos en 1842 o después, y antes de 1845…» con las plantillas `phrase`/`negated` y los nombres localizados del índice. Se muestra bajo cada constructor.
- **MTTH, `ai_chance` y `ai_will_do`** son esquemas pequeños: `Field("months"|"days"|"years")` más `Group("modifier", repeat=True, fields=(Field("factor", Float()), Script(REST, TRIGGER)))`. `mtth.effective(base_months, factors, satisfied) -> float` calcula el tiempo efectivo (p. ej. 6 × 0,75 × 0,95 = 4,3 meses).
- `idalloc.EventIdAllocator(index, settings).next_free()` usa el rango del proyecto y detecta colisiones con vanilla y con el resto del mod.

---

## 13. Interfaz: navegación, pantallas y piezas comunes

### 13.1 Las 7 salas

| Atajo | Placa | Título | Secciones (índice lateral, con contador) |
|---|---|---|---|
| Ctrl+1 | Proyecto | Proyecto y Archivos | Inicio · Descriptor .mod · Archivos · Validación · Cambios pendientes |
| Ctrl+2 | Mapa | Editor de Mapa | Mundo (provincias) · Regiones · Continentes y climas · Estrechos y canales · Taller de mapas |
| Ctrl+3 | Naciones | Naciones | Países · Culturas · Gobiernos |
| Ctrl+4 | Guerra | Guerra e Historia | Fechas de inicio · Guerras de inicio · Diplomacia inicial · Casus belli · Unidades terrestres · Unidades navales |
| Ctrl+5 | Eventos | Eventos y Decisiones | Eventos · Decisiones · Modificadores |
| Ctrl+6 | Interfaz | Interfaz y Gráficos | Ventanas (.gui) · Sprites (.gfx) · Imágenes y banderas |
| Ctrl+7 | Textos | Localización | Todos los textos · Pendientes de traducir · Archivos CSV |

- Las placas llevan nombres cortos para caber a 1100 px (≈150 px por placa, frente a los 112 de `NavButton.minimumSizeHint`); el título largo va en la cabecera de la sala.
- `ui/shell/hall.py: HallPage(BasePage)` contiene un `SectionRail` y un `QStackedWidget`. `MainWindow` pasa de `PAGE_CLASSES` a `HALLS`, descubiertas en `ui/halls/registry.py`; `MainWindow.page(key)` se mantiene.
- Cada `ui/halls/<sala>/__init__.py` exporta `SECTIONS: list[SectionSpec]`. Los esquemas con `hall` y `section` generan su sección (`EntityEditorPage`) sin código.
- Mientras una sección no está implementada se ve como la tarjeta «en desarrollo» actual (`PlannedModulePage`), con la iteración prevista.

```python
@dataclass(frozen=True)
class SectionSpec:
    key: str; hall: str; order: int; title: str; icon: str
    factory: Callable[["Session"], QWidget] | None = None   # None + schema_kind → EntityEditorPage
    schema_kind: str | None = None; view: str | None = None
    badge: Callable[["Session"], int | None] | None = None
```

### 13.2 Esqueleto de la ventana

```text
┌ Estandarte: emblema · «Victoria II Mod Studio» · [Mod: Shago Mod ▾] [Buscar… Ctrl+K] [Fecha 1836.1.1 ▾] [↶ ↷] [Guardar (7)] · Sencillo/Avanzado · ES/EN ┐
├ Placas: Proyecto | Mapa | Naciones | Guerra | Eventos | Interfaz | Textos ───────────────────────────────────────────────────────────┤
│┌ Índice (madera) ┐┌ Sección (pergamino, marco de bronce) ───────────────────────────────────────────────────────────────────────┐│
││ ▸ Países     271 ││ cabecera con medallón · título · subtítulo · acciones                                                       ││
││   Culturas   226 ││ contenido: navegador | formulario | vista previa                                                            ││
││   Gobiernos    8 ││                                                                                                             ││
│└─────────────────┘└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘│
├ Paneles acoplables: Problemas (con [Arreglar] y «mostrar heredados») · Historial (deshacer) ────────────────────────────────────────┤
└ Barra de estado: mensaje · tarea en curso (progreso, cancelar) · «3 archivos sin guardar · 1 se copiará del juego base» ──────────┘
```

Acciones globales: Ctrl+S, Ctrl+Z, Ctrl+Y (y Ctrl+Mayús+Z), Ctrl+K, F7 (validar), Ctrl+1..7. El título de la ventana lleva `*` si hay cambios sin guardar, y `closeEvent` pregunta antes de cerrar y escribe la recuperación.

### 13.3 Inicio

1. **Primer arranque**: elegir la carpeta del juego, validada con `evaluate_game`.
2. **Elegir mod**: tarjetas con los `<juego>/mod/*.mod` leídos con `read_descriptor` (nombre, carpeta, `user_dir`), más «Crear mod nuevo».
3. **«¿Qué quieres hacer?»**: tarjetas de pergamino que lanzan los flujos (crear un país, repartir provincias, montar una guerra de inicio, escribir un evento, crear una decisión, nueva unidad, nuevo gobierno, nueva cultura, editar una ventana del juego, crear un mapa nuevo, traducir textos pendientes (N)). Las tarjetas de capacidades que aún no existen indican en qué iteración llegan.
4. **Estado del mod**: problemas por gravedad (sin los heredados), cambios sin guardar y última validación.

### 13.4 Buscador universal (Ctrl+K)

`CommandPalette` sobre `SymbolIndex.search` y las acciones registradas. Admite «PRU», «Berlín», «549», «north_german», «31501» o «nuevo país». Cada resultado muestra el icono del tipo, el id, el nombre localizado y la cinta de origen. Intro abre el editor de la entidad; Mayús+Intro, el código.

### 13.5 Editor genérico de entidades (`ui/entity/editor_page.py`)

```text
┌ Navegador ─────────────┐┌ Formulario (secciones del esquema) ─────────────┐┌ Vista previa ────────┐
│ filtro  [Origen ▾]     ││ Infantería [infantry]   (Juego base) [Copiar…]   ││ tarjeta de unidad /  │
│ ▸ infantry  Juego base ││ ─ Básico ─  Tipo de unidad (unit_type) [infantry]││ ventana del evento / │
│ ▸ guard     Juego base ││ ─ Coste ─   build_cost [small_arms 10] [+]       ││ bandera…             │
│ ▸ askari    Nuevo      ││ ─ Combate ─ Ataque (attack) [4] …                ││                      │
│ [+ Nuevo] [Duplicar]   ││ Pestañas: Formulario | Textos | Usos | Código |  ││ Problemas (2)        │
│ [Renombrar] [Borrar]   ││           Otros campos                           ││                      │
└────────────────────────┘└──────────────────────────────────────────────────┘└──────────────────────┘
```

- La lista sale de `SymbolIndex.entities(kind)`: id, nombre localizado, origen, archivo y número de problemas.
- Botones: Nuevo, Duplicar («basar en…»), Renombrar (con vista previa de usos), Borrar (bloqueado si hay usos), Restaurar vanilla y Ver en el archivo.
- **Textos** edita las `LocSpec` en ES y EN (FR y DE opcionales) con «Rellenar vacíos con…». **Usos** lista `refs_to`. **Código** reutiliza `ClausewitzViewer` en el bloque de la entidad; editar allí es `replace_model` y se puede deshacer. **Otros campos** lista las claves desconocidas como texto editable.
- **Cintas de origen**: «Juego base» (pizarra; se copiará al guardar), «Mod» (verde), «Mod, sustituye al juego base» (ámbar), «Nuevo» (azul tinta). En los campos de historia, «desde 1836.1.1» indica un valor heredado de una fecha anterior.

### 13.6 Formularios generados (`ui/forms`)

```python
class FieldState(NamedTuple):
    origin: str        # "vanilla" | "mod" | "new" | "default" | "inherited"
    since: ClausewitzDate | None
    problems: tuple[Problem, ...]

class FieldEditor(QWidget):                       # uno por ValueType.widget
    value_committed = Signal(object)
    def set_value(self, value: object, state: FieldState) -> None
    def retranslate(self) -> None

EDITORS: dict[str, type[FieldEditor]] = {
    "int": SpinEditor, "float": DoubleSpinEditor, "bool": TriStateCheck,   # sin marcar = valor por defecto del juego
    "date": DateEditor, "word": LineEditor, "text": LineEditor, "enum": ComboEditor,
    "ref": RefPicker, "color": ColorEditor, "list": ChipsEditor, "path": FileRefEditor,
    "lockey": LocKeyEditor, "sprite": SpriteFramePicker, "picture": PicturePicker,
}

class FormBuilder:
    def __init__(self, session: "Session", *, mode: str = "simple") -> None
    def build(self, schema: EntitySchema, ref: RecordRef, *, date: ClausewitzDate | None = None) -> "EntityForm"

class EntityForm(QWidget):
    record_changed = Signal(object)               # RecordRef
    def bind(self, ref: RecordRef, date: ClausewitzDate | None = None) -> None   # re-enlace tras deshacer o cambiar fecha
    def focus_field(self, path: tuple[str, ...]) -> None
    def retranslate(self) -> None
```

- Cada `Section` es una `ParchmentCard` plegable con `QFormLayout`. Un `Group` repetible de escalares es una `RepeatedTable` con los mismos editores como delegados (partidos, regimientos, POPs, `state_building`); si está anidado, es una lista de tarjetas.
- `DynamicKeys`: `checklist` (tecnologías por carpeta y área, ordenadas por año), `grid` (un combo por grupo de reforma), `table` (TAG → valor) y `sliders` (`upper_house`, con la suma visible y aviso si no da 100).
- `Script` se ve como una frase legible y el botón «Editar condiciones…», que abre el constructor de §14.7.
- Flujo de una edición: `FieldEditor.value_committed` → `Session.edit(label, merge_key)` → `Record.set` o `HistoryView.set` (con `touch` y colocación) → `DocChanged` → reextracción del índice, validación del registro con 300 ms de espera e insignias del formulario; si es una provincia, `ProvinceFacts.update`, fila de la LUT y repintado de su caja.

### 13.7 Selectores (`ui/pickers`)

- `SymbolPicker(kind, multi=False, allow_new=False)`: desplegable con búsqueda difusa por id y por nombre localizado, muestra de color y la fila «Crear nuevo…».
- `TagPicker`: miniatura de la bandera (TGA → `QPixmap` en caché) y color del país.
- `ProvincePicker`: busca «549 Berlín» y tiene «Elegir en el mapa…» (`MapPickDialog`, selección simple o múltiple).
- `CulturePicker`: árbol por grupo. `IssuePicker`: un combo por grupo de reforma.
- `TechTreeDialog`: carpetas (army, navy, commerce, culture, industry) × áreas (de `common/technology.txt`) × filas por año, con «hasta el año ____» y «como el país…».
- `UpperHouseField` (deslizadores que suman 100), `DateEdit` (sin 29 de febrero; botones con las fechas de inicio), `ColorField` (aviso de colores parecidos a los vecinos), `LocTextField` (resalta los códigos de color `§Y…§W` y `$VAR$`), `GoodsAmountsField`, `NameListEditor` (pegar listas, quitar duplicados, comprobar cp1252) y `SpriteFramePicker`.

### 13.8 Vistas previas

- **Evento**: proporciones reales de `event_country_window.gui` (imagen de 521×203), con el fondo del juego del usuario o el procedural. Interpreta `§Y…§W` y deja `$COUNTRY$` como ficha; conmutador ES/EN. En la iteración 8 pasa a usar el renderizador `.gui` real.
- **Decisión**: imagen de 95×95 más título, descripción y condiciones en frase.
- **Bandera**: las 5 variantes, sobre la máscara de escudo si la instalación la tiene.
- **Unidad**: tarjeta de estadísticas comparada con el tipo vanilla más parecido.
- **País**: minimapa con sus provincias.

### 13.9 Mensajes y arreglos

Cada mensaje de problema lleva [Arreglar] (SimpleFix, con plan de cambios y confirmación) y [¿Por qué?] (explicador de conflicto), según §11.1. Ejemplos de tono:

- «"PRU" ya lo usa Prusia (common/countries.txt, línea 10). Prueba "PRX" o "PRS".» [Usar PRX]
- «"CON" no sirve: Windows no permite archivos llamados CON (la bandera sería CON.tga).»
- «Provincia 549 (Berlín): el dueño "PRX" no existe.» [Elegir país] [Crear PRX]
- «El id 31501 ya lo usa AUSFlavor.txt (juego base). Siguiente libre en tu rango: 200000012.» [Usar]
- «El gobierno "junta" no tiene destino en 14 tipos de rebeldes (rebel_types.txt).» [Elegir destinos]
- «27 colores de provinces.bmp no están en definition.csv (heredado del juego base).» [Ver en el mapa]

### 13.10 Estética

Se reutilizan `ParchmentCard`, `OrnateFrame`, `RibbonBadge`, `StatusBadge`, `Medallion`, `EmptyState` y `TexturedPanel`: índice de madera con remaches, formularios sobre pergamino y botón principal de terciopelo. Los iconos nuevos se dibujan con QPainter en `ui/widgets/icons_extra/<sala>.py`, registrados con el mismo decorador `_icon`, para que cada agente toque su propio archivo.

---

## 14. Las 15 capacidades

| # | Capacidad | Sala › sección | Esquemas y motores | Iteración |
|---|---|---|---|---|
| 1 | Generar `.mod` | Proyecto › Descriptor .mod / Inicio | `modfile` | 2 |
| 2 | Países | Naciones › Países (asistente + ficha) | `country_registry`, `country`, `country_colors`, `country_history`, `oob`, `diplomacy`, receta `new_country`, `gfx/flags` | 6 |
| 3 | Provincias | Mapa › Mundo | `province_history`, `pops`, `definition`, `positions`, `domain/province` | 5 (nuevas: 9) |
| 4 | Unidades terrestres | Guerra › Unidades terrestres | `unit` (vista land) | 4 |
| 5 | Decisiones | Eventos › Decisiones | `decision` + `core/script` | 7 |
| 6 | Suite de interfaces | Interfaz | `core/gui`, `gfx`, `gui_elements` | 8 |
| 7 | Eventos | Eventos › Eventos | `event`, `mtth`, `ai_chance` + `core/script` | 7 |
| 8 | Guerras de inicio | Guerra › Guerras de inicio | `war` (historia LOG), receta `new_war` | 6 |
| 9 | Casus belli | Guerra › Casus belli | `casus_belli` | 4 (condiciones con constructor: 7) |
| 10 | Bookmarks | Guerra › Fechas de inicio | `bookmark` + `lua_defines` | 4 (cámara desde el mapa: 5) |
| 11 | Gobiernos | Naciones › Gobiernos | `government` | 4 |
| 12 | Unidades navales | Guerra › Unidades navales | `unit` (vista naval) | 4 |
| 13 | Culturas | Naciones › Culturas | `culture_group` + `Children(culture)` | 4 |
| 14 | Regiones | Mapa › Regiones / Continentes y climas | `region`, `region_sea`, `continent`, `climate`, `map/groups` | 5 |
| 15 | Mapa nuevo desde cero | Mapa › Taller de mapas | `core/mapforge` (pipeline, importación, exportación y auditoría) | 9a y 9b |

### 14.1 Generar el archivo `.mod`

- **Archivos y formato.** `<juego>/mod/<Carpeta>.mod`, en cp1252 con CRLF, junto a la carpeta del mod. Ejemplo real (`VSM.mod`): `name = "Shago Mod"`, `path = "mod/VSM"`, `user_dir = "VSM"`. Admite `replace_path` (repetible) y `dependencies`, un bloque con los nombres de otros mods: `modfile.ModDescriptor.dependencies` ya lo lee y `write_descriptor` ya lo escribe (cambia el bloque solo si la lista difiere). Las claves que el descriptor no conoce se conservan.
- **Ver, crear y editar.** Proyecto › Descriptor .mod es un formulario. «Nuevo mod» crea `<juego>/mod/<Carpeta>/` con `common/`, `history/` y `localisation/`, más el descriptor, en una transacción; no copia vanilla, porque la herencia lo hace innecesario. Una opción importa una plantilla (una carpeta como `Plantilla Mod`). Editar un `.mod` existente edita su CST, así que conserva los comentarios.
- **Controles.** Sugerencia de carpeta a partir del nombre (`sanitize_folder`: «Dark Age Mod» → `DAM` o `Dark_Age_Mod`). Selector de `replace_path` entre las carpetas existentes, con el efecto explicado («el juego dejará de cargar 2 705 archivos de vanilla en history/provinces»). Ayuda: `user_dir` separa partidas y caché de las de vanilla.
- **API.**

  ```python
  @dataclass(frozen=True)
  class DescriptorSpec:
      name: str; folder: str; user_dir: str = ""
      replace_paths: tuple[str, ...] = (); dependencies: tuple[str, ...] = ()
  def render_descriptor(spec: DescriptorSpec, existing: ParseResult | None = None) -> bytes
  def descriptor_problems(spec: DescriptorSpec, game_root: Path) -> list[Problem]
  def create_mod_skeleton(project_or_guard, game_root: Path, spec: DescriptorSpec) -> ModDescriptor
  def sanitize_folder(name: str) -> list[str]      # propuestas
  ```

- **Validaciones.** `descriptor_path_mismatch` (error: `path` ≠ `"mod/<carpeta>"`), `descriptor_folder_missing` (error), `descriptor_user_dir_empty` (info), `descriptor_name_duplicate` (aviso: otro `.mod` con el mismo `name`), `replace_path_empty` y `replace_path_hides_referenced` (error), `windows_reserved_name` (error).
- **Prueba de oro.** `render_descriptor(DescriptorSpec("Shago Mod", "VSM", "VSM"))` es igual byte a byte a `tests/fixtures/shago_mod_min/VSM.mod`.

### 14.2 Países (ver, crear y editar)

- **Archivos y formato.**
  - `common/countries.txt`: `TAG = "countries/<Nombre>.txt"`; `dynamic_tags = yes` en la línea 265 y, detrás, D01–D50.
  - `common/countries/<Nombre>.txt`: `color = { r g b }`, `graphical_culture`, `party = { … }` repetido (H12), `unit_names = { <tipo> = { "n1" "n2" } }` y colores por gobierno opcionales (`fascist_dictatorship = { 40 40 40 }`).
  - `common/country_colors.txt`: colores de uniforme, opcionales (los tienen 147 de 271 TAG).
  - `history/countries/<TAG> - <Nombre>.txt`: `capital`, `primary_culture`, `culture` (repetible), `religion`, `government`, `plurality`, `nationalvalue`, `literacy`, `non_state_culture_literacy`, `civilized`, `prestige`, `ruling_party`, `last_election`, `upper_house = { <ideología> = n }`, reformas (`slavery = no_slavery`), tecnologías, invenciones, `schools`, `consciousness`, `oob`, `foreign_investment`, `decision`, `set_country_flag` y bloques fechados.
  - `history/units/<TAG>_oob.txt` (y subcarpetas por fecha): `army`, `navy`, `leader` y relaciones.
  - `history/diplomacy/*.txt`: alianzas, garantías, vasallos, subestados y uniones.
  - `gfx/flags/<TAG>{,_communist,_fascist,_monarchy,_republic}.tga`.
  - Localización: `TAG`, `TAG_ADJ`, partidos y, opcional, `TAG_<gobierno>`.
- **Ver y editar.** Lista con bandera, color, nombre localizado, origen y problemas. **Ficha nacional** (el «panel nacional»), que también se abre con doble clic en el mapa. Sus pestañas son Identidad · Banderas · Partidos · Política · Tecnologías · Territorio · Economía · Ejército · Diplomacia · Textos, y todas trabajan en la **fecha de trabajo**:
  - **Política**: gobierno, partido gobernante (filtrado por el archivo del TAG), reformas, cámara alta, pluralidad, prestigio y valor nacional.
  - **Economía**: `state_building` de sus provincias agrupadas por estado, y `foreign_investment`.
  - **Ejército**: el editor de OOB (ejércitos y flotas con ubicación, regimientos con tipo y provincia de origen, barcos y líderes).
  - **Diplomacia**: `history/diplomacy` filtrado por `first`/`second`.
- **Crear: asistente «Nuevo país»** (receta `new_country`). Cada paso se valida en vivo y se puede volver atrás:
  1. **Identidad**: nombre y adjetivo ES/EN; TAG sugerido (`suggest_tags("Somalia")` → SOM, SOL, SMA) y validado en vivo; «basar en…» un país existente para rellenar el resto.
  2. **Color y banderas**: color de mapa (aviso si se parece al de un vecino), `graphical_culture` y colores de uniforme opcionales. `FlagStudio` importa PNG, JPG o TGA y los encuadra (cubrir, contener o estirar, con punto focal), con una imagen común o una por variante y vista previa de las 5.
  3. **Pueblo**: cultura principal y aceptadas (con «Crear cultura…» en línea) y religión.
  4. **Partidos**: plantilla con un partido por ideología (`start_date = 1830.1.1`, `end_date = 2000.1.1`, las fechas más habituales en vanilla) o «Copiar partidos de PRU», que renombra el prefijo.
  5. **Gobierno y sociedad**: gobierno, partido gobernante, reformas políticas y sociales (también económicas y militares si no es civilizado), cámara alta, pluralidad, alfabetización, prestigio, valor nacional, escuela tecnológica y `civilized`.
  6. **Tecnologías**: `TechTreeDialog` con las plantillas «civilizado 1836», «no civilizado» y «como <país>».
  7. **Territorio y ejército** (opcional): brocha de dueño en el mapa (clic = dueño y controlador; la casilla «también núcleo» añade el núcleo), capital entre las provincias propias y OOB inicial.
  8. **Revisión**: plan de cambios con diff. «Crear país» lo aplica en una transacción deshacible y, si «Guardar al terminar» está marcado (lo está por defecto), guarda.

  Archivos que toca: `common/countries.txt` (+1 línea antes de `dynamic_tags`), `common/countries/<Nombre>.txt`, `common/country_colors.txt` (opcional), `history/countries/<TAG> - <Nombre>.txt`, `history/units/<TAG>_oob.txt` (opcional), 5 `gfx/flags/<TAG>*.tga`, las `history/provinces/...` reasignadas y `localisation/00_<P>_countries.csv`.
- **Controles especiales.** `TagPicker`, `FlagStudio` (`core/gfx/flags.py`: `fit_flag(img, *, mode="cover", focus=(0.5, 0.5))`, `make_flag_set(images) -> dict[str, bytes]`: TGA de 32 bits, 93×64, origen abajo a la izquierda, releídas con Pillow), `TechTreeDialog`, `IssuePicker`, `UpperHouseField`, `ColorField` y minimapa.
- **Validaciones.** `tag_invalid`, `tag_taken`, `tag_not_registered`, `tag_after_dynamic_tags`, `country_file_missing`, `country_history_missing`/`_duplicate`, `ruling_party_not_of_country`, `ruling_party_ideology_not_allowed`, `ruling_party_inactive` (fechas del partido), `party_unknown_policy`, `party_missing_ideology` (info), `upper_house_sum`, `capital_not_owned` (solo para los TAG con tierra: en vanilla, 90 de las 220 capitales están en provincias de otro país), `nationalvalue_unknown` y demás `*_unknown`, `flag_missing`/`flag_format`, `country_colors_missing` (info), `map_color_duplicate` (info), `oob_file_missing`, `army_location_sea`, `navy_location_inland` y `regiment_type_mismatch`.

### 14.3 Provincias (ver, crear y editar)

- **Archivos y formato.** `history/provinces/<carpeta>/<id> - <Nombre>.txt` (`owner`, `controller`, `add_core`, `remove_core`, `trade_goods`, `life_rating`, `terrain`, `railroad`, `fort`, `naval_base`, `colonial`, `colony`, `is_slave`, `state_building`, `party_loyalty` y bloques fechados). `history/pops/<fecha>/<Zona>.txt` (`<id> = { <tipo_pop> = { culture religion size [militancy] [rebel_type] } }`). La fila de `map/definition.csv` (color y nombre), `map/positions.txt` y la clave `PROV<id>`.
- **Ver y editar.** Mapa › Mundo. Un clic abre el panel de provincia con las pestañas Resumen · Historia · POPs · Edificios · Textos, en la fecha de trabajo. La brocha asigna dueño, controlador, núcleo, RGO, life rating, terreno, ferrocarril, fuerte o base naval con clic o arrastre. Mayúsculas + clic hace multiselección y «Rellenar estado» asigna toda la región. La línea temporal muestra los bloques fechados y permite editar un suceso concreto.
- **POPs.** Tabla con tipo, cultura, religión, tamaño y totales, más «copiar POPs de la provincia…» y «escalar ×». Se edita el bloque en el archivo que lo define (al guardar se copia ese archivo de zona). Las provincias nuevas van a `history/pops/<fecha>/00_<P>_pops.txt`. Un bloque repetido (2482) se muestra dos veces y se edita el elegido.
- **Crear.** Provincias nuevas en un mapa existente («Dividir provincia» y «Pintar provincia nueva») en la iteración 9b (§18.10). Una provincia sin historia recibe `history/provinces/<carpeta de su región o «studio»>/<id> - <Nombre>.txt`.
- **Controles especiales.** `ProvincePicker` con «Elegir en el mapa», `PopsEditor`, `TimelineBar` y deslizador de life rating; modo «IDs» que dibuja el número de cada provincia en su centroide (como la imagen de referencia de HoD del usuario).
- **Validaciones.** `province_not_in_definition`, `province_history_duplicate`, `province_file_name` (info), `sea_province_has_owner`/`_has_pops`, `naval_base_inland` (sin vecino de mar en el ráster), nivel de edificio ≤ `max_level` de `buildings.txt`, `tag_unknown`, `goods_unknown`, `terrain_unknown`, `pop_size_invalid`, `pop_culture_unknown`/`_religion_unknown`/`pop_type_unknown` y `missing_prov_localisation`.

### 14.4 Unidades terrestres

- **Archivos y formato.** `units/<id>.txt`, un tipo por archivo (11 con `type = land`): `icon`, `sprite` (actor `<cultura gráfica><sprite>` de `interface/*.gfx`), `active`, `unit_type` (infantry, cavalry, support, special), `floating_flag`, `priority`, `max_strength`, `default_organisation`, `maximum_speed`, `weighted_value`, `build_time`, `build_cost = { <bien> = n }`, `supply_consumption`, `supply_cost = { … }`, `reconnaissance`, `attack`, `defence`, `discipline`, `support`, `maneuver`, `siege`, `sprite_mount*` y sonidos. Se activa con `activate_unit = <id>` en `technologies/*.txt` e `inventions/*.txt`. Localización: `<id>` y `<id>_short`.
- **Ver, crear y editar.** Guerra › Unidades terrestres (esquema `unit`, vista land). «Nueva unidad basada en infantry» duplica el bloque en `units/<id>.txt` y crea sus claves. Tarjeta de estadísticas comparada con la base.
- **Controles especiales.** `GoodsAmountsField` para costes y suministros, selector del actor de sprite y `ActivateUnit` (dónde se desbloquea y cambiarlo, lo que copia el archivo de tecnología al guardar).
- **Validaciones.** `unit_never_active` (info: `active = no` y ningún `activate_unit`), `unit_type` fuera de su lista, `sprite_missing`, `goods_unknown`, `duplicate_id` y, en los OOB, `regiment_type_mismatch`.

### 14.5 Decisiones

- **Archivos y formato.** `decisions/*.txt` (29 archivos, 151 decisiones): `political_decisions = { <id> = { picture potential = { } allow = { } effect = { } ai_will_do = { factor modifier } [alert] [news] } }`. Imagen: `gfx/pictures/decisions/<id>.dds` (95×95); si falta `picture`, vale el id (H21). Localización: `<id>_title` y `<id>_desc`.
- **Ver, crear y editar.** Eventos › Decisiones: lista y editor con Requisitos (`potential`, `allow` con el constructor), Efecto (constructor de efectos), IA (`ai_will_do` con modificadores), Imagen y Textos, más la vista previa. Lo nuevo va a `decisions/<P>_decisions.txt` dentro de `political_decisions`. Editar una de vanilla copia el archivo entero a la misma ruta.
- **Controles especiales.** `PicturePicker` con importación (PNG → DDS de 95×95 sin comprimir), `TriggerBuilder`, `EffectBuilder` y frase legible.
- **Validaciones.** `decision_picture_missing` (info; 4 heredados), `loc_key_missing`, `decision_duplicate`, errores de ámbito y `unclosed_block` con el arreglo «Añadir `}` al final»: las dos decisiones rotas del usuario se abren en modo texto y el arreglo habilita el formulario.

### 14.6 Suite de modificación de interfaces

Ver §17. Archivos: `interface/*.gui`, `interface/*.gfx`, `gfx/interface/**`, `gfx/pictures/**` y `gfx/fonts/*.fnt`. Se ven y se modifican las ventanas existentes (mover, redimensionar, cambiar sprites, textos y fuentes) y se crean sprites a partir de imágenes propias. Validaciones: `sprite_missing`, `texture_missing`, `sprite_duplicate` (info; 13 heredados), `gui_orientation_unknown` y `gui_named_element_removed`.

### 14.7 Eventos

- **Archivos y formato.** `events/*.txt` (82 archivos, 1 064 eventos): `country_event`/`province_event = { id title desc picture fire_only_once is_triggered_only major news news_desc_long/medium/short election issue_group trigger = { } mean_time_to_happen = { months|days|years modifier = { factor … } } immediate = { } option = { name ai_chance = { factor modifier } <efectos> } }`. Imágenes: `gfx/pictures/events/*.tga` (521×203). Localización según la convención de vanilla: `EVTNAME<id>`, `EVTDESC<id>`, `EVTOPTA<id>`, `EVTOPTB<id>`… (2 eventos de `ACW.txt` usan texto literal en lugar de claves, y se respeta).
- **Ver, crear y editar.** Event Studio: lista filtrable (archivo, tipo, origen, id, texto) y editor con General · Condiciones · MTTH · Inmediato · Opciones · Textos · Código, con vista previa en vivo y frase legible. «Nuevo evento» pide el tipo y el archivo de destino (existente o `events/<P>_<tema>.txt`) y toma el id de `EventIdAllocator`. Los eventos de vanilla se abren igual y, al editarlos, su archivo se copia entero al mod.
- **Controles especiales.**
  - **Constructor de condiciones** (`TriggerBuilder`): árbol con grupos TODAS/ALGUNA/NINGUNA (AND/OR/NOT) en corchetes de color. «+ Condición» abre un buscador por categorías (País, Provincia, Tiempo, Tecnología, Política, Economía, Diplomacia, Población, Banderas) con etiqueta ES/EN y clave cruda. El control del valor depende del tipo del catálogo. «+ Ámbito» añade `capital_scope`, `any_owned_province`, `FRA = { }`, `369 = { }`… «Texto» edita el nodo como Clausewitz con diagnósticos. Los nodos sin catalogar se ven como «Condición no catalogada» y se conservan.
  - **MTTH**: base en meses, días o años, más modificadores (factor + constructor), con el tiempo efectivo calculado.
  - **Opciones**: tarjetas con el texto ES/EN, un `EffectBuilder` (mismo modelo, ámbitos de efecto) y `ai_chance`.
  - Los campos `news_desc_*` solo aparecen con `news = yes`.
- **Validaciones.** `event_id_duplicate`, `event_id_out_of_range`, `event_ref_missing`, `event_picture_missing`, `loc_key_missing`, `script_unknown_key` (info), `scope_mismatch` (condición de país dentro de un ámbito de POP), `mtth_missing` (evento no disparado sin MTTH) y `option_without_name`.

### 14.8 Guerras de inicio

- **Archivos y formato.** `history/wars/<Nombre>.txt` (5 en vanilla): `name = "…"` (comentado en `ACW.txt`) y bloques fechados con `add_attacker`, `add_defender`, `rem_attacker`, `rem_defender` y `war_goal = { casus_belli actor receiver [state_province_id] [country] }`.
- **Ver, crear y editar.** Guerra › Guerras de inicio: lista y editor en línea temporal (historia en modo LOG). Asistente «Nueva guerra» (receta `new_war`):
  1. **Nombre y fecha de inicio**: botones rápidos con las fechas de `bookmarks.txt`; `DateEdit` no permite pasar de `end_date`.
  2. **Bandos**: atacantes y defensores con `TagPicker` múltiple (el primero de cada lista es el líder) y un minimapa con los bandos en rojo y azul.
  3. **Objetivos**: una tarjeta por `war_goal`, con el CB (y su descripción localizada), actor y receptor (que deben estar en la guerra), `state_province_id` («Elegir en el mapa») y `country`. Los campos visibles dependen de las `po_*` del CB.
  4. **Fin** (opcional): una fecha que genera `rem_attacker`/`rem_defender`.
  5. Se escribe `history/wars/<P>_<nombre>.txt` con el formato de `ACW.txt`.
- **Validaciones.** `war_participant_unknown`, `wargoal_cb_unknown`, `wargoal_actor_not_in_war`, `wargoal_state_required`, `war_dates_order` y `war_inactive_at_bookmarks` (aviso: la guerra termina antes de la primera fecha de inicio o empieza después de `end_date`).

### 14.9 Casus belli

- **Archivos y formato.** `common/cb_types.txt`: `peace_order = { … }` y bloques de CB (H17) con `sprite_index`, `is_triggered_only`, `months`, `constructing_cb`, `crisis`, `mutual`, `great_war_obligatory`, `all_allowed_states`, `always`, `is_civil_war`, `construction_speed`, `truce_months`, factores (`badboy_factor`, `prestige_factor`, `peace_cost_factor`, `penalty_factor`, `break_truce_*`, `good_relation_*`, `tws_battle_factor`), 18 `po_*`, `war_name` y los bloques de guion `can_use`, `is_valid`, `allowed_states`, `allowed_states_in_crisis`, `allowed_substate_regions`, `allowed_countries`, `on_add` y `on_po_accepted`.
- **Ver, crear y editar.** Guerra › Casus belli con el editor genérico: secciones General, Factores, Opciones de paz (casillas), Condiciones, Efectos y Textos (`<cb>`, `<cb>_desc`, `<cb>_setup`, `<cb>_short`, más `NORMAL_`/`AGRESSION_<war_name>` compartidas). Plantilla «basar en acquire_state». Crear un CB lo añade al final de `peace_order` (compañero) y borrarlo lo quita. Hasta la iteración 7, los bloques de guion se editan como código con diagnósticos.
- **Controles especiales.** `SpriteFramePicker` con los fotogramas de `GFX_diplo_wargoal_icons` leídos del juego del usuario.
- **Validaciones.** `cb_not_in_peace_order` (con arreglo), `peace_order_unknown` (`annex`, heredado), `remove_cores_needs_transfer` (regla documentada en la cabecera del propio archivo: `po_remove_cores` exige `po_transfer_provinces`, `po_demand_state` o `po_annex`), `loc_key_missing` y `cb_unknown` en las guerras.

### 14.10 Bookmarks (fechas de inicio)

- **Archivos y formato.** `common/bookmarks.txt`: `bookmark = { name = "GC_NAME" desc = "GC_DESC" date = 1836.1.1 cameraX = 2950 cameraY = 1550 }` (2 en vanilla; las comillas se conservan). `common/defines.lua`: `start_date`, `end_date`.
- **Ver, crear y editar.** Guerra › Fechas de inicio con el editor genérico: nombre y descripción (`LocKey`), fecha y cámara. Desde la iteración 5, «Usar la vista actual del mapa» rellena la cámara en coordenadas del juego. Las fechas de los bookmarks alimentan el selector global de fecha de trabajo. Si la fecha pasa de `end_date`, se ofrece ampliarla editando solo ese token de `defines.lua`.
- **Validaciones.** `bookmark_date_outside_defines` (error), `bookmark_without_pops` (aviso: no hay `history/pops/<fecha ≤ bookmark>`; qué carpeta usa el juego es [verificar en juego]), `bookmark_camera_outside_map` y `loc_key_missing`.

### 14.11 Gobiernos nuevos

- **Archivos y formato.** `common/governments.txt` (H16), `common/rebel_types.txt` (14 tablas `government = { }`), localización `<id>` y `<id>_ruler` (y `TAG_<id>` por país, opcional), banderas `TAG_<flagType>.tga`.
- **Ver, crear y editar.** Naciones › Gobiernos (§10.10): casillas de ideologías del índice, elecciones (la duración solo aparece si hay elecciones), `appoint_ruling_party` y `flagType` o ninguno («usa TAG.tga»). Al crear, la **matriz de rebeldes** (tipo de rebelde × gobierno de destino) pide los destinos, con uno propuesto por defecto. La pestaña Textos de cada país ofrece el nombre `TAG_<gobierno>`.
- **Validaciones.** `government_without_ideology` (error), `government_election_without_duration` (aviso), `government_missing_in_rebel_map` (error con arreglo), `government_flagtype_unknown`, banderas que faltan para los países que lo usan (info) y `loc_key_missing`.

### 14.12 Unidades navales

- **Archivos y formato.** `units/<id>.txt` con `type = naval` (10): los campos comunes más `naval_icon`, `sail`/`steam`, `capital`, `colonial_points`, `can_build_overseas`, `min_port_level`, `limit_per_port`, `supply_consumption_score`, `hull`, `gun_power`, `fire_range`, `evasion`, `torpedo_attack` y `transport`; `unit_type` big_ship, light_ship o transport. Los países nombran sus barcos en `unit_names` por tipo.
- **Ver, crear y editar.** Guerra › Unidades navales: el mismo esquema `unit` con la vista naval (`Variant` por `type`). Al crear una unidad, `UnitNamesSlot` ofrece añadir su lista de nombres en los países.
- **Validaciones.** Las de las terrestres, más `min_port_level` frente al `max_level` de `naval_base` y, en los OOB, `navy_location_inland`.

### 14.13 Culturas

- **Archivos y formato.** `common/cultures.txt` (34 grupos, 226 culturas): `<grupo> = { leader = european unit = EuropeanGC union = GER is_overseas = no <cultura> = { color = { r g b } first_names = { … } last_names = { … } radicalism = n primary = TAG } }`.
- **Ver, crear y editar.** Naciones › Culturas: árbol por grupo con los campos del grupo y de la cultura. Mover una cultura de grupo quita y añade el bloque conservando su texto. Hay «Crear cultura…» en línea desde el asistente de países.
- **Controles especiales.** `NameListEditor` (pegar listas, quitar duplicados, comprobar cp1252) y `ColorField` con aviso de color repetido.
- **Validaciones.** `culture_name_duplicate` (en todos los grupos), `culture_group_union_unknown`, `color_duplicate` (info), nombres no representables en cp1252 y `loc_key_missing` (cultura y grupo).

### 14.14 Regiones

- **Archivos y formato.** `map/region.txt` (549 estados, `PRU_549 = { 549 550 551 552 681 }`), `map/region_sea.txt` (solo CR, con regiones vacías), `map/continent.txt` (6) y `map/climate.txt` (claves emparejadas). Localización `<región>` (`PRU_549;Brandenburg`).
- **Ver, crear y editar.** Mapa › Regiones: modo de mapa «región» y brocha de regiones (se elige un estado y cada clic mueve la provincia). Cada movimiento es una edición compuesta que quita la provincia de A y la añade a B, de modo que «exactamente un estado» se cumple tras cada paso. Crear un estado (nombre `<TAG>_<primera provincia>` y su clave), renombrar (muestra los usos como ámbito, p. ej. `TUR_860 = { }`) y borrar (exige que esté vacío). Continentes y climas se editan con brocha o lazo.
- **API.**

  ```python
  class ProvinceGroups:                 # core/map/groups.py
      def __init__(self, ws: Workspace, rel: VPath, *, layout: str = "flat")   # "flat" | "provinces_key" | "paired"
      def groups(self) -> list[str]; def members(self, gid: str) -> list[int]; def group_of(self, pid: int) -> str | None
      def move(self, pid: int, gid: str) -> None
      def create(self, gid: str, members: Iterable[int]) -> None
      def rename(self, old: str, new: str) -> None; def delete(self, gid: str) -> None
  ```

- **Validaciones.** `land_province_without_region`, `province_multiple_regions`, `sea_in_region`, `province_without_continent`, `region_empty` (info), `region_not_contiguous` (info), `climate_layout` y `loc_key_missing`.

### 14.15 Taller de mapas: generar o importar un mapa nuevo y sus recursos

- **Archivos y formato.** La lista exacta, en orden y por nivel, está en §18.8:
  - todo `map/` salvo lo que se hereda (`terrain.txt`, `trees.txt`, texturesheets y teselas);
  - las 4 texturas `colormap*`, con las cabeceras de vanilla, y el minimapa;
  - `history/provinces` y `history/pops`, OOB vacíos para cada `oob` citado y `capital` corregida en las historias de los TAG existentes;
  - con el nivel Mundo, además: `common/countries.txt` (los TAG existentes se conservan), `common/countries/*`, `history/countries/*` nuevos, `common/cultures.txt` y las banderas TGA (5 por país);
  - la cámara de `bookmarks.txt`, la localización (EN y ES, con copia opcional a FR y DE) y los `replace_path` del descriptor;
  - el traslado a la papelera de los archivos del propio mod bajo las carpetas reemplazadas.
  
  Es una sola transacción con diario y `.bak`. Destino: este mod o un mod nuevo, que es el recomendado si el mod ya tiene `history/`.
- **Ver, crear y editar.** Mapa › Taller de mapas. Hay tres niveles:
  - **Solo mapa**: reparto entre TAG existentes (por defecto) o mapa base no jugable;
  - **Mundo**;
  - **Sobre vanilla**: provincias nuevas o un continente nuevo en una caja de océano.
  
  Y cuatro orígenes:
  - **Generar**: pipeline procedural al estilo de Azgaar;
  - **Importar bitmaps**: lo que falta se reconstruye;
  - **Altura**: un PNG en gris;
  - **FMG JSON**: «Export to JSON → Full» (iteración 9b).
  
  El asistente tiene un modo sencillo de 4 controles con «Generación rápida» y un modo avanzado. Hay vista previa en vivo a W/4 (1,6–1,75 s) y edición entre pasos: pinceles de relieve y tierra/mar, mover fronteras, dividir y fusionar, pintar dueños y culturas, renombrar y bloquear.
  
  Todo se calcula en un proceso trabajador: la interfaz nunca se bloquea más de 50 ms. El mundo se guarda en el proyecto y es determinista por semilla, también entre CPU distintas. El render final se puede cancelar (unos 15 s a 5616×2160). Después, el mapa se edita en el editor de mapa (§16); al volver al taller, los cambios se detectan por sha.
- **Controles especiales.**
  - Galería de plantillas y editor de plantillas con la sintaxis de FMG.
  - Pinceles en coordenadas normalizadas.
  - Tablas bioma → terreno, terreno → RGO y presencia de tipos de POP.
  - Herramientas de provincia y enlace al editor de píxeles de §16.
  - Selector de fuente de nombres por grupo y galería de banderas.
  - Ranuras de importación con detección de orientación y matriz «lo que falta se reconstruye».
  - Lista de estrechos sugeridos.
  - Plan de cambios con clase A/B/C y movimientos a la papelera.
  - Auditoría por carpeta y rol con [replace_path] [Vaciar] [Papelera] [Ignorar].
- **Validaciones.** Las de §16.6 sobre el resultado, más la familia `mapforge` (§18.11), cada una con SimpleFix y explicador:
  - de destino y jugabilidad: `replace_path_mod_files_remain` y `forge_no_owned_provinces`;
  - del bitmap: `forge_orientation_suspect`, `forge_not_24bit`, `forge_size`, `forge_color_reserved`, `forge_tiny_province`, `forge_seam_province` y `province_isolated`;
  - de tierra y mar: `forge_land_sea_unknown` y `forge_land_sea_ambiguous`;
  - de terreno y ríos: `terrain_not_indexed`, `rivers_not_indexed`, `terrain_index_invalid`, `terrain_index_placeholder`, `rivers_diagonal`, `rivers_in_water` y `river_source_missing`;
  - de altura y FMG: `heightmap_size`, `fmg_version_unknown` y `fmg_aspect`;
  - de límites, ediciones y exportación: `forge_too_many_provinces`, `forge_edit_conflict`, `forge_env_changed`, `forge_export_conflict`, `forge_loc_shadowed` y `forge_overlay_sea_shrunk`.
  
  Antes de confirmar, la auditoría de dependencias (§18.9) recorre todo el índice por rol (provincia, estado, continente, TAG, cultura y religión).
- **Iteraciones.**
  - **9a:** mapa procedural, importación de bitmaps, Solo mapa jugable con TAG existentes y proceso trabajador.
  - **9b:** Mundo, FMG JSON, banderas y Sobre vanilla.

### 14.16 Requisitos originales: dónde quedan cubiertos

| Requisito | Dónde |
|---|---|
| Herencia vanilla + mod (vanilla solo lectura, todo al mod creando subcarpetas) | §5, §6 (iteración 2) |
| Editor de mapa: modos político, RGO, infraestructura, life rating y terreno; edición por clic de owner, controller, add_core, trade_goods, life_rating, terrain, railroad, fort, naval_base y POPs | §14.3, §16 (iteración 5) |
| Panel nacional: tecnologías, reformas, partido, upper_house, prestigio, pluralidad, economía y OOB | §14.2 (iteración 6) |
| Asistente de países: TAG validado y registrado, color, 5 banderas TGA, partidos, nombres de unidades, history/countries | §14.2 (iteración 6) |
| Event Studio: eventos de país y de provincia, AND/OR/NOT con buscadores, MTTH con modificadores, opciones con efectos y ai_chance | §14.7 (iteración 7) |
| Editor CSV editable con sincronización automática de claves | §8 y sala Textos (iteración 3); cada suite añade sus `LocSpec` |

---

## 15. Validación global y renombrado seguro

- `Validator.validate` reúne la sintaxis, los validadores de cada esquema, las referencias desconocidas (`Ref` contra el índice), la coherencia del mapa (§16.6), la localización y los avisos de mod (UTF-8, copias idénticas o degradadas). Proyecto › Validación reutiliza `ValidationPanel` con columnas de entidad, el conmutador de heredados y los botones [Arreglar].
- **Renombrado seguro** (`Entities.rename`): muestra los usos (`refs_to`), reescribe las referencias en una transacción y renombra las claves de localización que siguen la plantilla (las `shared` no). Ejemplo: renombrar el TAG AAA a AAB reescribe el registro, la historia, los dueños de provincia, las guerras y las claves.

---

## 16. Editor de mapa (mapas existentes)

### 16.1 Núcleo (`core/map`)

```python
# bmp.py: lector y escritor propios con numpy; write(read(b)) == b
def read_bmp(data: bytes) -> "BmpImage"            # 24 bits o 8 bits con paleta; filas de abajo arriba
def write_bmp(img: "BmpImage") -> bytes            # mismo orden de filas, relleno a 4 bytes y paleta (1 078 B de cabecera en 8 bits)

# definition.py (sobre tablecsv)
@dataclass
class DefinitionRow: line: int; id: int | None; rgb: tuple[int, int, int]; name: str; raw: str
class DefinitionTable:
    @classmethod
    def parse(cls, text: str) -> tuple["DefinitionTable", list[Problem]]   # tolera "223.", filas sin id y cabecera
    def id_of(self, rgb) -> int | None; def rgb_of(self, pid: int) -> tuple[int, int, int]; def ids(self) -> list[int]
    def add(self, pid: int, rgb, name: str) -> None
    def to_source(self) -> str                       # sin pérdidas en las filas no tocadas

# raster.py: la fila del array es la y del juego (H1)
@dataclass
class ProvinceRaster:
    ids: np.ndarray            # (H, W) uint16
    pixel_count: np.ndarray    # (N+1,)
    bbox: np.ndarray           # (N+1, 4): x0 y0 x1 y1
    centroid: np.ndarray       # (N+1, 2)
    unknown: list[tuple[tuple[int, int, int], int, tuple[int, int]]]   # color, píxeles, muestra
    @classmethod
    def build(cls, rgb: np.ndarray, table: DefinitionTable, *, progress=None, cancelled=None) -> "ProvinceRaster"
        # LUT densa color → id (2^24 entradas uint16); los colores sin fila dan 0 y se listan en unknown
    def at(self, x: int, y: int) -> int
    def neighbors(self, *, wrap_x: bool = True) -> dict[int, frozenset[int]]   # el mapa es cíclico en horizontal
    def border_mask(self, group_lut: np.ndarray | None = None) -> np.ndarray
def to_display_row(y: int, height: int) -> int       # H-1-y: único punto de conversión

# facts.py: datos compactos para los modos, sin mantener CST
@dataclass
class ProvinceFacts:           # arrays por id, calculados con HistoryView a la fecha de trabajo
    owner: np.ndarray; controller: np.ndarray; trade_goods: np.ndarray; life_rating: np.ndarray
    railroad: np.ndarray; fort: np.ndarray; naval_base: np.ndarray; terrain: np.ndarray
    region: np.ndarray; continent: np.ndarray; is_sea: np.ndarray; population: np.ndarray
    def update(self, pid: int, record: Record, date: ClausewitzDate) -> None

# modes.py: también declarativos
@dataclass(frozen=True)
class MapMode:
    key: str; label: str
    lut: Callable[[ProvinceFacts, SymbolIndex], np.ndarray]    # (N+1,) uint32 0xAARRGGBB
    legend: Callable[[ProvinceFacts, SymbolIndex], list["LegendItem"]]
```

`cache.py` guarda el ráster en `.npy` en la carpeta de caché, con la clave sha1 del BMP más `definition.csv`.

### 16.2 Modos de mapa

| Modo | Color |
|---|---|
| Político | `color` de `common/countries/<país>.txt` del dueño |
| RGO | color del bien en `goods.txt` |
| Infraestructura | degradado por `railroad` (0 a `max_level`) |
| Life rating | degradado de 0 a 100 |
| Terreno | la anulación `terrain` o el índice mayoritario de `terrain.bmp` (bincount de `id*256 + índice`), según `terrain.txt` |
| Regiones, continentes y climas | color por hash del grupo |
| Culturas y religiones | las del POP mayoritario |
| Núcleos | los del TAG elegido |
| Población | escala logarítmica |
| Problemas | provincias con algún `Problem` |
| IDs | número de cada provincia en su centroide (zoom alto) |

### 16.3 Lienzo (`ui/map/canvas.py`)

- `QGraphicsView` con un `QGraphicsPixmapItem`. La imagen sale de `np.take(lut, ids_mostrados)` como `QImage` `Format_RGB32` sin copia (`ARCHITECTURE.md` §1.4), con la vista volteada (`np.flipud` una vez por ráster).
- Encima van capas de fronteras (provincia, estado y país), la selección y las etiquetas.
- `refresh(pids)` repinta solo las cajas envolventes afectadas. `pick_mode` sirve a los selectores.
- Herramientas: selección, brocha (por campo), relleno de estado, regiones, estrechos y cámara de bookmark.

### 16.4 Estrechos y canales

`core/map/adjacency.py` lee y escribe `adjacencies.csv` de forma tolerante y sin pérdidas (la cabecera es un comentario, `#From;To;Type;Through;Data;Comment`, y hay líneas `#` de sección). En vanilla hay 63 `sea` activas (y 3 comentadas), 18 `impassable` y 3 `canal` (Kiel, Suez y Panamá, con `Data` 1–3). Herramienta: clic en tierra A, clic en tierra B y clic en el mar intermedio, que crea `A;B;sea;MAR;0;Comentario`; también se pueden marcar `impassable` y `canal`. Se valida contra los vecinos del ráster (`adjacency_unknown_province`, `adjacency_bad_type`, `adjacency_through_not_sea`).

### 16.5 Rendimiento (criterios)

- Primera carga del ráster de vanilla en segundo plano: ≤ 4 s. Medido: 0,9 s leyendo el BMP y traduciendo colores con una LUT densa `uint16` de 2^24 entradas (32 MB); con `np.searchsorted`, 1,5 s, y con `np.unique(return_inverse=True)`, 3,2 s. El censo de colores de la importación del taller (§18.6) usa `np.unique` sin `return_inverse` más la misma LUT densa: 0,62–0,83 s con el BMP de vanilla. Desde la caché `.npy`: ≤ 0,5 s.
- Cambio de modo ≤ 150 ms. Repintado tras cambiar un dueño ≤ 50 ms.
- Los centroides (unos 0,9 s por eje con `bincount` ponderado) se calculan una vez y se guardan en la caché.

### 16.6 Invariantes de coherencia (`core/map/coherence.py: check_map(vfs) -> list[Problem]`)

`bmp_size_mismatch`, `bmp_color_unmapped` (píxeles y muestra), `definition_color_duplicate`, `duplicate_id`, `definition_bad_number`, `definition_id_ge_max`, `province_without_pixels`, `max_provinces_too_small`, `sea_start_unknown`, `sea_start_duplicate`, `land_province_without_region`, `province_multiple_regions`, `sea_in_region`, `province_without_continent`, `climate_layout`, `positions_missing`, `missing_history`, `province_history_duplicate`, `province_file_name`, `adjacency_unknown_province`, `adjacency_through_not_sea`, `terrain_sea_mismatch`, `missing_prov_localisation` y `province_fragmented`. Sobre vanilla, el resultado se compara con una instantánea de «problemas conocidos» (la línea base). El taller añade la familia `mapforge` (§18.11).

---

## 17. Suite de interfaces

### 17.1 Modelo (`core/gui`)

```python
@dataclass(frozen=True)
class Sprite:
    name: str; kind: str        # spriteType, textSpriteType, corneredTileSpriteType, maskedShieldType, progressbartype…
    texture: str; texture2: str | None; frames: int; border: tuple[int, int] | None
    rel: VPath; line: int; resolved: VPath | None   # textura encontrada (con extensión alternativa) o None

class SpriteDB:
    @classmethod
    def build(cls, vfs: VirtualFS, ws: Workspace) -> "SpriteDB"   # todos los interface/*.gfx, claves sin mayúsculas
    def get(self, name: str) -> Sprite | None
    def duplicates(self) -> dict[str, list[Sprite]]
    def usages(self, name: str) -> list[tuple[VPath, int]]        # .gui que lo usan

@dataclass
class GuiElement:
    entry: Entry; type: str; name: str; children: list["GuiElement"]
    position: tuple[int, int]; size: tuple[int, int] | None; orientation: str
    sprite: str | None; text: str | None; font: str | None; format: str | None

class GuiDocument:
    def __init__(self, doc: Document) -> None          # claves sin distinguir mayúsculas; al escribir conserva la grafía
    def windows(self) -> list[GuiElement]
    def find(self, path: str) -> GuiElement
    def set_position(self, el: GuiElement, x: int, y: int) -> None   # Block.set sobre position = { x = y = }
    def set_size(self, el: GuiElement, w: int, h: int) -> None

def layout(window: GuiElement, screen: tuple[int, int]) -> dict[int, "Rect"]
    # anclajes UPPER_LEFT, UPPER_RIGHT, LOWER_LEFT, LOWER_RIGHT, CENTER, CENTER_UP, CENTER_DOWN;
    # un valor desconocido (UPPERL_LEFT) se trata como UPPER_LEFT con aviso

class BMFont:                                          # gfx/fonts/*.fnt + .tga de la instalación del usuario
    @classmethod
    def load(cls, fnt_text: str, atlas: "Image.Image") -> "BMFont"
    def render(self, text: str, *, max_width: int, align: str, color_codes: Mapping[str, tuple[int, int, int]]) -> "Image.Image"
```

`textures.py` carga DDS (sin comprimir, DXT1/3/5) y TGA con Pillow, normaliza `\\` y mayúsculas, prueba la extensión alternativa (`.tga`↔`.dds`, H23), recorta los fotogramas (`noOfFrames`), hace el 9-slice de `corneredTile` y mantiene una caché LRU. `core/gfx/dds.py` escribe DDS A8R8G8B8 sin comprimir (cabecera de 128 bytes); si la versión de Pillow sabe escribir DXT, se ofrece como opción.

### 17.2 Lienzo y edición (`ui/interface`)

- `GuiCanvas` muestra la ventana a la resolución elegida (1024×768, 1280×720 o 1920×1080). Cada elemento es un `QGraphicsItem` con asas: arrastrar actualiza `position` según el anclaje y las asas cambian `size`. Hay rejilla e imán; los elementos sin sprite se dibujan con línea discontinua y su nombre.
- `GuiTree` muestra la jerarquía, sincronizada con el lienzo.
- El formulario de propiedades lo generan los esquemas de `core/schemas/gui_elements.py` (windowType, guiButtonType, iconType, instantTextBoxType, textBoxType, checkboxType, listboxType, scrollbarType, positionType, OverlappingElementsBoxType, editBoxType, shieldtype, eu3dialogtype), con `ignore_case=True`.
- Editar un `.gui` de vanilla copia el archivo entero al mod con el mismo nombre. Sin juego configurado, el lienzo usa el estilo procedural.

### 17.3 Sprites e imágenes

- `SpriteBrowser`: rejilla de miniaturas con buscador, filtro por archivo, usos y duplicados.
- «Nuevo sprite»: importa un PNG, lo convierte a DDS sin comprimir en `gfx/interface/<P>/` y crea el `spriteType` en `interface/<p>_studio.gfx`. Pide fotogramas y borde si es «cornered».
- `PictureManager` agrupa las imágenes de evento (TGA 521×203), de decisión (DDS 95×95), banderas (TGA 93×64), tecnologías, noticias y pantallas de carga. El tamaño esperado de cada carpeta se calcula con el más común de vanilla. Se importa con encuadre y vista previa dentro del marco real.

### 17.4 Límites que se explican al modder

- El ejecutable busca muchos elementos **por nombre**: borrar uno puede romper el juego. Se ofrece «ocultar» (mover fuera de la pantalla) y la regla `gui_named_element_removed` avisa.
- No se pueden crear ventanas nuevas con función. Sí se puede mover, redimensionar, cambiar sprites, fuentes y textos, y añadir decoración (iconos y texto estático).
- **Alcance decidido (§24, decisión 10).** La suite modifica las ventanas existentes (posición, tamaño, anclaje, sprites, fuentes, textos y decoración) y gestiona las imágenes del juego: sprites nuevos, imágenes de eventos y decisiones, banderas, iconos de CB, tecnologías y pantallas de carga. No crea ventanas nuevas, porque el ejecutable no las abriría; en su lugar ofrece «Duplicar como variante» para probar otra disposición sin perder la original, y explica el límite con el explicador (§11.1).

---

## 18. Taller de mapas: generar o importar un mapa y sus recursos (Mapa › Taller)

> **Decisión del usuario (§24, n.º 9).** Una suite que genera el mapa y sus recursos de forma procedural, al estilo de Azgaar's Fantasy Map Generator (FMG), y la opción de importar recursos de mapa para quien sabe trabajar con bitmaps.
>
> **Base medida.**
> - **R1**: formato real del mapa de HoD 3.04 (`prototipos/mapforge/r1-format/scripts/`, m01–m15).
> - **R2**: estudio de FMG v1.156.0 (MIT) y su prototipo `prototipos/mapforge/r2-azgaar/proto/forge.py`.
> - **Prototipos de este diseño** en `prototipos/mapforge/design/proto/`: `p0`–`p6` (versión 1) y `p7`–`p10` más `mf_lib.py` (versión 2, tras la verificación adversarial). `[pN]` indica el prototipo que da cada cifra. Cuando p1 y p7 discrepan, manda p7.
> - Las rutas son relativas a `docs/diseno/`; `prototipos/mapforge/README.md` explica cómo se ejecutan.
> - Todas las medidas se tomaron en 4 CPU compartidas, con Python 3.13, numpy 2.5 y Pillow 12.3, y se repitieron al menos 2 veces. Los mínimos del proyecto (numpy ≥ 1.24, Pillow ≥ 10) no se pudieron medir aquí: lo hace `bench_mapforge` en CI (§18.12).

Los dos caminos, generar e importar, llenan el mismo modelo (`ForgeWorld`). Desde ahí comparten la vista previa, las ediciones manuales, la validación con SimpleFix y el explicador, la auditoría de dependencias y la exportación en una sola transacción con diario. El resultado es un mapa normal del mod, que se sigue editando con el editor de mapa (§16).

### 18.1 Alcance por niveles, destino y orígenes

El usuario elige un **nivel** (qué se genera), un **destino** (en qué mod se escribe) y un **origen** (de dónde sale la geografía).

| Nivel | Genera | Hereda o modifica | Para qué |
|---|---|---|---|
| **Solo mapa** (`Level.MAP`) | Todo `map/` (§18.8), los colormaps y el minimapa. Historias de provincia con `trade_goods`, `life_rating` y dueño según la opción «Dueños». POPs mínimas en cada provincia de tierra y en cada fecha de `history/pops`. `PROV<id>`, estados y cámara de los bookmarks | Países, culturas, religiones, tecnologías y el resto de `common/`. Modifica `capital` en las historias de los TAG que reciben tierra | Hacer un mapa jugable con los países existentes, o un mapa base para repartirlo después con la brocha política (§16) |
| **Mundo** (`Level.WORLD`) | Lo de Solo mapa, más países nuevos (registro, archivo de país con partidos, historia y 5 banderas), dueños, controladores, núcleos y capitales, culturas (grupos nuevos), religiones (mapeadas a las existentes), POPs completas, RGO, life rating y la localización de todo | Gobiernos, ideologías, reformas, tecnologías, bienes, tipos de POP, culturas gráficas y conjuntos de unidades. **Los TAG existentes siguen registrados, sin tierra** (opción «Quitar los TAG existentes», con auditoría completa, §18.9) | Conversión total con un mundo jugable |
| **Sobre vanilla** (`Level.OVERLAY`) | Sobre el mapa efectivo (vanilla + mod): provincias nuevas (dividir o pintar) o un continente o islas nuevos dentro de una caja de océano. Opcionalmente, países nuevos sobre la tierra nueva o reparto entre TAG existentes | Todo lo demás. **Los ids existentes no cambian** y solo se añade | Ampliar el mapa de vanilla sin romper eventos, decisiones ni OOB |

**Opción «Dueños» de Solo mapa** (pantalla 7). Vanilla no puede jugarse sin provincias con dueño, así que hay que elegir:
- **Repartir entre TAG existentes** (por defecto). Toma los K TAG con más provincias en la instalación efectiva (K = 60, editable) y reparte la tierra por expansión desde sus capitales nuevas (paso 12, con el 85 % de la tierra colonizada). Las provincias sin dueño toman la cultura y la religión del TAG más cercano (expansión sin tope). Las POPs de una provincia con dueño usan la `primary_culture` y la `religion` de su historia.
- **Mapa base, no jugable.** No hay dueños. Las POPs usan una cultura y una religión de la instalación (por defecto, las más frecuentes en sus POPs de 1836, calculadas en tiempo de ejecución). La revisión muestra el aviso `forge_no_owned_provinces`, que exige confirmación explícita.

**Capitales de los TAG sin tierra.** En vanilla, 90 de las 220 capitales ya están en provincias de otro país, porque son países que no existen al empezar (medido con un script sobre `history/countries` y `history/provinces`). Por eso un TAG sin tierra conserva su `capital` si el id sigue siendo una provincia de tierra del mapa nuevo. Si no lo es (id > N o de mar), se reescribe a la capital del país con tierra de su mismo grupo cultural o, si no hay ninguno, a la del país mayor [verificar en juego: liberación de esos TAG].

**Destino.**
- **Este mod.** Antes de exportar se cuentan los archivos que el mod ya tiene bajo las carpetas que el nivel reemplaza o regenera. Si los hay, se ofrece el destino «Mod nuevo» como recomendado. El caso real VSM es una copia completa: 2 705 historias de provincia, 358 de POPs, 265 OOB, 5 guerras y 4 diplomacias (`find`).
- **Mod nuevo.** Usa el generador de `.mod` (§14.1). El mod nuevo hereda de la instalación, no del mod actual.

| Origen | Qué aporta | Niveles | Iteración |
|---|---|---|---|
| **Generar** (`Origin.GENERATE`) | Pipeline procedural completo (§18.3) con plantilla de relieve y semilla | Todos (en Sobre vanilla, dentro de la caja) | 9a (Sobre vanilla, 9b) |
| **Importar bitmaps** (`Origin.BITMAPS`) | `provinces.bmp`/PNG, `definition.csv`, `default.map`, `terrain.bmp`, `rivers.bmp`, mapa de altura, máscara y texto del mapa (§18.6). Lo que falte se reconstruye | Solo mapa y Mundo | 9a |
| **Altura** (`Origin.HEIGHTMAP`) | PNG en gris (también el del editor de alturas de FMG) que sustituye al paso de relieve | Todos | 9a |
| **FMG JSON** (`Origin.FMG_JSON`) | «Export to JSON → Full» o «PackCells» de FMG: celdas, alturas, biomas, ríos, culturas, estados, provincias, religiones y nombres | Solo mapa y Mundo | 9b: en la 9a el botón no aparece |

### 18.2 Flujo del asistente

**Disposición de todas las pantallas.**
- **Izquierda:** la lista de pasos. Cada paso muestra su estado: pendiente, calculado, editado, importado o bloqueado.
- **Centro:** la vista previa a W/4 (1404×540 con el tamaño de vanilla), con el norte arriba. Sus modos son relieve sombreado, tierra/mar, temperatura, precipitación, ríos, biomas, terreno (colores de `terrain.txt`), provincias, estados, continentes, climas, países, culturas, religiones, población y problemas.
- **Derecha:** los parámetros y las herramientas del paso.
- **Abajo:** la semilla (campo y botón «Aleatoria»), los botones «Regenerar este paso», «Regenerar desde aquí» y «Bloquear», Deshacer/Rehacer, la barra de progreso con Cancelar y el contador de problemas.

**Modo sencillo** (por defecto, P4). Solo hay 4 controles: tamaño, plantilla, semilla y número de países (o «Dueños» en Solo mapa). El botón **«Generación rápida»** ejecuta todo con valores por defecto y salta a la pantalla 12. En el modo avanzado se ven el resto de parámetros (`advanced` en `ForgeParams`): cuantiles, exponentes, jitter, `blobPower`…

Cada edición es una transacción del proyecto del taller y se puede deshacer (§6).

| # | Pantalla | Controles | Edición manual en la vista previa |
|---|---|---|---|
| 0 | **¿Qué quieres hacer?** | Tres tarjetas de nivel, los botones de origen de la iteración en curso y el destino (este mod o un mod nuevo, con el recuento de archivos que se moverían a la papelera). Lista de proyectos del taller guardados | — |
| 1 | **Lienzo** | Tamaño: 5616×2160 por defecto, 2808×1080 o personalizado en múltiplos de 24 (aviso [verificar en juego] si no es el de vanilla). Envoltura horizontal (sí). Semilla. Objetivos de provincias de tierra y mar, **escalados con el área** (2 700 y 545 a 5616×2160; 675 y 136 a 2808×1080), con la opción «mismo número que vanilla». **Densidad de celdas** (automática). **La rejilla queda fija al salir de esta pantalla** (§18.4) | — |
| 2 | **Relieve** | Plantilla: 14 portadas de FMG, con miniaturas. Editor de texto con la sintaxis de FMG (`Hill 1 90-100 44-56 40-60`, con la y convertida, §18.5), validado por línea, con «Pegar plantilla de FMG» y «Guardar como plantilla». Deslizador de fracción de tierra (0,34): mueve solo el nivel del mar | Pinceles en coordenadas normalizadas: Subir, Bajar, Suavizar, Allanar, Tierra/Mar, Cordillera (trazo → `Range`) y Fosa (trazo → `Trough`), con radio y fuerza. Lazo para aplicar una operación de plantilla a una zona. Repintado de 13–21 ms (mediana) [p5] |
| 3 | **Clima y agua** | Latitudes sur y norte (−60 y 75), temperaturas del ecuador y de los polos, precipitación, vientos por franja, tamaño mínimo de lago (4 celdas) y **Cantidad de ríos** (cuantil de caudal 0,75, que da unos 90 000 px a 5616×2160; vanilla tiene 104 071) | Pincel «quitar o forzar río»; clic en un lago para convertirlo en tierra o en mar |
| 4 | **Terreno** | Tabla bioma → categoría de Victoria II (editable), umbrales de colinas (h ≥ 44) y montañas (h ≥ 67) y porcentaje de farmlands | Pincel de categoría por celdas |
| 5 | **Provincias** | Objetivos de tierra y mar, variación de tamaño (exponente de idoneidad 0,75), coste de montañas y ríos, sesgo del mar hacia la costa | Mover frontera (a nivel de celda, unos 190 px a 5616×2160), Dividir (trazo), Fusionar, Añadir provincia (semilla), Quitar y Bloquear. Tabla con id provisional, nombre, área, terreno y estado. Para retoques al píxel, el enlace «Abrir en el editor de píxeles» lleva a §16 después de exportar |
| 6 | **Estados, continentes y climas** | Provincias por estado (4,92), número de continentes y sus nombres (por defecto los de la instalación: 6 en vanilla, para que `pop_types`, los eventos y las tecnologías sigan valiendo) y umbrales de clima | Brochas de región, continente y clima de §14.14 sobre la vista previa |
| 7 | **Dueños** (Solo mapa) / **Países** (Mundo) | Solo mapa: «Repartir entre TAG existentes» (K, % colonizado) o «Mapa base». Mundo: número de países (60), % colonizado (85 %), % civilizado, gobiernos permitidos, expansionismo, «Conservar los TAG existentes sin tierra» (sí) y plantilla de tecnologías | Pintar dueño, Mover capital y Editar país (TAG validado con `tag_invalid`/`tag_taken`, nombre EN/ES, color, gobierno y bandera). Bloquear país |
| 8 | **Culturas y religiones** (Mundo) | Culturas (24), grupos (8), fuente de nombres por grupo (§18.5), `unit`/`leader` del grupo (de la instalación) y religiones mapeadas a las existentes | Pintar cultura y religión; renombrar |
| 9 | **Población y economía** | Población total (250 M), fechas de POP (las carpetas efectivas de `history/pops`: `1836.1.1` y `1861.4.14` en vanilla), tabla de presencia de tipos de POP (§18.5), tabla terreno → RGO y distribución del life rating | Pincel de RGO y de life rating |
| 10 | **Nombres** (9a) y **banderas** (9b) | Tabla de nombres (provincias, estados, países, adjetivos, culturas y grupos) EN/ES, con «Regenerar», «Bloquear», duplicados y comprobación de cp1252. Galería de banderas por país (5 variantes) | Doble clic en la vista previa para renombrar |
| 11 | **Estrechos y detalles** | Estrechos sugeridos (con el hueco en px y «aceptar todos») y hueco máximo (8 px). Canales opcionales e `impassable` | Herramienta de estrechos de §16.4. Vista de los puntos `unit` y `naval_base` |
| 12 | **Revisión y exportación** | Render final en el proceso trabajador con progreso por paso y Cancelar. Panel de problemas con [Arreglar] y [¿Por qué?] (§18.11). Auditoría (§18.9). Plan de cambios (archivo · acción · clase A/B/C · tamaño), incluidos los movimientos a la papelera, y Exportar | — |
| 13 | **Hecho** | «Abrir en el editor de mapa» (Mapa › Mundo) y «Seguir en el taller» | — |

- **Atajos por nivel.** Sobre vanilla empieza con «Elegir zona»: una caja sobre el mapa existente, con un buscador de cajas de océano libres. Después pasa por las pantallas 2–6 restringidas a la caja, la 7 opcional y la 12. El origen Importar bitmaps sustituye las pantallas 2–5 por «Importar recursos» (§18.6); cada paso cubierto por un archivo queda como «importado».
- **Paso al editor de mapa (§16).** Tras exportar, el mapa es un mapa normal del mod. El proyecto del taller guarda el sha256 de cada archivo exportado. Si después se editan en §16 y se vuelve a exportar desde el taller, salta `forge_export_conflict` (§18.11), con el explicador y el arreglo «Reimportar al taller los cambios del editor»: los bitmaps del mod entran como capas importadas y bloqueadas.

### 18.3 Pipeline procedural

**Dos etapas.**
- **Etapa de celdas** (pasos 1–17). Se calcula **una sola vez en las coordenadas finales**, sea cual sea la escala de la vista, y sus resultados se guardan en el proyecto (§18.4). Incluye todo lo que decide qué es cada cosa: relieve, agua, provincias **provisionales** sobre el grafo de celdas, estados, continentes, climas, países, culturas, religiones, población, RGO, life rating, nombres y banderas.
- **Etapa de ráster** (pasos 18–27). Se ejecuta a la escala pedida: 4 para la vista previa y 1 para el final. Dibuja las provincias provisionales, arregla fragmentos y, en `reconcile`, hereda los atributos de cada provincia final de su provincia provisional.

Por eso la vista previa y el final comparten el mismo mundo: los hashes de la etapa de celdas y del mundo son idénticos a escala 4 y a escala 1 [p7].

**Principios.**
- **Grafo de celdas.** Rejilla hexagonal con jitter 0,3: sus 6 vecinos implícitos son exactamente los de Voronoi (precisión y recobrado 1,0000 [R2]), sin Delaunator.
- **La costura x = 0/W−1 es frontera.** Ninguna provincia ni estado la cruza, como en vanilla (0 provincias [R1]). La vecindad a través de ella se conserva: hay 33–34 pares de vecinos frente a los 28 de vanilla [p7].
- **Un PRNG por paso.** Cada paso usa `np.random.default_rng([seed, crc32(step_id)])`, así que regenerar los ríos no cambia el relieve.
- **Aritmética reproducible en las decisiones** (§18.4). No se usan ufuncs trascendentes de numpy (power, exp, log, arctan2, hypot), porque su resultado depende del SIMD de la CPU.
  - Las potencias sobre enteros 0–255 van por una tabla calculada con `math.pow`.
  - Pesos `suit^0,75 = sqrt(suit·sqrt(suit))`; distancias con `sqrt`, que es exacta en IEEE.
  - Totales con `math.fsum`.
  - Ordenaciones estables con el id como desempate.
  - Centroides sin trigonometría: la costura es frontera.
- **Pasos puros.** `ForgeWorld → ForgeWorld`, cancelables con `core/cancel.py`. Las ediciones manuales son `EditOp` que se reaplican después de su paso (§18.4).

Tiempos de p7 (60 000 celdas, plantilla «continents» de 13 operaciones, semillas 11 y 7, más la 11 sin AVX-512). La vista previa es a 1404×540 y el final a 5616×2160; la etapa de celdas cuesta lo mismo en las dos.

| # | id | Etapa | Qué hace | Parámetros | Vista previa / final (s) |
|---|---|---|---|---|---|
| 1 | `lattice` | celdas | Rejilla hexagonal con jitter 0,3, envoltura y vecinos implícitos; aristas de la costura marcadas | N = ⌈7,3 · L / f_tierra⌉ acotado a [10 000, 200 000] (unas 60 000), **fijado en la pantalla 1** | 0,025–0,035 |
| 2 | `relief` | celdas | Plantilla FMG: Hill, Pit, Range, Trough, Strait, Mask, Invert, Add, Multiply y Smooth por anillos BFS, con el truncado a Uint8 de Hill [R2] | Plantilla, `blobPower`/`linePower` según N | 0,10–0,15 |
| 3 | `sea_level` | celdas | Nivel del mar por cuantil para la fracción de tierra | `land_fraction` | incluido |
| 4 | `features` | celdas | El océano es la mayor componente de agua. Lagos de ≥ 4 celdas → provincias de mar interior (así modela vanilla sus 38 lagos [R1]); los menores pasan a tierra. Islas | `min_lake_cells` | 0,013–0,018 |
| 5 | `climate` | celdas | Temperatura por latitud de la fila (fila 0 = sur, H1) y −6,5 °C/km. Precipitación por vientos y franjas (FMG simplificado) | Latitudes, temperaturas, vientos | 0,12–0,18 los pasos 5–7 juntos |
| 6 | `hydro` | celdas | *Priority-flood* y acumulación de flujo. Ríos en las celdas con flujo ≥ cuantil | `river_flux_quantile` 0,75 | ″ |
| 7 | `biomes` | celdas | Matriz temperatura × humedad → categoría de Victoria II (tabla editable). h ≥ 67 → mountain; 44 ≤ h < 67 → hills. Farmlands en el 20 % más idóneo de plains y woods. Idoneidad al estilo de `rankCells` | Tabla y umbrales | ″ |
| 8 | `provinces` | celdas | Provincias **provisionales**: Dijkstra multifuente vectorizado sobre el grafo **sin las aristas de la costura** y 2 iteraciones de Lloyd. Tierra con peso idoneidad^0,75 y coste ×2,5 en montaña y ×1,5 en río; mar uniforme. Cada isla recibe al menos 1. Empates por el id de semilla menor | L, S, `size_variance` | 0,26–0,36 |
| 9 | `states` | celdas | Agrupa provincias provisionales vecinas (4,92 por estado, sin cruzar la costura). Una masa de menos de 3 provincias se une al estado más cercano (vanilla tolera 65 estados no conexos) | `provinces_per_state` | 0,013–0,021 los pasos 9–11 |
| 10 | `continents` | celdas | k-medias de centroides; cada masa de tierra va entera a su continente mayoritario, salvo las que superan el 25 % de la tierra | Nombres | ″ |
| 11 | `climates` | celdas | Temperatura e idoneidad medias → `mild`/`temperate`/`harsh`/`inhospitable` (nombres y modificadores de la instalación) | Umbrales | ″ |
| 12 | `countries` | celdas | Centros por idoneidad con separación W/40 (÷1,2 si no caben, como FMG). Expansión Dijkstra sobre el grafo de provincias más los cruces de una celda de mar, con coste por terreno y tope de colonización. En Solo mapa, los centros son los K TAG existentes | Número, % colonizado, expansionismo | 0,06–0,12 los pasos 12–16 |
| 13 | `cultures`, `religions` | celdas | El mismo esquema sin tope. Grupos por cercanía de centros. Religiones mapeadas a las existentes | Número, grupos | ″ |
| 14 | `population` | celdas | Población ∝ área × idoneidad, normalizada con `fsum`. Tabla de presencia de tipos (§18.5) | Total | ″ |
| 15 | `economy` | celdas | RGO por terreno, clima y azar (tabla validada contra los bienes del índice). Life rating por cuantiles de idoneidad sobre la distribución objetivo | Tablas | ″ |
| 16 | `names` | celdas | Nombres de provincias, estados, países (con sufijos tipo `getState`), adjetivos y culturas (§18.5) | Fuente | ″ |
| 17 | `flags` (Mundo) | celdas | 5 TGA por país (§18.5) | Estilo | 0,03 (300 TGA) [p1] |
| 18 | `raster` | ráster | Campo de deformación ligado a la rejilla, costa por altura bilineal por píxel y vecino más cercano 3×3 restringido por clase | Amplitud | 0,28–0,31 / 4,9–5,5 |
| 19 | `fix` | ráster | `fix_fragments2` **sin envoltura**: un trozo al otro lado de la costura es un fragmento. Un trozo menor se funde con el vecino de su clase. Un islote de menos de 40 px cambia de clase; uno mayor pasa a ser provincia hija de la suya | `islet_px` | 0,08–0,12 / 2,6–2,7 |
| 20 | `ids` | ráster | Compacta los ids: tierra 1..L y mar L+1..N. `sea_starts` contiguo y `max_provinces` = N+1. Colores únicos | — | 0,13–0,15 con `reconcile` |
| 21 | `reconcile` | ráster | Provincia final → provincia provisional madre. Una hija hereda estado, dueño, cultura, religión, continente, clima, RGO y life rating, y recibe nombre y POPs propios. Las provisionales que desaparecen se retiran; una capital desaparecida pasa a la mayor provincia del país y un estado vacío se elimina. En p7: 1–5 hijas, 1–6 desaparecidas de 3 253, 0 capitales reasignadas y 0 provincias de tierra sin estado, continente, clima o cultura | — | ″ |
| 22 | `adjacency` | ráster | Vecinos del ráster (4-conexión, con la costura) y estrechos sugeridos (§18.5) | `strait_max_gap_px` 8 | 0,04–0,05 / 1,7 |
| 23 | `positions` | ráster | §18.5 | — | 0,07–0,08 / 1,16–1,23 |
| 24 | `terrain_px` | ráster | Categoría por píxel e índice de `terrain.bmp` por (estado, categoría) entre los índices que usa la instalación (§18.5) | — | 0,03 / 0,8–1,2 |
| 25 | `rivers_px` | ráster | §18.5: 0, 1, 4-conexos y anchos de la instalación | — | 0,22–0,25 / 1,0–1,2 |
| 26 | `textures` | ráster | `colormap` (paleta aprendida), `colormap_water` (10 mips), `colormap_no_shadow` (DXT3), `colormap_political` y minimapa, con cabeceras de vanilla (§18.5) | — | 0,04–0,05 / 0,75–1,4 |
| 27 | `render` | ráster | Textos y codificación BMP/DDS/TGA | — | 0,08–0,09 / 0,3–0,4 (más 0,07–0,1 de textos de mundo [p1]) |
| | **Total** | | | | **1,6–1,75 s**, RSS 176 MiB / **14,9–15,3 s**, RSS 604–611 MiB (en el proceso trabajador). Con escritura y fsync de unos 3 150 archivos (2,1–3,0 s [p1]), unos 17–18,5 s |

- **Perfil de la instalación.** `learn_install()` lee de la instalación del usuario las paletas, las frecuencias de índices de `terrain.bmp` por categoría, los anchos de `rivers.bmp` y sus cuotas, y la paleta del colormap. Tarda 3,5–5,1 s [p7, p8]. Se calcula una vez por instalación y se cachea en `<cache_dir>/mapforge/install_<sha>.npz`, fuera del mod y del repositorio.
- **Nota de medida.** Las cifras de R2 se tomaron con `tracemalloc` activo, que encarece los bucles en Python. Las de p7 se tomaron sin él.

### 18.4 Determinismo, persistencia, ediciones, vista previa y procesos

- **Lo que se guarda.** El proyecto guarda **los resultados** de la etapa de celdas, no solo los parámetros, en `cells.npz` (< 2 MB).
  - Por celda: alturas, clase y categoría, ríos y provincia provisional.
  - Por provincia provisional: estado, continente, clima, dueño, cultura, religión, RGO, life rating y población.
  
  Al abrir el proyecto no se recalcula nada de esa etapa; se recalcula solo al pulsar «Regenerar». Así, abrirlo en otro PC da el mismo mundo aunque cambie la CPU.
- **Determinismo.**
  - La misma semilla, los mismos parámetros, las mismas ediciones y la misma versión de cada paso dan **bytes idénticos**. p7 dio los mismos sha256 (etapa de celdas, mundo, ids, terrain, rivers y todos los archivos) con y sin AVX-512 (`NPY_DISABLE_CPU_FEATURES`). En las mismas condiciones, p1 daba un `region.txt` distinto [p7].
  - `project.json` guarda `Step.version`, las versiones de numpy y Pillow, y huellas de los arrays clave. Si cambian, salta `forge_env_changed` (info): el mundo guardado sigue valiendo, y solo una regeneración podría dar otro resultado.
  - El orden de las expansiones depende solo de arrays y de la semilla, nunca del orden de un `dict` ni del de un `set`.
- **La rejilla es fija.** N, el tipo, el jitter y la semilla de la rejilla (`LatticeSpec`) se deciden en la pantalla 1 y se guardan aparte. La fracción de tierra y los objetivos de provincias solo mueven el nivel del mar y las cuotas. Cambiar la densidad es una acción explícita con aviso.
- **Ediciones.** `EditOp(step, kind, payload, uid)`.
  - Los pinceles de relieve y de tierra/mar guardan trazos en **coordenadas normalizadas** (x, y, r, fuerza), y se reproyectan sobre cualquier rejilla.
  - Las operaciones por celda (mover frontera, pincel de categoría) referencian celdas de la `LatticeSpec` vigente. Si la densidad cambia, pasan a `forge_edit_conflict`.
  - Las ediciones de entidades (países, culturas, nombres) van por uid, nunca por id de provincia, que se renumera.
  - Al regenerar un paso se reaplican sus ediciones. Las que ya no aplican se listan con Descartar o Reintentar.
  - **Bloquear** una entidad o una provincia la conserva al regenerar, como `lock` en FMG.
- **Vista previa frente al final.** Comparten la etapa de celdas y el mundo (mismos hashes). El final solo difiere en las provincias que `fix` crea o retira (hijas 0–5, desaparecidas 1–6 de 3 253), resueltas por `reconcile` [p7]. La vista previa se recalcula desde el paso tocado con 300 ms de espera tras soltar el control.
- **Pinceles en vivo.** La interfaz tiene una copia del ráster de celdas de la vista previa y de las capas por celda. Durante el arrastre repinta por LUT celda → color: 13–21 ms de mediana y 23–24 ms en el percentil 95 [p5]. Al soltar, el trabajador recalcula los pasos posteriores.
- **Proceso trabajador** (`core/mapforge/worker.py`, multiprocessing `spawn`). Es persistente mientras el taller está abierto: guarda el `ForgeWorld` y ejecuta todos los pasos. La interfaz recibe la vista previa (1404×540 `uint16` y capas por celda) por una tubería.
  - Medido con un hilo de interfaz que duerme 5 ms: con el pipeline en un hilo del mismo proceso, la interfaz se bloquea hasta 874 ms en la vista previa y 491 ms en el final. En el proceso trabajador, el máximo es de 8,3 y 42,9 ms y no hay ningún tick de más de 50 ms [p9].
  - El proceso de la interfaz se queda en 33,5 MiB, frente a 177 y 602 MiB del trabajador.
  - Arrancar el trabajador y el IPC cuestan 0,21–0,30 s.
  - El criterio de la iteración 10 (< 600 MB en el proceso de la aplicación) no se ve afectado. El trabajador termina al cerrar el taller.
- **Cancelación.** `cancelled` cruza el proceso con un `multiprocessing.Event`. Se comprueba entre pasos, en cada banda de 64 filas del ráster (unos 0,13 s), en cada pasada de erosión o dilatación y en cada ronda de fragmentos. Si en 2 s no responde, se termina el proceso, que se relanza desde `cells.npz`. Cancelar deja intacto el `ForgeWorld` anterior.

### 18.5 Algoritmos de derivación (numpy y Pillow, sin dependencias nuevas)

- **Orientación (H1, R1 §0.2).** El array guarda las coordenadas del juego: fila 0 = sur. Vanilla abierto en un editor de imágenes se ve con el sur arriba. Solo la vista se voltea. Las importaciones con el norte arriba (PNG, FMG) se voltean una sola vez con `np.flipud`. Los DDS se escriben con las filas en el orden del array. **Las plantillas de FMG** dan y en % desde arriba: el lector las convierte con y_juego = 100 − y, y la miniatura se dibuja con el norte arriba.
- **Máscara de agua única (R1, R2).** `provinces.bmp`, el 254 de `terrain.bmp` y el 254 de `rivers.bmp` salen de `~is_sea[ids]` después de `fix`: 0 px de diferencia, frente a 9 008 en vanilla [p1, p7].
- **Colores.** `rng.choice(2**24 − 2, N, replace=False) + 1`: únicos, sin (0,0,0) ni (255,255,255). En Sobre vanilla se excluyen además los colores de la `definition.csv` efectiva.
- **Posiciones (`core/map/positions.py: generate(raster, is_sea, *, cap=24)`).** Medido: 100 % de `unit` y de los puntos secundarios dentro de su provincia, y `naval_base` en un píxel de mar contiguo en el 100 % de las costeras. Tarda 1,16–1,23 s a 5616×2160 [p7], y 3,0–3,4 s sobre vanilla, que tiene mares mayores [p8].
  - *Centroides* por bandas de 256 filas con `bincount`, sin trigonometría. Solo en las provincias que tocan x = 0 y x = W−1 (posibles en un mapa importado) se suma W a las x < W/2.
  - *Punto interior*: distancia al borde con tope de 24 erosiones 4-conexas (`uint8`, 25 cubos de histograma: 0..24). El máximo por provincia sale de un `bincount`; entre los empates gana el más cercano al centroide. Es `unit` y `text_position`.
  - *Puntos secundarios*: dirección unitaria × min(d, r), con d = 6, 7, 8, 10 y 5 px para `building_construction`, `military_construction`, `factory`, `fort` y `railroad`, y r la distancia al borde de `unit` menos 1. Se prueban 8 direcciones, en un orden distinto por clave, hasta caer dentro con distancia al borde ≥ 2; si ninguna sirve, se usa `unit`.
    - Medido a 5616×2160: entre el 0,8 y el 1,5 % de los puntos quedan a menos de 2 px de `unit`; medianas de 6, 7, 8, 10 y 5,7 px [p7]. En vanilla, las medianas van de 9,8 a 15,5 px [p0]: d es un parámetro calibrable.
    - (La versión 1 elevaba el desplazamiento al cuadrado, y el 99,7–100 % de los puntos caía sobre `unit`.)
  - *`naval_base`*: el píxel de mar contiguo más cercano a `unit` (`lexsort` sobre los pares de frontera). `building_rotation.naval_base` mira hacia tierra.
  - *`text_scale`* = 0,749·área^0,214 (ajuste sobre vanilla, r = 0,889 [p0]), calculado con `math.pow` por provincia.
  - *`text_rotation`*: el ángulo del eje principal (momentos por bandas), solo si la elongación es mayor que 4. En radianes, en [0, 2π).
  - Las provincias de mar llevan `unit`, `text_position` y `text_scale`.
- **Estrechos (`core/map/adjacency.py: suggest_straits(ids, is_sea, max_gap=8)`).**
  - Las ids de tierra se propagan por el mar con D/2 dilataciones 4-conexas. Hay colisión donde dos píxeles de mar contiguos llevan tierras distintas y su hueco es ≤ D. `Through` es la provincia de mar del punto de colisión.
  - Se descartan los pares ya vecinos por tierra.
  - D = 8 px, porque es el percentil 90 de los huecos de las 63 adyacencias `sea` de vanilla [p0].
  - Salen entre 12 y 26 sugerencias por semilla [p7]. El usuario las acepta.
- **Terreno (`terrain_index_by_state_category`).**
  - La categoría por píxel sale de la celda; la altura bilineal fuerza colinas y montañas, salvo en el ártico.
  - **Índices candidatos:** solo los que la instalación usa de verdad, con al menos el 0,5 % de los píxeles de su categoría, ponderados por su frecuencia (aprendidos en tiempo de ejecución).
    - En vanilla quedan fuera 52–59: coastal_desert y las teselas moradas de relleno.
    - Entran el 4 (24 % del ártico de vanilla) y 60–63 (22 % de la montaña), aunque `terrain.txt` los comente como «unused», porque vanilla los pinta.
  - **Un índice por (estado, categoría):** dentro de una provincia, cada categoría usa un solo índice. Así el índice mayoritario pertenece siempre a la categoría mayoritaria. Medido: 0 provincias en las que no ocurre, de 2 715 y de 2 702 (vanilla tiene 34) [p7]. Las dos reglas posibles del motor dan el mismo terreno (R1 §0.3).
  - `terrain =` solo se escribe en las anulaciones que pinte el usuario (`explicit_terrain = "overrides_only"`; la opción `"always"` lo escribe en todas).
  - Tierra con 0 px de 254 ni de índices ≥ 64. La categoría dominante tiene p5 = 55 % y mediana = 100 % [p7].
- **Ríos (`draw_rivers`).**
  - Cada nacimiento (celda de río sin río aguas arriba) inicia un tramo que sigue a los receptores hasta el agua.
  - Los tramos se dibujan por caudal de desembocadura descendente: primero los troncos. Cada uno se dibuja como polilínea en escalera 4-conexa entre extremos enteros, sin huecos.
  - **0** en el primer píxel. El tramo se detiene antes del primer píxel de agua (desembocadura, prolongado una celda si hace falta para llegar al agua del ráster) o al tocar otro río, y entonces marca **1** en su último píxel.
  - Ancho por cuantil del caudal, con **los anchos y las cuotas de píxeles de la instalación** (vanilla: 2, 4, 6, 7, 10 y 11, con 44/34/15/5/1/1 %).
  - Se quitan los píxeles aislados.
  - Medido a 5616×2160 [p7]:
    - 90 395–93 175 px de río (vanilla: 104 071); 1 018–1 243 nacimientos (0) y 586–604 confluencias (1);
    - 0 px unidos solo en diagonal y 0 aislados;
    - los extremos son nacimientos o tocan el agua, salvo 11–14 tramos abiertos;
    - cuotas generadas 42/34/15/5/1/1 %.
  - Sin ríos: 255 en tierra y 254 en agua.
- **Texturas (`core/mapforge/textures.py`).**
  - **Paleta aprendida de la instalación en tiempo de ejecución:** media de `colormap.dds` por categoría de `terrain.bmp`, y también **bajo el agua** (en vanilla, (134,129,89): el agua la dibuja otro shader).
    - Medido: el fondo bajo el mar generado tiene una media de (134,129,89), frente a (133,130,90) de vanilla.
    - La media de la tierra coincide con la prevista por la mezcla de categorías: (141,147,77) frente a (142,148,77). Difiere de la de vanilla (109,135,87) solo porque la mezcla de categorías es otra [p7].
    - Sin instalación se usa una paleta procedural propia.
  - Sobre ese color: sombreado del relieve (luz del noroeste, factor 0,7–1,25) y grano.
  - **Cabeceras idénticas a las de vanilla** [p7]:
    - A8R8G8B8 con `flags` 0x81007 (0xa1007 con mips) y `pitchOrLinearSize` = w·h·4;
    - `colormap.dds` y `colormap_political.dds` de 1880×720 (5 414 528 B);
    - `colormap_water.dds` de 936×360 con **10 mips hasta 1×1** (1 796 960 B, igual que vanilla);
    - `colormap_no_shadow.dds` de 1872×720 en **DXT3** con un codificador numpy propio (extremos mín./máx. por bloque 4×4, alfa 0xF): 1 347 968 B, igual que vanilla, con un error medio de 1,2–1,4 por canal al releerlo con Pillow;
    - `gfx/interface/minimap.dds` de 266×102 (108 656 B).
  - `colormap` y `colormap_political` llevan 4 px de margen por lado copiados envolviendo el mapa [verificar en juego].
- **Nombres (`core/mapforge/names.py: MarkovNames`).** Port de la cadena de pseudosílabas de `names-generator.ts`. Fuentes por grupo de cultura:
  - `syllables` (propia; 9a, también en las pruebas);
  - `custom` (lista pegada por el usuario; 9a);
  - `fmg_bundled` (las 43 bases de FMG, MIT, 9 195 nombres en cp1252; 9b);
  - `user_corpus` (entrenada en memoria con la instalación; nunca se guarda; 9b).
  
  Se filtran los duplicados por tipo, los nombres que no caben en cp1252 y los problemas de `windows_name_problems`.
- **Nombres de archivo.** Se transliteran a ASCII (NFKD, solo `[A-Za-z0-9 _-]`): `history/provinces/<continente>/<id> - <Nombre ASCII>.txt`. Vanilla no tiene ningún nombre de archivo no ASCII. El nombre acentuado queda solo en la localización. Medido: 0 rutas no ASCII [p7].
- **CSV del motor sin comentarios.** `definition.csv` empieza por su cabecera en la línea 1, como vanilla, que no tiene líneas `#`. Los CSV de localización no llevan cabecera ni comentario. `adjacencies.csv` lleva en la línea 1 la cabecera comentada de vanilla (`#From;To;Type;Through;Data;Comment`). El comentario «Generado por…» solo va en los `.txt` de Clausewitz. La procedencia queda en `project.json`.
- **Banderas (`core/gfx/flags.py: procedural_flag(spec)`, 9b).**
  - Estilos propios: tribanda, bicolor, cruz, cruz nórdica, aspa, cantón, disco y cheurón.
  - Variantes por `flagType` (H16).
  - Las escribe `make_flag_set`: TGA de 32 bits, 93×64, origen abajo a la izquierda (H22).
  - De un escudo de FMG solo se importan los colores.
- **Historias.** Formato de §14.3: `owner`, `controller` y `add_core` si hay dueño, `trade_goods` y `life_rating` (y `colonial` si así se pide).
- **POPs.** `history/pops/<fecha>/00_<P>_mapforge.txt` para cada fecha efectiva; la segunda fecha es una copia escalada. **Tabla de presencia** (en lugar de una POP de cada tipo):
  - sin dueño: farmers (o labourers si el RGO es minero), artisans, clergymen, aristocrats y soldiers;
  - con dueño: además bureaucrats y officers;
  - capital de un país civilizado: además craftsmen, clerks y capitalists.
  
  Medido: 0 POPs urbanas en provincias sin dueño y craftsmen solo en las 28 capitales civilizadas; total de 250 M [p7]. En vanilla 1836 hay craftsmen en 33 provincias.

### 18.6 Importación de recursos (para quien domina el bitmap)

Pantalla «Importar recursos»: una ranura por archivo, que admite arrastrar y soltar. Cada ranura muestra su estado (válido o con n problemas), una miniatura con «N» para la orientación y el conmutador «Voltear».

Debajo está la **matriz «Lo que falta se reconstruye»**: para cada paso dice si sale de un archivo, de un paso generado o de una regla, y se actualiza al añadir o quitar archivos. Un paso cubierto por un archivo queda «importado y bloqueado». Se puede importar un solo archivo sobre un proyecto generado; por ejemplo, un `terrain.bmp` pintado a mano.

**Bitmaps con provincias ya dibujadas.** Las provincias provisionales son las del bitmap y no hay etapa de celdas para la partición. Estados, continentes, climas y mundo se calculan sobre el grafo de provincias del ráster (§16.1). En ese caso, `reconcile` no hace nada.

| Recurso | Formatos aceptados | Validación (códigos de §18.11) | Si no se aporta |
|---|---|---|---|
| Provincias | BMP de 24 bits o PNG RGB. W y H múltiplos de 24 | `forge_not_24bit`, `forge_size`, `forge_color_reserved` (vanilla: 7 px negros y 1 blanco [p2]), `bmp_color_unmapped`, `definition_color_duplicate`, `forge_tiny_province` (< 6 px; vanilla tiene 13), `province_fragmented` (info; 615 en vanilla), `forge_seam_province` (info), `province_isolated` y `forge_orientation_suspect` | Pipeline procedural |
| `definition.csv` | `;`, cp1252, tolerante (§16.1) | Las de §16.6 | Ids nuevos (tierra primero) y nombres generados |
| `default.map` | Clausewitz | `sea_start_unknown`, `sea_start_duplicate`, `max_provinces_too_small` | `max_provinces` y `sea_starts` de la clasificación tierra/mar |
| Tierra/mar | Por prioridad: `sea_starts` › mayoría del 254 de `terrain.bmp` › mayoría de `rivers.bmp` › mapa de altura › máscara PNG › clic | `forge_land_sea_unknown` y `forge_land_sea_ambiguous`: entre el 30 y el 70 % de agua, **o menos de 50 px con mezcla**. Así se detecta la 533 de vanilla (12 px, 75 % de agua), el único error de la mayoría del 254 [p0, p8] | Obligatoria si se importan provincias |
| `terrain.bmp` | BMP de 8 bits con paleta. Un BMP RGB se convierte con la paleta de la instalación (0 px de diferencia sobre vanilla [p0, p2]) | `terrain_not_indexed`, `terrain_index_invalid`, `terrain_index_placeholder` y `terrain_sea_mismatch` | Pasos 5–7 y 24 |
| `rivers.bmp` | Igual que `terrain.bmp` | `rivers_not_indexed`, `rivers_diagonal`, `rivers_in_water` y `river_source_missing` | Pasos 6 y 25 sobre el relieve o el pseudorrelieve, o «sin ríos» |
| Altura | PNG o BMP en gris de 8 o 16 bits, de cualquier tamaño, remuestreado a las celdas. El PNG del editor de alturas de FMG (`v = h/100·255`, agua ÷ 1,5) se reconoce y se invierte | `heightmap_size` (info) | Procedural, o **pseudorrelieve** si hay `terrain.bmp`: mountain 75, hills 50, resto 30 y agua 10, suavizado 3 veces |
| Máscara tierra/mar | PNG de 2 colores | — | — |
| `positions.txt`, `adjacencies.csv`, `region.txt`, `continent.txt`, `climate.txt` | Texto del juego | Se conservan si `check_map` no da errores con los ids importados; si no, se pregunta si regenerarlos | Pasos 9–11, 22 y 23 |
| `colormap*.dds` | DDS | Tamaño proporcional (R1 §1.10); si no, se regenera | Paso 26 |
| FMG «JSON Full» o «PackCells» (9b) | JSON de `export-json.ts` | `fmg_version_unknown` y `fmg_aspect` | — |
| Plantilla de relieve de FMG | Texto `tipo n alto x y` (y desde arriba) | Línea inválida, con la columna marcada | — |
| `.map` de FMG y GeoJSON | **Fuera de alcance**, en pendientes [R2] | — | — |

- **Orientación.**
  - Por defecto, `.bmp` se trata como orientación del juego y `.png`, `.jpg` y FMG como norte arriba.
  - Con `positions.txt` hay detección automática: vanilla da 100 % de `unit` dentro tal cual frente a 1,27 % volteado, en 0,01 s [p0, p2].
  - Sin posiciones, se muestra la miniatura con «N» y el conmutador.
- **Coste medido de extremo a extremo [p8].** Entrada: solo `provinces.bmp`, `terrain.bmp` y `rivers.bmp` de vanilla. Reconstruye ids, tierra/mar, fragmentos, vecinos, posiciones, estrechos, estados, continentes, climas, texturas con pseudorrelieve y textos, todo en memoria.
  - Total: **6,9–8,7 s**, sin contar el perfil de la instalación (cacheado). RSS 470 MiB.
  - Ids por censo con `np.unique` más una LUT densa de 2^24: 0,62–0,83 s. Es mejor que `return_inverse` (2,7 s [p2]) y que `bincount` de 2^24 (0,9 s [p0]).
  - Posiciones 3,0–3,4 s; estrechos 1,1–1,4 s.
- **Ida y vuelta.** Exportar → importar `provinces.bmp`, `definition.csv` y `default.map` da los mismos ids (sha igual), 0 colores sin id, 0 ids sin píxeles y `sea_starts` contiguo [p2].
- **FMG JSON (9b).** Se procesa en este orden:
  1. **Encaje.** Escalar uniformemente rellenando con océano (por defecto) o estirar (con aviso). Voltear y. Si hay tierra en las columnas 0 o W−1 con envoltura, se ofrece un margen de océano.
  2. **Rasterizar** los polígonos de `pack` con `ImageDraw.polygon` (60 000 en 0,19 s [R2]), con el mar profundo de `grid`. Después, `fill_gaps` y `fix_fragments2` sin envoltura.
  3. **Agrupar** en provincias de Victoria II dentro de cada provincia de FMG. Las provincias de FMG pasan a ser estados (troceados por encima de 8 provincias) y los estados de FMG, países.
  4. **Ríos** desde `rivers[].cells`.
  
  Un JSON Full de 60 000 celdas pesa unos 33 MB y se lee en 1,05 s, con 303 MiB [p4].

### 18.7 Modelo, módulos y API

```python
# core/mapforge/params.py
class Level(Enum): MAP = "map"; WORLD = "world"; OVERLAY = "overlay"
class Origin(Enum): GENERATE = "generate"; BITMAPS = "bitmaps"; HEIGHTMAP = "heightmap"; FMG_JSON = "fmg_json"
class Owners(Enum): EXISTING_TAGS = "existing_tags"; NONE = "none"           # opción «Dueños» de Solo mapa
@dataclass(frozen=True)
class ExportTarget: kind: str = "this_mod"; new_mod_name: str | None = None   # "this_mod" | "new_mod"
@dataclass(frozen=True)
class LatticeSpec:                               # fija desde la pantalla 1
    cells: int; seed: int; kind: str = "hex"; jitter: float = 0.3; wrap_x: bool = True
@dataclass(frozen=True)
class ForgeParams:
    level: Level = Level.MAP; origin: Origin = Origin.GENERATE; target: ExportTarget = ExportTarget()
    size: tuple[int, int] = (5616, 2160); seed: int = 0; lattice: LatticeSpec | None = None   # None = automática
    template: str = "continents"; template_text: str | None = None; land_fraction: float = 0.34
    lat_south: float = -60.0; lat_north: float = 75.0; temp_equator: float = 27.0; temp_poles: tuple[float, float] = (-30.0, -25.0)
    precipitation: float = 1.0; river_flux_quantile: float = 0.75; min_lake_cells: int = 4
    land_provinces: int | None = None; sea_provinces: int | None = None   # None = 2 700/545 escalados con el área
    size_variance: float = 0.75; provinces_per_state: float = 4.92; continents: tuple[str, ...] = ()
    strait_max_gap_px: int = 8; explicit_terrain: str = "overrides_only"; terrain_min_index_share: float = 0.005
    owners: Owners = Owners.EXISTING_TAGS; existing_tags: int = 60
    countries: int = 60; colonized_fraction: float = 0.85; civilized_fraction: float = 0.5; keep_existing_tags: bool = True
    cultures: int = 24; culture_groups: int = 8; religion_mode: str = "map_existing"
    total_population: int = 250_000_000; name_source: str = "syllables"; flag_style: str = "simple"
    secondary_point_px: Mapping[str, int] = MappingProxyType({"building_construction": 6, "military_construction": 7, "factory": 8, "fort": 10, "railroad": 5})
    ADVANCED: ClassVar[frozenset[str]] = frozenset({...})       # todo salvo size, template, seed, countries/owners
    def validate(self, rules: "GameRules") -> list[Problem]     # múltiplos de 24, ids ≤ 65 535…

# core/mapforge/world.py
@dataclass
class CellLayers: pts; nbr; seam_edge; h; land; feature; temp; prec; flux; recv; river; category; suit; province0   # (N,) / (N, 6)
@dataclass
class ProvisionalTable:                          # por provincia provisional (etapa de celdas)
    is_sea; state; continent; climate; owner; culture; religion; goods; life_rating; population; locked
@dataclass
class ForgeRaster:                               # coordenadas del juego (H1), a una escala
    ids: np.ndarray                              # (H, W) uint16 compactados: tierra 1..L, mar L+1..N
    parent: np.ndarray                           # (N+1,) provincia provisional madre (reconcile)
    terrain: np.ndarray; rivers: np.ndarray; h_px: np.ndarray | None; scale: int
@dataclass
class ForgeWorld:
    params: ForgeParams; cells: CellLayers; provisional: ProvisionalTable
    entities: dict[str, dict[str, "ForgeEntity"]]   # "country" | "culture" | "culture_group" | "religion" | "state" | "name"
    imported: dict[str, "ImportedLayer"]; raster: ForgeRaster | None; steps: dict[str, "StepState"]
    install: "InstallProfile"                       # paletas, índices por categoría, anchos de río, colores (en memoria)

# core/mapforge/pipeline.py
@dataclass(frozen=True)
class Step:
    id: str; deps: tuple[str, ...]; levels: frozenset[Level]; stage: str        # "cells" | "raster"
    version: int; run: Callable[[ForgeWorld, "StepContext"], ForgeWorld]
@dataclass(frozen=True)
class StepContext:
    rng: np.random.Generator                     # default_rng([seed, crc32(step_id)])
    scale: int; progress: "ProgressFn | None"; cancelled: CancelCheck | None
def steps() -> tuple[Step, ...]                 # registro: core/mapforge/steps/*.py
def run_cells(world, *, from_step=None, until=None, progress=None, cancelled=None) -> ForgeWorld
def run_raster(world, *, scale: int, progress=None, cancelled=None) -> ForgeWorld   # 18–27, incluido reconcile
def reconcile(world: ForgeWorld) -> tuple[ForgeWorld, "ReconcileReport"]          # hijas, desaparecidas, capitales

# core/mapforge/worker.py: proceso persistente (multiprocessing spawn)
class ForgeWorker:
    def start(self, project_dir: Path, install: "InstallProfile") -> None
    def submit(self, cmd: "ForgeCommand") -> "Future[ForgeReply]"   # run_cells/run_raster/apply_edit/export_bytes
    def cancel(self) -> None                     # Event; terminate() si no responde en 2 s
    def close(self) -> None
# ForgeReply: vista previa (ids 1404×540, LUT de colores, capas por celda) o carpeta temporal con bytes y sha256

# core/mapforge/edits.py
@dataclass(frozen=True)
class EditOp:
    step: str; kind: str; payload: Mapping[str, object]; uid: str
    # relief_stroke{tool, pts_norm, r_norm, strength} · landsea_stroke{pts_norm, r_norm, to}   (independientes de la rejilla)
    # assign_cells{lattice_sha, cells, province_uid} · paint_category{lattice_sha, cells, cat}       (ligados a la rejilla)
    # split{province_uid, line_norm} · merge{a, b} · rename · recolor · set_owner · move_capital · paint_culture · lock
def apply_edits(world, step_id, edits) -> tuple[ForgeWorld, list["EditConflict"]]

# core/mapforge/project.py: <mod>/.vic2studio/mapforge/<nombre>/
class MapForgeProject:
    name: str; params: ForgeParams; lattice: LatticeSpec; edits: list[EditOp]; locks: set[str]
    imports: dict[str, "ImportRef"]; exported: dict[VPath, str]; env: dict[str, str]   # numpy, Pillow, huellas
    @classmethod
    def open(cls, ws: Workspace, name: str) -> "MapForgeProject"   # carga cells.npz: no recalcula la etapa de celdas
    # project.json, entities.json, edits.jsonl (UTF-8 sin BOM), cells.npz (< 2 MB) e imports/

# core/mapforge/imports/{bitmaps,heightmap,fmg_template,fmg_json}.py
@dataclass
class ImportSet: files: dict[str, Path]; flip_y: bool | None = None
def inspect(files: ImportSet, ctx: ValidationContext, *, progress=None, cancelled=None) -> "ImportReport"
def build_world(files: ImportSet, report: "ImportReport", params: ForgeParams) -> ForgeWorld
def heights_from_image(img, cells, *, fmg: bool | None = None) -> np.ndarray
def read_fmg_json(path) -> "FmgWorld"; def fmg_to_world(fmg, params) -> ForgeWorld          # 9b

# core/mapforge/{install,export,audit,overlay}.py
def learn_install(vfs: VirtualFS, *, cache_dir: Path) -> "InstallProfile"     # 3,5–5,1 s la primera vez
def export_plan(world, project, ctx: "RecipeContext") -> "ChangePlan"         # archivo · acción (G/M/T/E) · clase · tamaño
def export(world, project, ctx) -> list[RecordRef]                            # una transacción
class DependencyAudit:
    def __init__(self, vfs, index: SymbolIndex, level: Level, *, new_ids, new_regions, kept_tags, removed_tags,
                 renamed_continents, replaced_paths) -> None
    def run(self) -> list["OrphanGroup"]          # por carpeta y rol: replace_path · vaciar · papelera · ignorar · ver usos
def find_ocean_boxes(base, is_sea, size) -> list[tuple[int, int, int, int]]
def overlay_world(base, box, params) -> ForgeWorld                             # 9b
```

**Módulos del núcleo** (todos en numpy; los portados llevan la cabecera `# Port of Azgaar's Fantasy Map Generator <ruta>.ts (MIT, © Max Haniyeu)`):
- `core/mapforge/{params,world,pipeline,worker,edits,project,install,graph,relief,climate,hydro,biomes,partition,rasterize,reconcile,textures,names,society,economy,validate,export,audit,overlay,paint}.py`;
- `core/mapforge/steps/*.py`, `core/mapforge/imports/*.py` y `core/mapforge/data/{templates,name_bases,biome_table}.py`.

Se reutilizan:
- `core/map/{bmp,definition,raster,positions,adjacency,groups,coherence}.py` (§16);
- `core/gfx/{dds,flags}.py` (D11, iteración 6; `dds.py` gana mips y DXT3);
- la receta `new_country` (iteración 6).

**Interfaz.** `ui/mapforge/{wizard,preview,brushes,province_tools,entity_tables,import_panel,review,audit_view,flag_gallery,worker_client}.py`, `ui/mapforge/steps/*.py`, `ui/halls/map/forge.py` y `ui/map/split_tool.py`. `preview.py` reutiliza el lienzo de §16.3 (LUT, volteo solo en la vista). `worker_client.py` adapta `ForgeWorker` a las señales de `ui/session.py`.

### 18.8 Exportación: archivos en orden (una sola transacción con diario)

Leyenda:
- **Acciones:** G = generar; M = modificar (copia desde el juego si hace falta, §5.2); H = heredar (no se escribe); T = mover a la papelera (`.vic2studio/trash/<txid>/`); E = archivo vacío en la misma ruta.
- **Clase (R1 §4):** A = el juego no carga sin él; B = no se puede jugar; C = calidad.

| # | Archivo | Clase | Solo mapa | Mundo | Sobre vanilla | Notas |
|---|---|---|---|---|---|---|
| 0 | **Archivos del mod bajo cada carpeta reemplazada** (`history/provinces`, `history/pops`, `history/units`, `history/wars`, `history/diplomacy`) | A | T | T | — | `replace_path` no oculta los archivos del propio mod (§5.3). Sin este paso, en VSM seguirían cargándose 2 705 historias (por ejemplo, `549 - Berlin.txt` con `owner = PRU` sobre la provincia nueva 549: `province_history_duplicate`) y 358 archivos de POPs. Mover 3 337 archivos tarda 0,05 s en Linux [p10]. Con el destino «Mod nuevo» no hace falta |
| 1 | `map/provinces.bmp`, `map/definition.csv` | A | G | G | M | 24 bits, datos en el byte 54. `definition.csv` sin comentarios, con la cabecera en la línea 1 |
| 2 | `map/default.map` | A | G | G | M | `max_provinces` = N+1 y `sea_starts`. El resto de claves (12 archivos y alturas de cámara, H5) se copian de la instalación |
| 3 | `map/terrain.bmp`, `map/rivers.bmp` | A/B | G | G | M (caja) | 8 bits, cabecera de 1 078 B, paletas de la instalación |
| 4 | `map/positions.txt` | A/B | G | G | M | Sobre vanilla: bloques nuevos y reescritura de los mares tocados |
| 5 | `map/adjacencies.csv` | A | G | G | M | Cabecera de vanilla en la línea 1 más los estrechos aceptados |
| 6 | `map/region.txt`, `map/continent.txt`, `map/climate.txt` | B | G | G | M (CST) | En `climate.txt`, los bloques de modificadores de la instalación y las listas nuevas (H7) |
| 7 | `map/region_sea.txt` | A | H, o G vacío si la efectiva cita ids | ídem | H | — |
| 8 | `map/terrain.txt`, `trees.txt`, `province_flag_sprites/`, `texturesheet*.tga` y las otras 36 texturas | A | H | H | H | No se copian |
| 9 | `map/terrain/colormap.dds`, `colormap_water.dds` | C (A si cambia el tamaño [verificar en juego]) | G | G | M (caja) | Cabeceras de vanilla; agua con 10 mips |
| 10 | `map/terrain/colormap_no_shadow.dds` (DXT3), `colormap_political.dds` | C | G | G | M (caja) | — |
| 11 | `history/provinces/<continente>/<id> - <Nombre ASCII>.txt` | B | G | G | G (nuevas) | Una por provincia de tierra |
| 12 | `history/pops/<fecha>/00_<P>_mapforge.txt` | B | G | G | G (nuevas) | Una por fecha efectiva; tabla de presencia |
| 13 | `history/units/<ruta>` de cada `oob` citado | A | E | E | — | Un archivo vacío por cada ruta `oob` citada en las historias de país efectivas que exista en la vista efectiva (vanilla: 342 rutas distintas citadas, 247 existentes). Así `replace_path history/units` no dispara `replace_path_hides_referenced` |
| 14 | `history/countries/<TAG> - <Nombre>.txt` de TAG existentes | A/B | M (`capital` de los K TAG con tierra y de los TAG sin tierra con capital inválida) | M (ídem) | — | CST: solo la clave `capital` |
| 15 | `common/countries.txt` | A | H | M | M si hay países nuevos | Se conservan todos los TAG existentes (también los propios del mod) y `REB`/`dynamic_tags`; los TAG nuevos van antes de `dynamic_tags` (D7). «Quitar los TAG existentes» los retira con auditoría completa |
| 16 | `common/countries/<TAG>.txt`, `history/countries/<TAG> - <Nombre>.txt` nuevos | A/B | — | G | G | Receta `new_country` |
| 17 | `common/cultures.txt` | A si se cita | — | M (añade grupos) | M | WHOLE_FILE: copia completa (aviso) |
| 18 | `common/religion.txt` | A | — | H (M solo con religiones nuevas [verificar en juego]) | H | — |
| 19 | `gfx/flags/<TAG>[_communist\|_fascist\|_monarchy\|_republic].tga` | C | — | G | G | 5 por país |
| 20 | `common/bookmarks.txt` (`cameraX`/`cameraY`) | C | M | M | H | Centro del país mayor o de la masa de tierra mayor |
| 21 | `gfx/interface/minimap.dds` | C | G | G | M | 266×102 |
| 22 | `localisation/00_<P>_map.csv` y `00_<P>_world.csv` | C | G | G | G | Sin cabecera ni comentario. `PROV<id>` (también las de mar), estados, continentes y climas nuevos, `TAG`, `TAG_ADJ`, `TAG_<gobierno>`, partidos, culturas y grupos. EN y ES rellenos; FR y DE copiados con `copy_en_to`. Las claves `PROV`/estado de otros CSV del mod dan `forge_loc_shadowed` |
| 23 | Descriptor `.mod` (`replace_path`) | A | `history/provinces`, `history/pops`, `history/units`, `history/wars` y `history/diplomacy` | ídem | — | Con confirmación. El taller registra el vaciado de `units`/`wars`/`diplomacy` como intencionado: `replace_path_empty` pasa a info en esas carpetas y sigue siendo error en `history/provinces` y `history/pops` |
| 24 | `map/cache` del mod | — | T | T | T | Y se explica cómo vaciar la caché de `user_dir` |
| 25 | `.vic2studio/mapforge/<nombre>/` | — | G | G | G | No lo carga el juego; la exportación del mod lo excluye |

- **Una transacción (§6.5).** Para Mundo: unos 3 150 archivos y 88 MB; el fsync de todos tarda 2,1–3,0 s en Linux [p1]. Los movimientos a la papelera entran en el mismo diario. En Windows (NTFS y antivirus) no se pudo medir aquí: lo mide la iteración 10 con `tools/bench_mapforge.py`.
- **Bytes desde el trabajador.** El render final escribe los bytes y sus sha256 en una carpeta temporal de `<cache_dir>`. La transacción del proceso de la interfaz los adopta como documentos de bytes ya verificados: el texto se reparsea en segundo plano antes de confirmar (I9) y los BMP, DDS y TGA se releen con Pillow.
- **Deshacer.** La exportación es un `UndoStep`. Las instantáneas `before` de más de 8 MB y los archivos movidos a la papelera se guardan como rutas (`Snapshot.before_path`, §6.3) en lugar de en memoria, para no agotar el límite de 256 MB.
- **Antes de exportar.** `check_map`, la validación global y la auditoría. Los errores no bloquean (I10), pero se muestran en la revisión con su SimpleFix. `replace_path_mod_files_remain` y `forge_no_owned_provinces` exigen confirmación explícita.

### 18.9 Auditoría de dependencias

`DependencyAudit` recorre **todas** las referencias del índice (§7) por rol: id de provincia, estado, continente, TAG, cultura y religión, en `common/*`, `events`, `decisions`, `news`, `history/*`, `interface` y localización. Los huérfanos se agrupan por carpeta y rol. Acciones: [Añadir replace_path], [Vaciar] (un archivo vacío con la misma ruta), [Mover a la papelera] (archivos del propio mod), [Ignorar] y [Ver usos].

| Nivel | Qué audita | Volumen en vanilla |
|---|---|---|
| Solo mapa y Mundo | Archivos del propio mod bajo carpetas reemplazadas | VSM: 2 705 + 358 + 265 + 5 + 4 |
| | `oob` de las historias de país (con `history/units` reemplazado) | 345 citas en 216 archivos; 342 rutas distintas |
| | `home` y `location` de los OOB (si no se vacían) | 2 604 y 658 |
| | `capital` de las historias de país | 222 (90 de las 220 de vanilla ya están en provincias de otro país) |
| | `events` | `province_id` 201, `owns` 58, `capital` 22, ámbitos `<id>` 26 y de estado 6 |
| | `decisions` | `owns` 173, ámbitos `<id>` 93, `province_id` 14, `capital` 7, `controls` 4 y de estado 27 |
| | Canales: `decisions/Canals.txt` y `province_flag_sprites` | 3 |
| | Continentes renombrados | `events` 184, `poptypes` 33, `pop_types.txt` 5, `rebel_types` 1, `technologies` 1, `decisions` 1 |
| | Claves de localización `PROV`/estado de otros archivos del mod | — |
| Mundo con «Quitar los TAG existentes» | Citas de TAG en todo el índice | `events`/`decisions` 572 en 80 archivos; `cultures.txt` (`union` 12, `primary` 1); `rebel_types.txt` (`controlled_by` 25, `tag` 12, `is_core` 2, `release_vassal` 2, `exists` 1); `cb_types.txt` (`tag` 11); `news` 64; `history/diplomacy` 78; `history/wars` 30 |
| | Culturas y religiones citadas | — |
| Sobre vanilla | Nada queda huérfano (los ids se conservan) | Comprueba los mares recortados (§18.10) |

Con «Conservar los TAG existentes» (por defecto), las citas de TAG siguen siendo válidas: esos países existen, pero sin tierra, como los TAG que vanilla no hace existir en 1836. En `cultures.txt`, el SimpleFix «Quitar `union`/`primary` de TAG inexistentes» actúa sobre la copia del mod. Al terminar, `check_map` debe dar 0 errores nuevos respecto a la línea base.

### 18.10 Sobre vanilla: provincias y continentes nuevos (iteración 9b)

- **Dividir provincia** (trazar una línea) y **Pintar provincia nueva** (`core/mapforge/paint.py`, `ui/map/split_tool.py`). Escriben en el mod `provinces.bmp` (copia entera, con aviso), la fila de `definition.csv`, `max_provinces`, la región, el continente y el clima, la posición generada, la historia y `PROV<id>`. Después se ejecuta `check_map`. La edición del BMP entra en la pila de deshacer como `RasterPatch`.
- **Continente o islas en una caja de océano.**
  - `find_ocean_boxes` busca cajas sin tierra con margen de mar (imagen integral a 1/8: 0,009 s).
  - El pipeline corre en la caja con la misma densidad de celdas. Medido con 720×480: relieve y provincias en 0,03 s, ráster y fusión en 0,09 s y fragmentos en 0,06 s, más 1,1 s de carga del ráster de vanilla [p3]. La caja no puede cruzar la costura.
  - Las provincias nuevas toman ids desde `max_provinces`; la convención de poner la tierra antes que el mar no se mantiene (H5).
  - Los mares existentes conservan su id y pierden los píxeles que pasan a tierra. En la prueba conservaron entre el 13,6 % y el 100 % de su área. Por debajo del 50 % salta `forge_overlay_sea_shrunk`.
- **Invariante: los píxeles de tierra existentes no cambian.** El prototipo sin restringir cambió 10 px de tierra de vanilla [p3]. Por eso el arreglo de fragmentos solo actúa sobre las ids nuevas y el mar de la caja (`locked_mask`), y una prueba lo fija.
- **Deshacer.** Con `RasterPatch` de la caja ampliada: 1,97 MB [p3]. `positions.txt`, `region.txt`, `continent.txt` y `climate.txt` se editan por CST con `ProvinceGroups` (§14.14).

### 18.11 Problemas del taller (SimpleFix y explicador, §11.1)

Familia `core/validate/rules/mapforge.py`, más las de §16.6 sobre el resultado. Cada código tiene su texto ES/EN, un arreglo con vista previa y el explicador por capas.

| Código | Gravedad | Detecta | SimpleFix (primero = el seguro) | Qué enseña el explicador |
|---|---|---|---|---|
| `replace_path_mod_files_remain` | error | El mod tiene archivos bajo una carpeta que la exportación reemplaza o regenera | Moverlos a la papelera / Exportar a un mod nuevo | Recuento por carpeta y un ejemplo de colisión por id (p. ej. `549 - Berlin.txt` con la provincia nueva 549) |
| `forge_no_owned_provinces` | aviso (con confirmación) | Ninguna provincia con dueño: no se podrá elegir país | Repartir entre TAG existentes | Por qué vanilla necesita provincias con dueño |
| `forge_orientation_suspect` | aviso | Con posiciones: < 50 % de `unit` dentro tal cual y > 90 % volteado | Voltear la imagen | Los dos porcentajes y una miniatura con «N» |
| `forge_not_24bit` | error | Provincias con paleta, en 32 bits o con alfa | Convertir a RGB de 24 bits | Modo y profundidad |
| `forge_size` | aviso | W o H no múltiplos de 24, o tamaño distinto de 5616×2160 [verificar en juego] | Ampliar con mar hasta el múltiplo | Medidas de las texturas resultantes |
| `forge_color_reserved` | aviso | (0,0,0) o (255,255,255) en el BMP | Fundir con el vecino mayoritario | Píxeles y muestra |
| `forge_tiny_province` | aviso | < 6 px | Fundir con el vecino de su clase con más frontera | Área frente al mínimo de vanilla |
| `forge_seam_province` | info | Una provincia importada con píxeles en x = 0 y x = W−1 (vanilla: ninguna) | Partirla por la costura | Filas afectadas [verificar en juego] |
| `province_isolated` | error | Provincia sin vecinos | Fundir con la más cercana de su clase | Vecinos del ráster |
| `forge_land_sea_unknown` | error | Ninguna fuente de tierra/mar | Elegir la fuente | Fuentes y prioridad |
| `forge_land_sea_ambiguous` | aviso | 30–70 % de agua, o < 50 px con mezcla | Marcar tierra con `terrain =` / Marcar mar | Recuento por capa y el caso vanilla 533 |
| `terrain_not_indexed`, `rivers_not_indexed` | error | BMP RGB en lugar de 8 bits con paleta | Convertir con la paleta de la instalación | Colores fuera de la paleta |
| `terrain_index_invalid` | aviso | Tierra con 254 o con un índice ≥ 64; agua sin 254 | Alinear con la máscara de `provinces.bmp` | Píxeles por provincia |
| `terrain_index_placeholder` | aviso | Índices que la instalación no usa (< 0,5 % de su categoría; en vanilla, 52–59) | Cambiar al índice usado más frecuente de la misma categoría | Frecuencias de la instalación y la tesela |
| `rivers_diagonal`, `rivers_in_water`, `river_source_missing` | aviso, aviso, info | Unión solo en diagonal / río sobre agua / tramo sin 0 | Insertar la esquina / Quitar / Marcar los nacimientos | Píxeles afectados |
| `heightmap_size` | info | El tamaño de la altura no coincide | (se remuestrea) | Tamaños |
| `fmg_version_unknown`, `fmg_aspect` | aviso, info | Versión de FMG posterior a la probada / proporción distinta | Importar igualmente / Rellenar con océano | Versión y campos / proporción |
| `forge_too_many_provinces` | error, o aviso por encima de 2× vanilla | > 65 535 ids (`uint16`; textura de 256×256 [R1]) | Reducir el objetivo | Límite [verificar en juego] |
| `forge_edit_conflict` | aviso | `EditOp` que ya no aplica | Descartar / Reintentar | Edición y paso |
| `forge_env_changed` | info | Versiones de numpy o Pillow, o huellas, distintas de las guardadas | (ninguno: el mundo guardado manda) | Versiones antes y después |
| `forge_export_conflict` | aviso | Archivos exportados que cambiaron después (sha) | Reimportar al taller / Sobrescribir (con papelera) | Diff por archivo y capa |
| `forge_loc_shadowed` | aviso | Claves `PROV<id>` o de estado nuevas también definidas en otros CSV del mod | Quitar esas claves de los otros CSV | Archivos y orden de carga [verificar en juego] |
| `forge_overlay_sea_shrunk` | aviso | Mar existente que conserva < 50 % | Repartir el mar de la caja | Área antes y después |

### 18.12 Rendimiento: criterios y cifras medidas

| Operación | Criterio | Medido |
|---|---|---|
| Vista previa completa (W/4, 60 000 celdas, etapa de celdas incluida) | ≤ 3 s | 1,6–1,75 s, RSS 176 MiB [p7] |
| Bloqueo máximo de la interfaz durante cualquier cálculo | ≤ 100 ms | 8,3 ms (vista previa) y 42,9 ms (final) con el trabajador; en un hilo, 874 y 491 ms [p9] |
| Pincel de relieve con repintado a W/4 | ≤ 50 ms | Mediana 13–21 ms, p95 23–24 ms [p5] |
| Regenerar un paso de mundo | ≤ 0,5 s | 0,06–0,12 s los pasos 12–16 [p7] |
| Render final 5616×2160 en memoria | ≤ 25 s | 14,9–15,3 s [p7]; con escritura y fsync, unos 17–18,5 s [p1] |
| Memoria pico del trabajador | ≤ 1,2 GiB | 604–611 MiB [p7, p9] |
| Memoria del proceso de la interfaz durante el render | sin aumento | 33,5 MiB en la prueba [p9] |
| Perfil de la instalación (una vez, cacheado) | ≤ 8 s | 3,5–5,1 s [p7, p8] |
| Importar 3 bitmaps del tamaño de vanilla y reconstruir lo que falta | ≤ 10 s | 6,9–8,7 s de extremo a extremo [p8] |
| Leer un JSON Full de FMG de 60 000 celdas | ≤ 3 s | 1,05 s, 33 MB, 303 MiB [p4] |
| Continente en una caja de 720×480 sobre vanilla | ≤ 3 s, más la carga del ráster | 0,2 s + 1,1 s [p3] |
| Respuesta a Cancelar | ≤ 1 s (≤ 2 s con terminate) | Comprobación cada ≤ 0,13 s en el ráster |

- **Memoria.** Ids en `uint16`; centroides, momentos y posiciones por bandas de 256 filas; liberación del campo de deformación y de la altura ampliada tras el ráster.
- **Versiones mínimas.** `bench_mapforge` corre en CI con numpy 1.24 y Pillow 10, los mínimos de `pyproject.toml`. Si no cumple los criterios, se sube el mínimo a numpy ≥ 2.0 (decisión de la iteración 9a; la ordenación SIMD de numpy 2 es la que da los 0,6–0,8 s del censo).

### 18.13 Licencias y datos

- **FMG** es MIT, con una cláusula de obras derivadas libres. Se portan algoritmos y código con cabecera por módulo y el texto MIT íntegro en `THIRD_PARTY_NOTICES.md`.
  - Se incluyen las 14 plantillas de relieve y las 43 bases de nombres.
  - **No** se incluyen las cargas heráldicas SVG (licencia no demostrada) ni los PNG de alturas del mundo real.
- **Paradox:** nada en el repositorio. En tiempo de ejecución, `learn_install()` lee de la instalación del usuario:
  - las paletas de `terrain.bmp` y `rivers.bmp`, las frecuencias de índices y los anchos de río;
  - `terrain.txt`, `trees.txt` y las claves de `default.map`;
  - los bloques de clima;
  - la paleta del colormap y el color medio del agua;
  - las listas de bienes, tipos de POP, gobiernos, reformas y tecnologías;
  - la fuente de nombres `user_corpus`.
  
  El perfil se cachea en `<cache_dir>`, fuera del mod y del repositorio. Las pruebas usan `syllables` y una instalación sintética.

---

## 19. Pruebas y fixtures

El repositorio **no contiene archivos de Paradox**, salvo lo que muestran dos capturas antiguas (`docs/capturas/03_estructura_provincia.png` y `04_localizacion_text_csv.png` enseñan archivos de vanilla), que se sustituyen en T5. Las pruebas del repositorio usan fixtures sintéticos generados por código con la forma real y la muestra del usuario (`tests/fixtures/shago_mod_min`: archivos creados por él, salvo los 6 de `common/countries/`, que desde el 26-10-2026 son versiones sintéticas de los suyos, por decisión del usuario, porque repetían bloques de partidos y listas `unit_names` de vanilla; las políticas, las fechas de los partidos y los `unit_names` son inventados). El corpus completo se usa en local mediante variables de entorno.

### 19.1 Fixtures

- **`tests/_minigame.py: build_minigame(root: Path, *, mod: bool = True) -> MiniGame`**. Genera en una carpeta temporal un juego y un mod coherentes, todo inventado:
  - `map/`: `provinces.bmp` **asimétrico** de 64×32 con 12 provincias (8 de tierra y 4 de mar), `definition.csv` (con cabecera, una fila `223.` y una fila sin id), `default.map`, `region.txt` (3 estados), `region_sea.txt` (solo CR), `continent.txt` (2), `climate.txt` (claves emparejadas), `terrain.bmp` y `rivers.bmp` de 8 bits con paleta, `terrain.txt`, `positions.txt`, `adjacencies.csv` y `province_flag_sprites`.
  - `common/`: `countries.txt` con AAA, BBB y CCC, un comentario, `dynamic_tags = yes` y D01; `countries/*.txt` con partidos (un nombre de partido compartido entre dos archivos, como H12); `country_colors.txt`, `cultures.txt` (2 grupos, 4 culturas), `religion.txt`, `governments.txt` (3), `rebel_types.txt` (2 tablas), `ideologies.txt`, `issues.txt`, `technology.txt` + `technologies/army_tech.txt` (con `activate_unit`), `inventions/`, `goods.txt`, `buildings.txt`, `poptypes/`, `nationalvalues.txt`, `cb_types.txt` (con `peace_order` y un valor que no es CB), `bookmarks.txt` (2), `defines.lua` mínimo y `graphicalculturetype.txt`.
  - `history/`: provincias (una solo CR, una con nombre irregular y un id duplicado en dos carpetas), países, POPs en 2 fechas (con un bloque repetido), `units/AAA_oob.txt`, una guerra y una alianza.
  - `units/infantry.txt` y `units/frigate.txt`, 2 eventos y 1 archivo de decisiones.
  - `interface/test.gui` y `test.gfx`, un DDS de 8×8 (escrito por `core/gfx/dds.py`), una BMFont mínima (`.fnt` + `.tga`), una imagen de evento y banderas de AAA.
  - `localisation/`: un CSV del juego y otro del mod.
- **`tests/_layers.py`**: construye capas de juego, dependencia y mod a partir de diccionarios de bytes (pruebas de la VFS).
- **`tests/_corpus.py`** gana `vanilla_root()` (`VIC2_GAME` si está definida; si no, la primera raíz de `VIC2_CORPUS` que contenga `map/default.map`) y `user_mod_full()`. Las pruebas de corpus se omiten con un motivo claro cuando falta.

### 19.2 Pruebas por riesgo

| Riesgo | Pruebas | Qué afirman |
|---|---|---|
| Escribir fuera del mod (I1) | `test_vfs_guard.py`, `test_arch_writes.py` | Enlaces simbólicos que escapan, `..`, `\\`, mayúsculas, mod dentro del juego, descriptor permitido. El recorrido AST no encuentra primitivas de escritura fuera de `fileio.py` ni llamadas a `fileio` fuera de los módulos permitidos (§4). |
| Guardado a medias (I2) | `test_journal_commit.py`, `test_journal_crash.py`, `test_journal_kill.py` | Fallo inyectado en cada paso k, `PermissionError` en el tercer `os.replace` y subproceso con `os._exit` en el paso k: tras `recover()` todo-antes o todo-después; recuperar dos veces da lo mismo. |
| Escritura con pérdidas (I3, I9) | `test_noop_save.py`, `test_render_checked.py`, `test_bmp_roundtrip.py`, `test_tablecsv.py`, `test_lua_defines.py`, `test_lexer_cr.py` | Guardar sin cambios no escribe; un carácter no cp1252 o un `SourceMismatchError` no tocan el disco; ida y vuelta de BMP, CSV de mapa y Lua; CR solo con comentario. |
| Leer escribe (I4) | `test_workspace_readonly.py` | Abrir, indexar y validar deja el árbol del mod idéntico. |
| Deshacer corrompe (I5) | `test_undo_property.py` | Secuencias aleatorias de edición (semilla fija) sobre el minijuego y, con corpus, sobre vanilla: deshacer todo da los bytes originales; rehacer todo, los del avance. |
| Claves desconocidas (I6) | `test_schema_unknown_keys.py` | Editar por esquema un archivo con `social_policy` conserva la línea. |
| Vista efectiva (I7) | `test_vfs_resolution.py`, `test_loc_effective.py` | WHOLE_FILE, UNION, KEYED, `replace_path` (recursivo y no) y mayúsculas; una clave de vanilla editada se ve nueva y `text.csv` no se copia. |
| Trabajo perdido (I8) | `test_recovery_autosave.py`, `test_lock.py`, `test_external_change.py` | Sesión huérfana restaurada; segunda instancia en solo lectura; cambio externo → conflicto. |
| Colocación | `test_placement.py` | TAG antes de `dynamic_tags` (bytes exactos); evento de vanilla copiado a la misma ruta; historia de provincia en la misma ruta; repetibles tras su último hermano; nada tras el primer bloque fechado. |
| Referencias rotas | `test_validate_*.py` | Minijuego con un error por regla; con corpus, VSM da exactamente los problemas conocidos (H14, H15) y vanilla reproduce su línea base. |
| Índice desfasado | `test_index_incremental.py`, `test_index_cache.py` | Cambiar un archivo reprocesa solo ese (contador de parseos); una versión nueva de extractor invalida su caché. |
| Orientación y coherencia del mapa | `test_map_orientation.py`, `test_map_invariants.py`, `test_mapforge_export.py` | Fixture asimétrico; con corpus, el punto `unit` de `positions.txt` cae en su provincia o junto a ella en ≥ 95 % de los casos; propiedad «una región por provincia»; mapa sintético exportado sin errores. |
| Hilos (I12) | `test_workspace_thread.py` | Llamar a `Workspace` desde otro hilo lanza un error. |

### 19.3 Arnés de esquemas (`tests/schema_harness.py`)

```python
class GovernmentContract(SchemaContract):
    schema = GOVERNMENT
    corpus = "common/governments.txt"          # opcional; requiere vanilla_root()
    allowed = {}                               # línea base declarada, p. ej. {"duplicate_field": 50} en country_history
```

Genera solas: `test_texts_es_en`, `test_docgen`, `test_open_save_unchanged`, `test_set_each_field` (cada `Field` con `example()` cambia una sola entrada y reparsea igual), `test_repeat_add_remove`, `test_dynamic_keys`, `test_history_write_policy` (si hay historia), `test_template_validates` (lo nuevo nace válido), `test_loc_keys`, `test_companions` (crear, renombrar y borrar), `test_placement` y `test_corpus_conformance` (con corpus: 0 `unknown_field` y 0 `bad_type` salvo `allowed`). Las pruebas de interfaz construyen el formulario de cada esquema registrado, ponen un valor en cada editor y comprueban el cambio en el registro, la paridad ES/EN y la pseudolocalización.

### 19.4 Pruebas de corpus (opcionales, en local)

Con `VIC2_CORPUS` y/o `VIC2_GAME`:

- Ida y vuelta byte a byte de todos los archivos Clausewitz del corpus (la prueba ya existe; `CLAUSEWITZ_SUFFIXES` debe incluir `.map` para cubrir `default.map`) y de los CSV, BMP y `defines.lua`.
- Recuentos del índice: 271 TAG + 50 dinámicos, 2 703 provincias de tierra (3246 incluida) y 545 de mar, 549 regiones, 6 continentes, 34 grupos y 226 culturas, 8 gobiernos, 31 CB, 21 tipos de unidad (11 + 10), 150 tecnologías, 387 invenciones, 1 064 eventos, 151 decisiones y 2 bookmarks.
- Conformidad de cada esquema, árbol de guion sin pérdidas en todos los eventos y decisiones, y cobertura del catálogo (≥ 95 % de los usos).
- `check_map(vanilla)` coincide con la instantánea de problemas conocidos; orientación de Berlín (fila 1675,6 frente a `y=1676`).
- Validación de VSM con los problemas exactos del usuario.

### 19.5 Arquitectura, interfaz y capturas

- **Arquitectura**: `core` no carga PySide6; sintaxis 3.10 (`ast.parse(..., feature_version=(3, 10))`); lista blanca de escrituras; cada `Field.label`/`help` y cada entrada del catálogo tiene ES y EN; fragmentos i18n sin claves duplicadas y con paridad.
- **Sin datos de Paradox**: `tests/fixtures/` solo admite rutas permitidas (la muestra del usuario, con sus archivos de país sintéticos). Con corpus, ninguna línea de 40 o más caracteres de los archivos de vanilla aparece en `src/`, `tests/` ni `docs/`. La comparación debe ignorar las asignaciones simples «clave = palabra» del vocabulario del juego (p. ej. `citizenship_policy = limited_citizenship`, que sale en cualquier archivo de país): sin eso la prueba daría falsos positivos con la muestra sintética.
- **Interfaz offscreen** (`tests/_qt.py`): cada sala y sección se construyen y se retraducen ES/EN sin claves crudas; Ctrl+1..7, Ctrl+K, Ctrl+S/Z/Y; los asistentes de país, guerra, evento y mapa, de principio a fin sobre el minijuego, crean exactamente los archivos de su plan.
- **Capturas**: `tools/screenshot.py` admite `--hall`, `--section`, `--entity kind:id`, `--wizard country --step N`, `--map-mode` y `--no-game-art` (por defecto en `docs/capturas`). En cada iteración se revisan en ES y EN a 1100×700 y 1920×1080.
- **Verificación adversarial**: al cerrar cada iteración, un verificador por componente reproduce cada hallazgo antes de reportarlo, y cada corrección lleva su prueba de regresión.
- **Lista de comprobación en el juego**: por decisión del usuario (§24) se entrega una sola vez, al final (iteración 10). Reúne todas las reglas [verificar en juego] y las pruebas de flujo («el país nuevo aparece jugable en 1836», «la guerra está activa en 1836», «el mapa nuevo carga»), incluidas las 28 comprobaciones del taller de mapas (§19.7). Mientras tanto, cada regla dudosa se modela como opción explícita y las pruebas cubren sus dos variantes.

### 19.6 Pruebas del taller de mapas (§18)

Las reparte el plan de las iteraciones 9a y 9b; cada archivo de prueba tiene un dueño.

#### Añadidos a §19.1 (fixtures)

- **`tests/_mapforge_fixtures.py`** (todo generado por código, sin datos de Paradox ni de FMG):
  - `tiny_params(seed, size=(288, 144), cells=2000, land=40, sea=10)` y `tiny_world(seed, level=Level.MAP)`. 288×144 es múltiplo de 24: W/3+8 = 104 y W/6 = 48 son enteros. `bad_size_params()` (256×128) existe solo para probar `forge_size`;
  - `synthetic_install(root)`, que añade al minijuego:
    - `terrain.txt` con 13 categorías y `text_0…63`;
    - un `terrain.bmp` sintético con frecuencias conocidas (índices 52–59 sin usar, para `terrain_index_placeholder`);
    - un `rivers.bmp` con anchos 2/4/6 y paletas de 256 entradas;
    - `climate.txt` con claves emparejadas, 2 carpetas de POP y un `colormap.dds` y un `colormap_water.dds` de muestra;
    - `common/countries.txt` con `REB`, 3 TAG y `dynamic_tags`;
    - historias de país con `capital` y `oob`;
    - un OOB por TAG;
    - `cultures.txt` con `union` y `primary`, y `rebel_types.txt` con `controlled_by`;
  - `full_copy_mod(root)`: un mod que copia `history/` completo del minijuego (el caso VSM);
  - bitmaps de importación de 72×48, derivados del `provinces.bmp` asimétrico del minijuego:
    - la versión «norte arriba» en PNG;
    - un `terrain.bmp` RGB;
    - un `rivers.bmp` con uniones en diagonal y un río sobre agua;
    - un BMP con píxeles (0,0,0) y una provincia de 3 px;
    - otro con una provincia partida;
    - otro con una provincia en x = 0 y x = W−1;
    - una provincia de 12 px con el 75 % de agua (caso 533);
    - una altura PNG en gradiente de 16 bits y una máscara tierra/mar;
  - `fmg_json_full(n_cells=200)`: JSON con la forma de `getFullDataJson` (3 estados, 6 provincias, 2 culturas, 1 río e `info.version` configurable);
  - `FakeForgeWorker`: devuelve `tiny_world` sin proceso, para las pruebas de interfaz.
- **Fuente de nombres de prueba:** `syllables`. Ninguna prueba depende de las bases de FMG ni de la instalación.

#### Añadidos a §19.2 (pruebas por riesgo)

| Riesgo | Pruebas | Qué afirman |
|---|---|---|
| Mapa incoherente | `test_mapforge_props.py` (semillas 0–19 sobre `tiny_world`; 3 semillas a 5616×2160 con la marca `slow`) | Cada provincia de tierra en exactamente 1 estado, 1 continente y 1 clima; el mar en ninguno. Colores únicos sin negro ni blanco. Biyección `definition.csv` ↔ BMP. Ids contiguos con la tierra primero; `sea_starts` = L+1..N; `max_provinces` = N+1. 0 partidas, 0 aisladas y 0 provincias en x = 0 y x = W−1 a la vez, con ≥ 1 par de vecinos a través de la costura. Adyacencias simétricas; `Through` es mar y toca a los dos extremos. Misma máscara de agua en las tres capas |
| `reconcile` | `test_mapforge_reconcile.py` | Tras el render final, cada provincia de tierra tiene estado, continente, clima, historia, POPs y `PROV<id>`. Las hijas heredan los atributos de su madre. Una capital desaparecida se reasigna a una provincia del mismo país. Un estado vacío se elimina |
| Terreno | `test_mapforge_terrain.py` | Índice mayoritario ∈ categoría mayoritaria en el 100 % de las provincias. Solo índices con ≥ 0,5 % en la instalación sintética. Tierra con índices < 64 y sin 254 |
| Ríos | `test_mapforge_rivers.py` | 4-conexos (0 píxeles unidos solo en diagonal) y 0 aislados. Cada tramo empieza en 0. Cada final es 1 junto a otro río o tierra junto al agua (≤ 2 % de tramos abiertos). El ancho no disminuye río abajo. Solo anchos de la instalación |
| Posiciones | `test_mapforge_positions.py` | 100 % de los puntos dentro de su provincia. < 5 % de puntos secundarios a menos de 2 px de `unit`; medianas en [5, 16] px a 5616×2160. `naval_base` en mar contiguo en cada costera. `text_rotation` en [0, 2π). Un bloque por provincia, también las de mar |
| Formato | `test_mapforge_textures.py`, `test_mapforge_export.py::formats` | DDS con medidas, mips, `flags`, `pitchOrLinearSize` y tamaño exactos (a 5616×2160: 5 414 528 / 1 796 960 con 10 mips / 1 347 968 en DXT3 / 108 656 B); DXT3 releído con Pillow con un error medio ≤ 3. Línea 1 de `definition.csv` = cabecera; CSV de localización sin comentarios; 0 rutas no ASCII |
| POPs | `test_mapforge_owners.py` | Con «Repartir», ≥ 1 TAG con tierra y capital propia; la cultura y la religión de las POPs con dueño son las del TAG. 0 POPs urbanas en provincias sin dueño. «Mapa base» da `forge_no_owned_provinces` |
| No determinismo | `test_mapforge_determinism.py` | Dos ejecuciones dan el mismo sha256 en todos los archivos. Una ejecución en un subproceso con `NPY_DISABLE_CPU_FEATURES="AVX512F AVX512CD AVX512_SKX X86_V4"` da los mismos hashes (se salta si la CPU no tiene AVX-512). Abrir un proyecto no recalcula la etapa de celdas. Regenerar `hydro` o `countries` no cambia `provinces.bmp`. Una provincia bloqueada conserva sus celdas. Mover `land_fraction` después de pintar no da conflictos de trazo |
| La vista previa engaña | `test_mapforge_preview.py` | Los hashes de la etapa de celdas y del mundo son iguales a escala 4 y a escala 1. Las provincias provisionales sin correspondencia son ≤ 1 % |
| Orientación y plantillas | `test_mapforge_import.py::orientation`, `test_mapforge_relief.py::fmg_template_y` | El PNG con el norte arriba se voltea; con `positions.txt` se detecta solo. Un `Hill` en y = 10 (arriba en FMG) queda en la parte norte del array (filas altas) |
| Importación | `test_mapforge_import.py` | Un fixture por código de §18.11 con su SimpleFix y su explicador. La conversión RGB → paleta es exacta. La matriz de reconstrucción es correcta para cada combinación de ranuras. Ida y vuelta con bytes idénticos. La provincia de 12 px con el 75 % de agua da `forge_land_sea_ambiguous` |
| Mod de destino | `test_mapforge_export.py::full_copy_mod` | Tras exportar sobre `full_copy_mod`: 0 archivos del mod anterior en `history/provinces`, `history/pops`, `history/units`, `history/wars` e `history/diplomacy` (están en la papelera y vuelven al deshacer). 0 `replace_path_hides_referenced`. `replace_path_empty` en info solo para las carpetas vaciadas de forma intencionada |
| Exportación a medias | `test_mapforge_export.py` | Plan de §18.8 por nivel. Fallo inyectado en cada paso, incluidos los movimientos a la papelera: todo antes o todo después. `map/cache` a la papelera. Deshacer con `before_path` |
| Huérfanos | `test_mapforge_audit.py`, `test_mapforge_audit_tags.py` (9b) | Cada rol (OOB, `capital`, `owns`, ámbito `<id>`, ámbito de estado, canal, continente renombrado, localización) en su grupo. Con «Quitar los TAG existentes», además `union`/`primary` de `cultures.txt` y `controlled_by` de `rebel_types.txt` |
| Interfaz | `test_mapforge_worker.py`, `test_mapforge_cancel.py` | Con el trabajador real sobre `tiny_world` escalado, un hilo de ticks de 5 ms no ve ningún retraso > 100 ms. Cancelar en cada paso responde en ≤ 1 s (≤ 2 s con terminate) y deja el `ForgeWorld` anterior. El trabajador se relanza desde `cells.npz` |
| FMG (9b) | `test_mapforge_fmg_json.py` | Ninguna provincia cruza una provincia de FMG ni la costura; estados → países; y volteada; versión posterior → `fmg_version_unknown` |
| Mundo jugable (9b) | `test_mapforge_world.py` | Dueños antes de `dynamic_tags`; `REB`, D01–D50 y TAG existentes conservados; capital propia; `ruling_party` admitido; POPs con presencia; culturas con nombres; TAG válidos; localización EN/ES |
| Sobre vanilla (9b) | `test_mapforge_overlay.py` | Ids desde `max_provinces`; 0 px de tierra existente cambian; los mares tocados conservan su id; `forge_overlay_sea_shrunk`; `RasterPatch` deshace exactamente |
| Licencias | `test_third_party_notices.py`, `test_no_install_content.py` | Cabecera de cada módulo portado y texto MIT. Ninguna línea de más de 20 caracteres ni ningún archivo del repositorio coincide con la instalación de prueba; `data/name_bases.py` está en lista blanca (sus topónimos reales coinciden por naturaleza) |

#### Añadidos a §19.4 (corpus, opcionales)

- Importar `provinces.bmp`, `definition.csv` y `default.map` de vanilla da 27 colores sin id (8 834 px), 1 `sea_start` repetido (2800), 0 ids sin píxeles y 0 colores repetidos.
- Tierra/mar por la mayoría del 254 de `terrain.bmp`: 1 provincia distinta (533), detectada por `forge_land_sea_ambiguous`.
- Orientación: 100 % de `unit` dentro tal cual frente a 1,27 % volteado.
- `terrain.bmp` y `rivers.bmp` pasados a RGB y reconvertidos: 0 px de diferencia.
- Perfil de la instalación de vanilla:
  - índices candidatos sin 52–59 y con 4 y 60–63;
  - anchos de río 2/4/6/7/10/11 con cuotas 44/34/15/5/1/1 %;
  - color bajo el agua ≈ (134,129,89).
- Importación de extremo a extremo de los 3 bitmaps de vanilla en ≤ 10 s.
- Continente en una caja de océano de vanilla: 0 px de tierra existente cambiados.
- Los DDS generados a 5616×2160 tienen el mismo tamaño en bytes y los mismos `flags` que los de vanilla.

#### Rendimiento (`tools/bench_mapforge.py`, local y en CI con los mínimos de `pyproject.toml`)

Con 5616×2160, 60 000 celdas y 3 semillas, en el proceso trabajador, comprueba:
- vista previa ≤ 3 s;
- render final en memoria ≤ 25 s;
- RSS del trabajador ≤ 1,2 GiB;
- bloqueo de la interfaz ≤ 100 ms;
- pincel ≤ 50 ms;
- perfil de la instalación ≤ 8 s;
- importación de 3 bitmaps ≤ 10 s;
- JSON de FMG ≤ 3 s.

Se mide sin `tracemalloc`; la memoria se mide en una ejecución aparte.

### 19.7 Comprobaciones en el juego del taller de mapas

Forman parte de la lista única de la iteración 10 (§19.5). Cada una cubre una regla [verificar en juego] de §18; mientras no haya respuesta, la opción correspondiente sigue siendo explícita y las pruebas cubren sus variantes.

1. Un mapa generado de 5616×2160 con «Solo mapa → Repartir entre TAG existentes» carga, permite elegir un país con tierra y se juega un mes sin errores; el mapa base sin dueños carga hasta el selector.
2. Tras exportar, borrar `map/cache` del mod y de `user_dir` basta para que el juego use el mapa nuevo.
3. Un TAG existente sin tierra cuya capital es una provincia de otro país (como 90 de las 220 de vanilla) no da error y se puede liberar con su capital reescrita.
4. Los archivos OOB vacíos escritos en las rutas citadas por `oob =` (con `replace_path` `history/units`) se aceptan sin errores ni unidades fantasma.
5. `history/wars` e `history/diplomacy` reemplazadas y vacías: el juego empieza sin guerras ni relaciones y no se cierra.
6. Un mapa de 2808×1080 con `colormap` de (W/3+8)×H/3, `colormap_water` de W/6×H/6 con 10 mips y minimapa nuevo carga y se ve alineado (margen de 4 px por lado, envuelto).
7. `colormap_no_shadow.dds` escrito con el codificador DXT3 propio y `colormap_political.dds` regenerado se cargan sin artefactos.
8. Con un índice de textura por (estado, categoría), el terreno que muestra el juego coincide con la categoría mayoritaria; una anulación `terrain =` gana sobre `terrain.bmp`.
9. Los índices de `terrain.bmp` aprendidos de la instalación (incluidos 4 y 60–63, sin 52–59) se dibujan con texturas normales, sin teselas moradas.
10. Los ríos generados (0 en el nacimiento, 1 en la confluencia y anchos 2/4/6/7/10/11) se dibujan continuos, con el ancho creciente río abajo, y desembocan bien en la costa.
11. No hay ninguna provincia que cruce la costura x=0/W−1 y los 33 pares de vecinos a través de ella permiten mover ejércitos y flotas de un borde al otro (envoltura).
12. Lagos generados como provincias de mar sin vecino de mar (en `sea_starts`, índice 254) se dibujan bien en `colormap_water` y no son navegables desde el océano.
13. Los estrechos generados (`sea` con `Through` en la provincia de mar del hueco) permiten cruzar ejércitos; un `adjacencies.csv` con la cabecera de vanilla y sin filas es válido.
14. `naval_base` en un píxel de mar contiguo con `building_rotation` hacia tierra: el puerto aparece y se puede construir en cada costera generada.
15. Los puntos secundarios de `positions.txt` (fuerte, fábrica, construcción) aparecen separados de la unidad y dentro de la provincia.
16. `text_scale` = 0,749·área^0,214 y `text_rotation` solo en provincias alargadas: los nombres se leen sin solaparse en el zoom por defecto.
17. `definition.csv` con la cabecera en la línea 1 y sin comentarios, y los CSV de localización sin cabecera: el juego no crea ninguna provincia fantasma ni claves vacías.
18. La localización `00_<P>_map.csv` gana sobre claves PROV/estado repetidas en otros CSV del mod (orden de carga), o hace falta el SimpleFix de `forge_loc_shadowed`.
19. Las historias con nombre de archivo ASCII se cargan por su id y el nombre acentuado aparece en la localización.
20. País generado con la receta `new_country` (partidos, `ruling_party` admitido, reformas y tecnologías de plantilla) es jugable en 1836 y celebra elecciones si su gobierno las tiene.
21. Las 5 banderas procedurales (TAG, _communist, _fascist, _monarchy, _republic) se muestran al cambiar de gobierno.
22. Un grupo cultural nuevo con unit y leader de un grupo existente usa sus gráficos de unidades y retratos.
23. Un continente con nombre nuevo carga y se localiza; los continentes con los nombres de la instalación conservan los efectos de `pop_types`.
24. Sobre vanilla: las provincias nuevas creadas desde `max_provinces` son colonizables u ocupables, y las provincias de mar recortadas siguen siendo navegables con su posición regenerada.
25. Un mapa con muchas más provincias que vanilla (p. ej. 6 000) carga; límite práctico de ids por debajo de 65 536.
26. `common/countries.txt` del nivel Mundo con los TAG existentes conservados, `REB` y el bloque `dynamic_tags` de la instalación: los dominios D01–D50 siguen funcionando.
27. Las POPs con tabla de presencia (sin craftsmen, clerks ni capitalists fuera de las capitales civilizadas) no producen paro ni militancia anómalos en el primer año.
28. La cámara de `bookmarks.txt` (cameraX/cameraY generados) centra la vista en el país elegido al empezar.

---

## 20. Trabajo con 2 agentes

- **Paso 0 de cada iteración (orquestador).** Un commit de contrato con las firmas de este documento: dataclasses, `Protocol` y funciones que lanzan `NotImplementedError`. El agente A implementa y el B consume.
- **Propiedad de archivos.** Cada iteración asigna conjuntos disjuntos (ver el plan). Los archivos compartidos (`ui/main_window.py`, `i18n/__init__.py`, `pyproject.toml`, `tests/_minigame.py`) tienen un único dueño por iteración; el otro agente pide los cambios por el orquestador.
- **Sin listas centrales.** Esquemas, salas, secciones, reglas y extractores se registran por descubrimiento (`pkgutil.iter_modules`). Los textos van en `i18n/<lang>/<área>.json` y `core/schemas/texts/<kind>.<lang>.json`, con una prueba de duplicados. Los iconos, en `ui/widgets/icons_extra/<sala>.py`.
- **Cuando B necesita lo de A antes de tiempo.** Usa el minijuego y el contrato. Las pruebas de B que dependen de A se marcan `skipUnless(implemented(...))` hasta la integración, que se hace al final de la iteración con verificación adversarial.
- **Ritmo.** Contrato → implementación en paralelo → integración → verificación adversarial → correcciones → capturas → informe al usuario en español.

---

## 21. Cambios en el código existente

| Archivo | Cambio |
|---|---|
| `core/encoding.py` | `detect_newline` devuelve `"\r"` si solo hay CR (H2). **Hecho en la iteración 1**, con la firma `detect_newline(text, *, lone_cr=True)`: con `lone_cr=False` un CR suelto no cuenta (el CSV del juego solo parte filas en LF). |
| `core/clausewitz/lexer.py` | Comentarios hasta `\r` o `\n` en `_TRIVIA` y `_COMMENT_SCAN_RE`; líneas contadas con `\r\n`, `\r` y `\n`; `newline_split` y `last_line_indent` aceptan `\r`. **Hecho en la iteración 1**: los dos patrones usan `#[^\r\n]*`, `LINE_BREAK_RE` es `\r\n?\|\n` y las dos funciones buscan los saltos con `first_break` y `last_break_end`, que tratan `\r`. |
| `core/clausewitz/nodes.py` | `Block.index_of(entry)` y `Block.insert_before(key, new_key, value)`, o sus equivalentes si la API de edición que se está ampliando en la iteración 1 ya los trae. **La iteración 1 trajo los equivalentes, con otra firma**: `Block.insert_before(entry, key, value, op="=")` e `insert_after(...)` reciben la entrada vecina, no su clave (se busca antes con `find`); `index_of` no es pública (el índice lo dan `block.entries.index(entry)`, que compara por identidad, y `remove_entry`). La búsqueda sin mayúsculas ya existe (`ignore_case`). |
| `core/clausewitz/serializer.py` | Se extrae `render_checked(document_or_result, *, encoding=None) -> bytes`; `write_file` la usa sin cambiar su comportamiento. |
| `core/csvloc/serialization.py`, `db.py` | `render_csv_checked(file) -> bytes`; `LocalisationDB.from_entries(entries)` para alimentarla desde la VFS con los documentos sucios. Se corrige el docstring que atribuye a vanilla los `?` (vienen de la copia del usuario, H15). |
| `core/fileio.py` | `stage_bytes`, `commit_staged`, `fsync_dir`; `atomic_write_bytes` se reimplementa encima con la misma firma. |
| `core/modfile.py` | Escritor del descriptor (§14.1). `read_descriptor` y `find_descriptor` no cambian. **Ya hay un escritor desde la iteración 1, con otra firma**: `write_descriptor(file, descriptor: ModDescriptor, *, backup=True)` edita un `.mod` existente cambiando solo los campos que difieren (conserva comentarios, claves desconocidas, formato y codificación, salvo UTF-16, que pasa a cp1252) o crea uno canónico en cp1252 con CRLF. Falta la API de §14.1 (`DescriptorSpec`, `render_descriptor`, `descriptor_problems`, `create_mod_skeleton` y `sanitize_folder`). |
| `core/modcheck.py` | `Issue` gana `entity` y `fixes` con valores por defecto; `check_file` alimenta la familia «syntax» del validador. |
| `i18n/__init__.py` | `load_catalog(code)` combina `es.json` con `es/*.json` y los textos del núcleo, y lanza un error ante claves duplicadas. |
| `ui/pages/project_page.py` | Pasa a ser la sección «Archivos» de la sala Proyecto, con insignias de capa J (juego), M (mod) y M⊃J (sustituye). `inspect_folder`, `evaluate_*`, `same_folder` y `_is_under` se mudan a `core/vfs/guard.py`. Las rutas del juego y del mod pasan a Inicio. |
| `ui/pages/localisation_page.py`, `ui/viewers/localisation_editor.py` | Pasan a la sala Textos. `LocalisationModel` se vuelve editable (`ItemIsEditable`; `setData` → LocSync dentro de una transacción) y gana filtros. |
| `ui/viewers/clausewitz_viewer.py` | `StructureIndex` y `build_index` se reutilizan en la pestaña «Código» y para navegar a un campo; la edición de texto emite `replace_model`. |
| `ui/main_window.py`, `ui/pages/__init__.py` | `PAGE_CLASSES` → `HALLS` (7 salas), acciones globales, paneles de problemas e historial, selector de mod, contador de cambios y `closeEvent`. |
| `ui/pages/planned.py`, `map_page.py`, `countries_page.py`, `events_page.py` | Se retiran cuando exista su sala; `RoadmapStrip` pasa a Inicio. |
| `ui/tasks.py` | Se mantiene su API (`TaskRunner`, `TaskContext` y cancelación con `core/cancel.py`). El índice, el mapa y la línea base lo usan, cada uno con su propio grupo de hilos. El taller calcula en un proceso trabajador propio (§18.4) y `ui/mapforge/worker_client.py` lleva sus resultados a las señales de `ui/session.py`. |
| `tests/test_ui_smoke.py` | Las expectativas pasan de 5 páginas a 7 salas. |
| `tests/_corpus.py` | `vanilla_root()`, `user_mod_full()` y `.map` en `CLAUSEWITZ_SUFFIXES`. |
| `pyproject.toml` | `package-data` con los nuevos JSON (§4.1). |
| `ARCHITECTURE.md` | §2.2–2.4, §3.1 (la protección es «solo el mod», H24) y §6 remiten a este documento. |

---

## 22. Plan de iteraciones

Cada iteración sigue el ritmo de §20 (contrato, trabajo en paralelo, integración, verificación adversarial, capturas e informe). El plan parte del repositorio tal como quede al cerrar las tareas pendientes de la iteración 1 (T1–T5 de `CONTINUAR_EN_CLAUDE_CODE.md`); la cancelación cooperativa de `core/cancel.py` ya está.

| Iter. | Nombre | Capacidades |
|---|---|---|
| 2 | Cimientos: VFS, proyecto transaccional, generador `.mod`, arreglo CR y armazón de 7 salas | 1 |
| 3 | Índice de símbolos, validación con línea base, localización editable sincronizada y Ctrl+K | (requisito del editor CSV) |
| 4 | Motor de esquemas y editor genérico: gobiernos, CB, bookmarks, culturas, unidades terrestres y navales | 4, 9, 10, 11, 12, 13 |
| 5 | Editor de mapa: provincias, POPs, modos, regiones, continentes, climas y estrechos | 3, 14 |
| 6 | Naciones y guerra: asistente de países, ficha nacional, banderas, OOB, diplomacia y guerras de inicio | 2, 8 |
| 7 | Event Studio y decisiones: catálogo, constructor AND/OR/NOT, MTTH, opciones | 5, 7 |
| 8 | Suite de interfaces (.gui/.gfx) e imágenes | 6 |
| 9a | Taller de mapas: mapa procedural, importación de bitmaps y «Solo mapa» jugable | 15 (mapa) |
| 9b | Taller de mapas: mundo, importación de FMG JSON, banderas y «Sobre vanilla» | 15 (mundo y mapa existente) |
| 10 | Pulido, rendimiento, exportación y empaquetado | — |

La 9b depende de la receta `new_country` de la iteración 6.

### Iteración 2 — Cimientos: VFS, proyecto transaccional, generador .mod, arreglo CR y armazón de 7 salas

**Objetivo.** Abrir o crear un mod sobre vanilla y recorrer las 7 salas con tres garantías probadas: nada se escribe fuera del mod, todo cambio se deshace y un guardado de varios archivos es todo o nada. Entrega la capacidad 1 (archivo .mod) y comprueba que sigue corregido el fallo latente de los saltos de línea solo CR, que se arregló en la iteración 1.

**Entregables.**

- Commit de contrato (paso 0): `core/vfs/model.py`, `core/project/model.py` (DocKind, DocHandle, PlannedWrite, SaveReport, UndoStep), señales de `ui/session.py` y `ui/halls/registry.py` (SectionSpec).
- Arreglo CR en `core/encoding.py` y `core/clausewitz/lexer.py` (comentarios hasta `\r` o `\n`, líneas por `\r\n|\r|\n`, `detect_newline` → `"\r"`): llegó con las correcciones de la iteración 1, así que aquí solo se comprueba la regresión.
- `core/vfs/{paths,rules,guard,vfs}.py`: VPath, LOAD_RULES, WriteGuard por realpath y VirtualFS (resolve, stack, mod_target, replace_path, snapshot, refresh). `evaluate_*`, `inspect_folder`, `same_folder` y `_is_under` se mudan de `ui/pages/project_page.py` a `core/vfs/guard.py`.
- `core/fileio.py` (stage_bytes, commit_staged, fsync_dir), `serializer.render_checked` y `csvloc.render_csv_checked`.
- `core/project/{documents,codecs,workspace,undo,journal,recovery,lock,settings,diffing,project}.py`: documentos con códecs, transacciones con nombre, deshacer por instantáneas, guardado con diario, recuperación, bloqueo, cambios externos, autoguardado y `project.json`.
- `core/modfile.py`: DescriptorSpec, render_descriptor, descriptor_problems, create_mod_skeleton y sanitize_folder. Además, `core/appdirs.py` y `core/texts.py`.
- `ui/session.py`, `ui/shell/*` y `ui/halls/project/*` (Inicio; Descriptor .mod con «Nuevo mod»; Archivos, que es la ProjectPage actual con insignias de capa). Diálogos `ui/dialogs/{save_review,conflict,recovery,new_mod}.py`.
- MainWindow con las 7 salas (las que aún no existen se ven como tarjeta «en desarrollo» con su iteración), Ctrl+1..7, Ctrl+S/Z/Y, contador de cambios y `closeEvent`.
- i18n por fragmentos (`i18n/<lang>/*.json`) y `package-data` ampliado en `pyproject.toml`.
- Pruebas: `tests/_layers.py`, `tests/_minigame.py` mínimo, `test_vfs_*`, `test_project_*`, `test_journal_*`, `test_undo_*`, `test_arch_writes`, `test_lexer_cr`, `test_noop_save`, `test_modfile_write`, `test_ui_shell` y `test_ui_descriptor`. `tools/screenshot.py` admite `--hall`, `--section` y `--no-game-art`.

**Reparto entre los 2 agentes.** Agente A (núcleo): `core/encoding.py`, `core/clausewitz/{lexer,serializer,nodes}.py`, `core/csvloc/serialization.py`, `core/fileio.py`, `core/vfs/**` (incluidas las funciones mudadas), `core/project/**`, `core/appdirs.py`, `core/texts.py`, `tests/_layers.py`, `tests/_minigame.py` y `tests/test_{lexer_cr,vfs_*,project_*,journal_*,undo_*,arch_writes,noop_save}.py`. Agente B (descriptor e interfaz): `core/modfile.py`, `ui/session.py`, `ui/main_window.py`, `ui/pages/__init__.py`, `ui/pages/project_page.py` (solo cambia sus imports), `ui/shell/**`, `ui/halls/**`, `ui/dialogs/**`, `ui/widgets/layer_badge.py`, `i18n/__init__.py`, `i18n/{es,en}/{shell,project}.json`, `pyproject.toml`, `tools/screenshot.py` y `tests/test_{modfile_write,ui_shell,ui_descriptor,ui_smoke}.py`. B trabaja contra el contrato con un Project falso construido con `tests/_layers.py` hasta la integración.

**Criterios de aceptación.**

1. Todas las pruebas pasan sin corpus, con `tests/fixtures/shago_mod_min` y con `VIC2_CORPUS` completo; la ida y vuelta byte a byte del corpus se mantiene.
2. `parse("a = 1 # c\rb = 2\r")` da 2 entradas, en las líneas 1 y 2, y `detect_newline` devuelve `"\r"`.
3. Minijuego con mod vacío: cambiar `months` de un CB y guardar crea solo `<mod>/common/cb_types.txt` (copia con 1 línea de diff respecto al juego). Vanilla + VSM: el mismo cambio modifica la copia de VSM con un diff de 1 línea. En los dos casos los hashes del juego base no cambian.
4. Abrir el proyecto y guardar sin cambios no escribe nada en el mod (árbol y fechas de modificación idénticos) y no crea `.vic2studio/`.
5. WriteGuard rechaza `<juego>/common/x.txt`, rutas con `..` y enlaces simbólicos que salen del mod, y admite `<juego>/mod/VSM/**` y `<juego>/mod/VSM.mod`.
6. Un fallo inyectado en cada paso de un guardado de 3 archivos (y `os._exit` en un subproceso) deja, tras `recover()`, todo como antes o todo como después; recuperar dos veces da lo mismo.
7. Deshacer y rehacer una transacción de 3 archivos es exacto byte a byte; deshacer hasta el punto guardado deja el documento limpio.
8. `render_descriptor(DescriptorSpec("Shago Mod", "VSM", "VSM"))` es igual byte a byte a `tests/fixtures/shago_mod_min/VSM.mod`; «Dark Age Mod» con carpeta DAM da `path = "mod/DAM"` y `user_dir = "DAM"` en cp1252 con CRLF.
9. `test_arch_writes` pasa: ninguna primitiva de escritura cruda fuera de `core/fileio.py`; dentro del mod solo escribe `core/project/journal.py`, siempre tras `WriteGuard.check`; las demás llamadas a `fileio` salen solo de `core/project/lock.py` (rutas de `core/appdirs.py`), de los envoltorios `serializer.write_file` y `csvloc.write_csv_file` y de las excepciones declaradas en la prueba (`ui/theme.py`, CLI).
10. Capturas ES/EN a 1100×700 y 1920×1080 de Inicio, Descriptor .mod, Archivos y el diálogo de revisión, sin textos cortados ni claves crudas.
11. Verificación adversarial con cada hallazgo reproducido antes de reportarlo y con su prueba de regresión. Lista de comprobación en el juego: el mod creado con «Nuevo mod» aparece en el lanzador y carga.

### Iteración 3 — Índice de símbolos, validación con línea base, localización editable sincronizada y Ctrl+K

**Objetivo.** El Studio sabe qué existe y qué está roto en la vista efectiva, con los cambios sin guardar, y no culpa al mod de los fallos de vanilla. La localización se edita en una tabla con sincronización de claves (requisito del editor CSV) y Ctrl+K encuentra cualquier símbolo.

**Entregables.**

- `core/index/{model,cache,builder,index}.py` con extractores de países, partidos, provincias, mapa, culturas, religiones, gobiernos, ideologías, reformas, tecnologías, invenciones, bienes, edificios, tipos de POP, unidades, CB, eventos, decisiones, bookmarks, guerras, sprites, imágenes y localización. Caché JSON-lines por capa e índice incremental.
- `core/validate/{model,registry,context,baseline,fixes,explain}.py` (SimpleFix y explicador de conflicto, §11.1) y reglas `{syntax,files,descriptor,countries,provinces,localisation,events,decisions}` con los textos `issues.{es,en}.json`. `modcheck.Issue` gana `entity` y `fixes`.
- `core/rules/{game,ids,names,colors}.py`, `core/lua_defines.py` y `core/locsync.py` (política de §8).
- SimpleFix (§11.1): registrar el TAG antes de `dynamic_tags`, convertir a cp1252, «Añadir `}` al final», «Recuperar las filas de vanilla» (`loc_copy_degraded`) y «Mover a la papelera las copias idénticas» (`mod_shadow_identical`), todos con plan de cambios previo y confirmación. Explicador de conflicto para cada código del catálogo.
- Interfaz: sala Textos (modelo editable, añadir clave, filtros «creadas por el Studio», «sin traducir», «sustituye a vanilla» y «degradadas»), Proyecto › Validación (columnas de entidad, conmutador de heredados, [Arreglar] y [¿Por qué?] con el panel del explicador), panel de problemas y paleta Ctrl+K.

**Reparto entre los 2 agentes.** Agente A: `core/index/**`, `core/validate/**`, `core/rules/**`, `core/lua_defines.py`, `core/modcheck.py` y `tests/test_{index_*,validate_*,rules_*,lua_defines}.py`. Agente B: `core/locsync.py`, `ui/halls/localisation/**`, `ui/viewers/localisation_editor.py`, `ui/pages/localisation_page.py`, `ui/halls/project/validation.py`, `ui/shell/{command_palette,problems_dock}.py`, `i18n/{es,en}/{localisation,validation,palette}.json` y `tests/test_{locsync,loc_effective,ui_loc_edit,ui_validation,ui_palette}.py`. Contrato: Symbol, SymbolRef, SymbolIndex, Problem y el decorador `rule`. B usa un índice en memoria construido sobre el minijuego.

**Criterios de aceptación.**

1. Con corpus, los recuentos del índice son: 271 TAG + 50 dinámicos, 2 703 provincias de tierra (3246 incluida) y 545 de mar, 549 regiones, 6 continentes, 34 grupos y 226 culturas, 8 gobiernos, 31 CB, 21 tipos de unidad (11 + 10), 150 tecnologías, 387 invenciones, 1 064 eventos, 151 decisiones y 2 bookmarks.
2. Construcción en frío del índice de vanilla en segundo plano en menos de 6 s y menos de 1 s desde la caché. Cambiar un archivo reprocesa solo ese archivo (contador de parseos) y subir la versión de un extractor invalida solo su caché.
3. Validar VSM: los errores no heredados son exactamente `tag_not_registered` (SIL), `nationalvalue_unknown` ×4 (GEL, MAJ, SOM y WRL) y 2 `unclosed_block`. Los avisos incluyen `ruling_party_ideology_not_allowed` (SOM_socialist), `party_unknown_policy` (`social_policy`), `government_election_without_duration` (`absolute_monarchy`) y `loc_copy_degraded` (`text.csv`, 3 429 filas). Cualquier otro aviso se revisa en la verificación adversarial y se clasifica.
4. Los problemas de vanilla salen como heredados y ocultos por defecto: 13 partidos, 50 `civilized`, 27 colores, 1396/1397, `HAI_oob.txt`, el evento 11108 y `annex`.
5. «Registrar SIL» inserta la línea justo antes de `dynamic_tags`, delante de los comentarios que lo preceden (diff de 1 línea); revalidar quita el error y Ctrl+Z lo deshace. El explicador de `tag_not_registered` muestra las capas (historia, archivo de país, banderas y dueño en 682–685 frente a `countries.txt`) y el de `loc_copy_degraded` muestra que el `text.csv` del mod sustituye al del juego.
6. Minijuego con mod vacío: editar una clave cuyo ganador es del juego crea `localisation/00_<P>_overrides.csv` con esa fila y no copia el CSV del juego. En VSM, que tiene su propio `text.csv`, la fila se edita en esa copia con un diff de 1 línea.
7. Ctrl+K encuentra «549», «Berlín», «PRU» y «north_german» y abre el archivo en su línea (o el editor de la entidad cuando exista).
8. Capturas ES/EN de Textos, Validación y la paleta; verificación adversarial con hallazgos reproducidos.

### Iteración 4 — Motor de esquemas y editor genérico: gobiernos, casus belli, bookmarks, culturas, unidades terrestres y navales

**Objetivo.** Que una entidad nueva cueste un esquema, sus textos y una prueba: el motor genera la lista, el formulario, la validación, las claves de localización, la documentación y las pruebas. Sobre él quedan completas las capacidades 4, 9, 10, 11, 12 y 13.

**Entregables.**

- `core/schema/{types,fields,entity,layouts,record,history,placement,companions,recipes,validate,texts,docgen,registry,__main__}.py`, con la API pública en `core/schema/__init__.py`.
- `core/schemas/{government,casus_belli,bookmark,culture,unit,event_modifier,readonly}.py` con sus textos ES/EN. `readonly` cubre tecnologías, invenciones, ideologías, reformas, bienes y edificios, que solo se indexan.
- Compañeros AppendToList(peace_order), MappingTable(rebel_types), ActivateUnit y UnitNamesSlot.
- `tests/schema_harness.py` (SchemaContract) y `test_schema_<kind>.py`; `docs/referencia/` generada con `python -m vic2studio.core.schema doc`.
- `ui/forms/**` (FormBuilder, EDITORS, tablas repetidas, claves dinámicas y campos de localización), `ui/entity/**` (navegador y editor con las pestañas Formulario, Textos, Usos, Código y Otros campos) y los selectores básicos de `ui/pickers/**` (SymbolPicker, DateEdit, ColorField, GoodsAmountsField, NameListEditor y SpriteFramePicker).
- Secciones Naciones › Culturas y Gobiernos, y Guerra › Fechas de inicio, Casus belli, Unidades terrestres y Unidades navales. Matriz de rebeldes y editor mínimo de `end_date` en `defines.lua`.

**Reparto entre los 2 agentes.** Agente A: `core/schema/**`, `core/schemas/**`, `tests/schema_harness.py`, `tests/test_schema_*.py` y `docs/referencia/**`. Agente B: `ui/forms/**`, `ui/entity/**`, `ui/pickers/**`, `ui/halls/{nations,war}/__init__.py`, `ui/widgets/icons_extra/{nations,war}.py`, `i18n/{es,en}/{forms,entity,pickers}.json` y `tests/test_ui_{forms,entity}.py`. Contrato: las dataclasses de esquema y los stubs de Record, RecordRef y Entities. B usa un esquema falso con todos los tipos de campo hasta la integración.

**Criterios de aceptación.**

1. Conformidad con vanilla sin `unknown_field` ni `bad_type`: 8 gobiernos, 31 CB, 2 bookmarks, 34 grupos y 226 culturas, y 21 unidades. Abrir y guardar sin cambios no escribe nada.
2. Cambiar `attack` de infantry modifica una sola línea de `units/infantry.txt`.
3. Crear el CB my_cb lo añade al final de `peace_order` y crea sus 4 claves en `localisation/00_<P>_cb.csv`. Borrarlo mientras se usa se bloquea y muestra los usos. Un solo Ctrl+Z deshace la creación entera.
4. Crear el gobierno junta copia `governments.txt` y `rebel_types.txt` al mod, lo añade a las 14 tablas y crea las claves `junta` y `junta_ruler`; `election = yes` sin `duration` da el aviso.
5. Las unidades terrestres y las navales salen en dos secciones del mismo esquema. «Basada en infantry» crea `units/<id>.txt` y las claves `<id>` y `<id>_short`.
6. Añadir el esquema `event_modifier` no toca ningún archivo de `ui/` (la sección aparece por descubrimiento), y su `test_schema_event_modifier.py` es una subclase de 3 líneas.
7. docgen genera la referencia ES/EN de cada esquema sin claves sin traducir. Capturas ES/EN de las 6 secciones y verificación adversarial.

### Iteración 5 — Editor de mapa: provincias, POPs, modos, regiones, continentes, climas y estrechos

**Objetivo.** Ver y editar el mapa existente con clic y brocha en la fecha de trabajo: modos político, RGO, infraestructura, life rating, terreno y regiones, sin romper sus invariantes. Cubre las capacidades 3 y 14.

**Entregables.**

- `core/map/{bmp,definition,raster,cache,facts,modes,borders,geometry,adjacency,positions,groups,coherence}.py` y `core/tablecsv.py`.
- Esquemas `{province_history,pops,region,region_sea,continent,climate,terrain,default_map,adjacency}` con sus textos, `core/domain/{province,pops}.py` y `core/validate/rules/map.py`.
- `ui/map/{canvas,layers,modes_bar,legend,province_panel,pops_editor,brush,region_tool,straits_tool,timeline}.py` y `ui/halls/map/**` (Mundo, Regiones, Continentes y climas, Estrechos y canales).
- ProvincePicker con MapPickDialog, selector global de la fecha de trabajo, «Usar la vista actual del mapa» para la cámara de los bookmarks, modo IDs y `tools/bench_map.py`.

**Reparto entre los 2 agentes.** Agente A: `core/map/**`, `core/tablecsv.py`, `core/schemas/{province_history,pops,region,region_sea,continent,climate,terrain,default_map,adjacency}.py` y sus textos, `core/domain/{province,pops}.py`, `core/validate/rules/map.py` y `tests/test_{map_*,schema_province,bmp_roundtrip,tablecsv}.py`. Agente B: `ui/map/**`, `ui/pickers/province_picker.py`, `ui/halls/map/**`, `i18n/{es,en}/map.json`, `tools/bench_map.py` y `tests/test_ui_map.py`. Contrato: ProvinceRaster, ProvinceFacts, MapMode, ProvinceGroups, PopsIndex y la fachada de provincia. B usa el ráster del minijuego.

**Criterios de aceptación.**

1. Ida y vuelta byte a byte de `provinces.bmp`, `terrain.bmp` y `rivers.bmp` de vanilla; `definition.csv` conserva «223.» y las 56 filas sin id.
2. Orientación: el centroide de Berlín (549) cae en la fila 1675,6, frente a `y=1676` de `positions.txt`, y al menos el 95 % de los puntos `unit` caen en su provincia o junto a ella. Sin corpus, el fixture asimétrico de 64×32 fija el norte arriba en la vista.
3. Rendimiento con vanilla (`tools/bench_map.py`): ráster en ≤ 4 s en segundo plano y ≤ 0,5 s desde la caché, cambio de modo ≤ 150 ms y repintado tras cambiar un dueño ≤ 50 ms.
4. Con vanilla + mod vacío, cambiar el dueño de 549 y guardar crea solo `history/provinces/germany/549 - Berlin.txt`, con un diff de 1 línea.
5. Editar en 1861.7.1 escribe en el bloque `1861.1.1` que ya tiene 549; no crea uno nuevo.
6. Los POPs de 549 en 1836.1.1 salen de `history/pops/1836.1.1/Germany.txt`. La provincia 2482 muestra sus dos bloques de `1861.4.14/Australia.txt` y se edita el elegido.
7. Prueba de propiedad de la brocha de regiones: tras cada movimiento, cada provincia de tierra sigue en exactamente un estado.
8. `check_map(vanilla)` reproduce la línea base (27 colores sin id, «223.», 1396/1397 y el 2800 repetido en `sea_starts`), y `check_map` del minijuego da 0 errores.
9. Capturas ES/EN de los modos y del panel de provincia; verificación adversarial; lista de comprobación en el juego (el dueño cambiado se ve en 1836).

### Iteración 6 — Naciones y guerra: asistente de países, ficha nacional, banderas, OOB, diplomacia y guerras de inicio

**Objetivo.** Crear un país jugable de principio a fin con un asistente que se deshace en un paso, editar cualquier país en la ficha nacional en la fecha de trabajo y montar guerras de inicio. Cubre las capacidades 2 y 8.

**Entregables.**

- `core/gfx/flags.py`: fit_flag y make_flag_set (5 TGA de 93×64 y 32 bits, con origen abajo a la izquierda, que se releen con Pillow).
- `core/domain/{tags,country}.py`: check_tag, suggest_tags, NewCountrySpec y plan_new_country.
- Esquemas `{country_registry,country,country_colors,country_history,oob,war,diplomacy}` con sus textos, y las recetas `new_country` y `new_war`.
- Reglas `ruling_party_*`, `upper_house_sum`, `capital_not_owned`, `country_history_*`, `flag_*`, `army_location_sea`, `navy_location_inland`, `regiment_type_mismatch` y `war_*` en `core/validate/rules/{countries,military,history}.py`.
- `ui/countries/{wizard/*,sheet/*,flag_studio.py,upper_house.py,oob_editor.py}`, los selectores `{tag_picker,culture_picker,tech_tree,issue_picker}` y `ui/halls/war/{wars,war_timeline,diplomacy}.py`.

**Reparto entre los 2 agentes.** Agente A: `core/gfx/flags.py`, `core/domain/{tags,country}.py`, `core/schemas/{country_registry,country,country_colors,country_history,oob,war,diplomacy}.py` y sus textos, `core/validate/rules/{countries,military,history}.py` y `tests/test_{flags,schema_country*,country_create,validate_military,schema_war}.py`. Agente B: `ui/countries/**`, `ui/pickers/{tag_picker,culture_picker,tech_tree,issue_picker}.py`, `ui/halls/nations/countries.py`, `ui/halls/war/{wars,war_timeline,diplomacy}.py`, `i18n/{es,en}/{countries,war}.json` y `tests/test_ui_{country_wizard,country_sheet,wars}.py`. Contrato: NewCountrySpec, ChangePlan, la API de banderas y el modelo de guerra.

**Criterios de aceptación.**

1. El asistente, sobre el minijuego, crea exactamente los archivos de su plan (registro con 1 línea más antes de `dynamic_tags`, archivo de país, historia, 5 banderas, claves y provincias reasignadas) en una transacción que un solo Ctrl+Z deshace.
2. `check_tag` rechaza PRU (usado), D07 (dinámico), CON (dispositivo de Windows), AND (palabra de guion), REB (reservado) y 12A (patrón), y sugiere TAG libres.
3. Las 5 banderas generadas son TGA de 93×64 y 32 bits con origen abajo a la izquierda, y Pillow las relee.
4. «Copiar partidos de PRU» crea los partidos con el prefijo del TAG nuevo. Con VSM, SOM_socialist da el aviso con su arreglo.
5. La ficha nacional se abre con doble clic en el mapa y edita tecnologías, reformas, `upper_house` (suma 100), prestigio y pluralidad en la fecha de trabajo.
6. Una guerra nueva se escribe con el formato de `ACW.txt`. Las 5 guerras y los 4 archivos de diplomacia de vanilla hacen ida y vuelta. Un `war_goal` con un CB que no existe o con un actor fuera de la guerra es un error.
7. Capturas ES/EN de cada paso del asistente y de la ficha; verificación adversarial; lista de comprobación en el juego (el país nuevo es jugable en 1836 y la guerra está activa).

### Iteración 7 — Event Studio y decisiones: catálogo, constructor AND/OR/NOT, MTTH y opciones

**Objetivo.** Escribir eventos de país y de provincia, y decisiones, sin tocar código: condiciones y efectos con buscadores, MTTH con modificadores y opciones con `ai_chance` y vista previa. Lo que el catálogo no conozca se conserva sin pérdidas. Cubre las capacidades 5 y 7.

**Entregables.**

- `core/script/{catalog,tree,scopes,phrases,mtth,idalloc}.py` y `core/script/data/{triggers,effects,scopes}.json` (solo nombres, tipos y frases propias), más `tools/catalog_census.py`.
- Esquemas `{event,decision,mtth}` con sus textos y `core/validate/rules/{events,decisions}.py`.
- `ui/script/{trigger_builder,effect_builder,catalog_picker,mtth_editor,option_cards,event_preview,decision_preview,picture_picker,phrase_view}.py` y `ui/halls/events/**` (Eventos, Decisiones y Modificadores).
- Los bloques de guion de los CB (`can_use`, `is_valid`…) pasan del editor de código al constructor.

**Reparto entre los 2 agentes.** Agente A: `core/script/**`, `tools/catalog_census.py`, `core/schemas/{event,decision,mtth,casus_belli}.py` y sus textos, `core/validate/rules/{events,decisions}.py` y `tests/test_{script_*,schema_event,schema_decision}.py`. Agente B: `ui/script/**`, `ui/halls/events/**`, `i18n/{es,en}/{events,script}.json` y `tests/test_ui_{event_studio,decisions}.py`. Contrato: ScriptKeyDef, ScriptCatalog, ScriptNode y ScriptTree. B usa un catálogo de 20 entradas hasta la integración.

**Criterios de aceptación.**

1. El árbol de guion hace ida y vuelta byte a byte en los 82 archivos de eventos y los 29 de decisiones de vanilla, y cambiar el valor de un nodo cambia solo su línea.
2. El catálogo cubre al menos el 95 % de los usos de vanilla según el censo; el resto se muestra como nodo crudo y se conserva.
3. Un evento nuevo recibe el primer id libre del rango del proyecto, va a `events/<P>_events.txt` y crea EVTNAME, EVTDESC, EVTOPTA y EVTOPTB en `00_<P>_events.csv`. Editar un evento de vanilla copia su archivo entero a la misma ruta.
4. Las 2 decisiones rotas del usuario se abren en modo texto con su diagnóstico, y el arreglo «Añadir `}` al final» habilita el formulario.
5. La frase de AUSFlavor 31502 nombra Austria y Austria-Hungría, «1842 o después», los tres gobiernos y «antes de 1845», y el editor de MTTH muestra el tiempo efectivo.
6. La comprobación de ámbitos avisa de una condición de país dentro de un ámbito de provincia, y un id duplicado se rechaza proponiendo el siguiente libre.
7. Capturas ES/EN del Event Studio y del editor de decisiones; verificación adversarial; lista de comprobación en el juego (el evento nuevo se dispara y la decisión aparece).

### Iteración 8 — Suite de interfaces (.gui/.gfx) e imágenes

**Objetivo.** Ver y modificar las ventanas del juego (mover, redimensionar y cambiar sprites, textos y fuentes) y crear sprites a partir de imágenes propias, con una vista previa fiel y sin meter arte de Paradox en el repositorio. Cubre la capacidad 6.

**Entregables.**

- `core/gui/{gfxdb,guimodel,layout,bmfont,textures}.py` y `core/gfx/{dds,images}.py`, con un escritor DDS A8R8G8B8 sin comprimir.
- Esquemas `{gfx,gui_elements}` con sus textos y `core/validate/rules/interface.py`.
- `ui/interface/{gui_canvas,gui_tree,sprite_browser,import_dialog,picture_manager}.py` y `ui/halls/interface/**` (Ventanas, Sprites, e Imágenes y banderas).
- La vista previa de eventos pasa al renderizador `.gui` real, con la alternativa procedural.

**Reparto entre los 2 agentes.** Agente A: `core/gui/**`, `core/gfx/{dds,images}.py`, `core/schemas/{gfx,gui_elements}.py` y sus textos, `core/validate/rules/interface.py` y `tests/test_{gui_*,dds}.py`. Agente B: `ui/interface/**`, `ui/halls/interface/**`, `ui/script/event_preview.py`, `i18n/{es,en}/interface.json` y `tests/test_ui_interface.py`. Contrato: SpriteDB, GuiDocument, `layout()` y BMFont.

**Criterios de aceptación.**

1. Los 59 `.gui` y los 66 `.gfx` de vanilla cumplen sus esquemas. Las 434 texturas con otra extensión se resuelven, y las 27 que faltan y los 13 sprites duplicados salen como heredados. `Orientation`/`orientation` y `UPPERL_LEFT` se reconocen.
2. Arrastrar un elemento cambia solo su línea `position` en la copia del `.gui` en el mod.
3. Importar un PNG crea un DDS sin comprimir que Pillow relee, y su `spriteType` en `interface/<p>_studio.gfx`.
4. Vistas previas a 1024×768 y 1920×1080. Sin juego configurado se usa la alternativa procedural, y una prueba confirma que el repositorio no contiene recursos del juego.
5. Capturas ES/EN (con `--no-game-art`) y verificación adversarial.

### Iteración 9a — Taller de mapas: mapa procedural, importación de bitmaps y «Solo mapa» jugable

**Objetivo.** Generar un mapa al estilo de Azgaar, o importarlo desde bitmaps, editarlo entre pasos con vista previa en vivo y exportarlo con el nivel «Solo mapa»:
- todo `map/` y las texturas;
- historias de provincia con dueño, repartido entre los TAG existentes, o el mapa base sin dueño;
- POPs mínimas con tabla de presencia, RGO, life rating, nombres (`syllables`/`custom`) y localización;
- OOB vaciados, `capital` corregida, `replace_path`, papelera de los archivos del mod y auditoría.

Todo el cálculo va en un proceso trabajador. Cubre la capacidad 15 (parte de mapa).

**Entregables.**

- **Paso 0, commit de contrato.** `core/mapforge/{params,world,pipeline,worker,edits,project}.py` con las firmas de §18.7: `ForgeParams`, `LatticeSpec`, `ExportTarget`, `Owners`, `ForgeWorld`, `ProvisionalTable`, `ForgeRaster`, `Step`, `StepContext`, `ForgeWorker`/`ForgeCommand`/`ForgeReply`, `EditOp`, `MapForgeProject`, `ImportSet`/`ImportReport`, `export_plan`/`export` y `DependencyAudit`.
- **Pipeline.**
  - `core/mapforge/{install,graph,relief,climate,hydro,biomes,partition,rasterize,reconcile,textures,names,society,economy,validate,export,audit}.py`;
  - todos los pasos de §18.3 salvo `flags`;
  - `society.py` solo con la expansión (países sobre TAG existentes y zonas culturales); `economy.py` con RGO, life rating y la tabla de presencia de POPs; `names.py` con las fuentes `syllables` y `custom`;
  - `core/mapforge/data/{templates,biome_table}.py`: 14 plantillas portadas de FMG, con la y convertida.
- **Importación.** `core/mapforge/imports/{bitmaps,heightmap,fmg_template}.py`: ranuras, orientación, matriz de reconstrucción, conversión RGB → paleta y pseudorrelieve.
- **Derivados.** `core/map/positions.py` (`generate` de §18.5), `core/map/adjacency.py` (`suggest_straits`) y `core/map/coherence.py` completo.
- **Texturas.** `core/gfx/dds.py`: mips hasta 1×1, cabecera de vanilla (`LINEARSIZE`) y codificador DXT3.
- **Deshacer.** `core/project/undo.py`: `Snapshot.before_path` para instantáneas de más de 8 MB y archivos movidos a la papelera (§6.3).
- **Validación.** `core/validate/rules/mapforge.py` y los textos `core/validate/texts/mapforge.{es,en}.json`. `replace_path_empty` pasa a info en las carpetas vaciadas de forma intencionada (§5.3).
- **Licencias y medidas.** `THIRD_PARTY_NOTICES.md` (FMG, MIT) y `tools/bench_mapforge.py`, también en CI con numpy 1.24 y Pillow 10.
- **Interfaz.**
  - `ui/mapforge/{wizard,preview,brushes,province_tools,entity_tables,import_panel,review,audit_view,worker_client}.py`;
  - las pantallas 0–7 (7 = «Dueños»), 9, 10 (solo nombres), 11, 12 y 13 en `ui/mapforge/steps/*.py`, con modo sencillo y «Generación rápida»;
  - `ui/halls/map/forge.py`.
  - El origen FMG JSON no aparece.

**Reparto entre los 2 agentes.**
- **Agente A (núcleo):**
  - `core/mapforge/**` (salvo `imports/fmg_json.py`, `overlay.py`, `paint.py` y `data/name_bases.py`);
  - `core/map/{positions,adjacency,coherence}.py`, `core/gfx/dds.py`, `core/project/undo.py` (`before_path`) y `core/validate/rules/mapforge.py` con sus textos;
  - `THIRD_PARTY_NOTICES.md` y `tools/bench_mapforge.py`;
  - `tests/_mapforge_fixtures.py` y `tests/test_mapforge_{pipeline,determinism,preview,raster,reconcile,positions,straits,rivers,terrain,textures,import,export,audit,owners,worker,cancel,props}.py`, más `tests/test_third_party_notices.py` y `tests/test_no_install_content.py`.
- **Agente B (interfaz):** `ui/mapforge/**`, `ui/halls/map/forge.py`, `i18n/{es,en}/mapforge.json` y `tests/test_ui_mapforge.py`.
- **Cómo trabaja B antes de la integración:** con el contrato y un `ForgeWorker` falso que devuelve un `ForgeWorld` del fixture `tiny_world` (288×144, 2 000 celdas). La vista previa reutiliza el lienzo de §16.3 sin modificarlo; si hace falta un gancho, se pide por el orquestador al dueño de `ui/map/canvas.py`.

**Criterios de aceptación.**

1. Propiedades sobre `tiny_world` (288×144) con las semillas 0–19 y sobre un render de 5616×2160 con 3 semillas (§19):
   - cada provincia de tierra en exactamente 1 estado, 1 continente y 1 clima, y el mar en ninguno;
   - colores únicos, sin negro ni blanco; biyección entre `definition.csv` y el BMP;
   - ids contiguos con la tierra primero y `max_provinces` = N+1;
   - 0 provincias partidas y 0 aisladas; 0 provincias con píxeles en x = 0 y x = W−1, con vecinos a través de la costura;
   - adyacencias simétricas;
   - la misma máscara de agua en las tres capas;
   - índice mayoritario ∈ categoría mayoritaria en el 100 % de las provincias, y solo índices que la instalación usa;
   - ríos 4-conexos, con 0 en cada nacimiento y 1 en cada confluencia;
   - tras `reconcile`, cada provincia de tierra tiene estado, historia, POPs y `PROV<id>`;
   - `check_map` da 0 errores y el resultado se abre en el editor de la iteración 5.
2. Determinismo:
   - la misma semilla, parámetros y ediciones dan el mismo sha256 en todos los archivos, también con `NPY_DISABLE_CPU_FEATURES` (sin AVX-512);
   - abrir un proyecto no recalcula la etapa de celdas;
   - regenerar `hydro` deja `provinces.bmp` y `definition.csv` idénticos;
   - una provincia bloqueada conserva sus celdas;
   - mover el deslizador de tierra después de pintar no produce `forge_edit_conflict` en los trazos de pincel.
3. La vista previa y el final comparten los hashes de la etapa de celdas y del mundo. Las diferencias solo afectan a provincias hijas o desaparecidas de `fix` (≤ 1 % de las provisionales).
4. `tools/bench_mapforge.py`, con 5616×2160, 60 000 celdas y 4 CPU:
   - vista previa ≤ 3 s;
   - render final en memoria ≤ 25 s;
   - RSS del trabajador ≤ 1,2 GiB;
   - bloqueo máximo de la interfaz ≤ 100 ms (hilo de ticks de 5 ms);
   - pincel ≤ 50 ms;
   - Cancelar ≤ 1 s, o ≤ 2 s con terminate, dejando el mundo anterior intacto.
5. Formatos:
   - `provinces.bmp` de 24 bits con los datos en el byte 54;
   - `terrain.bmp` y `rivers.bmp` de 8 bits con cabecera de 1 078 B y las paletas de la instalación (sintéticas en el fixture);
   - DDS con las medidas, el número de mips, los `flags` y el tamaño exacto de vanilla a 5616×2160: 5 414 528 / 1 796 960 (10 mips) / 1 347 968 (DXT3) / 5 414 528 / 108 656 B;
   - `definition.csv` con la cabecera en la línea 1 y CSV de localización sin comentarios; 0 nombres de archivo no ASCII;
   - positions: 100 % de `unit` dentro; < 5 % de puntos secundarios a menos de 2 px de `unit`, con medianas en [5, 16] px; `naval_base` sobre mar contiguo en el 100 % de las costeras;
   - 0 POPs urbanas en provincias sin dueño.
6. Importación:
   - un PNG con el norte arriba se voltea; con `positions.txt` se detecta solo (corpus: 100 % frente a 1,27 %);
   - con solo `provinces.bmp` y una altura se genera el resto y se cumple el criterio 1;
   - un `terrain.bmp` RGB se convierte con 0 px de diferencia;
   - ida y vuelta con bytes idénticos;
   - cada código de §18.11 tiene un fixture, y su SimpleFix y su explicador funcionan;
   - 3 bitmaps del tamaño de vanilla se importan en ≤ 10 s.
7. Exportación de «Solo mapa»:
   - los archivos de §18.8 en una transacción con diario; un fallo inyectado en cada paso deja todo antes o todo después;
   - un mod de prueba que es copia completa del minijuego queda con 0 historias o POPs ajenas tras exportar (papelera);
   - `replace_path` sin `replace_path_hides_referenced`, gracias a los OOB vacíos;
   - con «Repartir», hay ≥ 1 TAG con tierra y capital propia;
   - deshacer restaura el mod, con las instantáneas grandes en disco.
8. La auditoría, sobre vanilla más un mapa nuevo, lista por carpeta y rol los huérfanos de §18.9 y ofrece sus acciones.
9. Capturas ES/EN de cada pantalla (`--wizard mapforge --step N`, `--no-game-art`), verificación adversarial y ampliación de la lista de comprobación en el juego (§19.5). El mod de prueba en el juego se construye con el exportador real, no con un prototipo: el mapa «Repartir» carga, se elige un país y se juega un mes; el «Mapa base» carga hasta el selector.

### Iteración 9b — Taller de mapas: mundo, importación de FMG JSON, banderas y «Sobre vanilla»

**Objetivo.**
- Convertir un mapa del taller en un mundo jugable con el nivel «Mundo»: países, culturas, religiones, POPs completas, nombres de FMG o del usuario y banderas.
- Importar un «Export to JSON → Full» de FMG conservando sus entidades.
- Ampliar el mapa existente con provincias o un continente nuevos sin tocar los ids.

Cubre la capacidad 15 (mundo y mapa existente) y reutiliza la receta `new_country` de la iteración 6.

**Entregables.**

- **Paso 0, contrato.** `ForgeEntity`, `FmgWorld`, `NameSource`, `FlagSpec` y `OverlayPlan`.
- **Mundo.** `society.py` completo (TAG nuevos, grupos culturales y religiones mapeadas), mezcla completa de POPs en `economy.py`, el paso `flags` y la opción «Quitar los TAG existentes» con la auditoría de rol TAG en todo el índice.
- **Nombres.** Fuentes `fmg_bundled` y `user_corpus` en `names.py`, y `data/name_bases.py` (43 bases, MIT).
- **Importación de FMG.** `imports/fmg_json.py`.
- **Banderas.** `core/gfx/flags.py: procedural_flag`.
- **Sobre vanilla.** `core/mapforge/{overlay,paint}.py` y `ui/map/split_tool.py`.
- **Interfaz.** Pantallas 7 (países), 8, 10 (banderas) y «Elegir zona»; `ui/mapforge/flag_gallery.py` y la ranura de FMG JSON.

**Reparto entre los 2 agentes.**
- **Agente A (mundo y FMG):**
  - `core/mapforge/{society,economy,names}.py`, `core/mapforge/steps/{countries,cultures,religions,population,economy,names,flags}.py` y `core/mapforge/data/name_bases.py`;
  - `core/mapforge/imports/fmg_json.py`, `core/gfx/flags.py` (solo `procedural_flag`) y los cambios de Mundo en `core/mapforge/{export,audit}.py`;
  - `tests/test_mapforge_{world,names,flags,fmg_json,audit_tags}.py`.
- **Agente B (interfaz de mundo y «Sobre vanilla» vertical):**
  - `ui/mapforge/steps/{countries,cultures,names_flags,zone}.py`, `ui/mapforge/flag_gallery.py` e `ui/mapforge/import_panel.py` (ranura FMG);
  - `core/mapforge/{overlay,paint}.py` y `ui/map/split_tool.py`;
  - `i18n/{es,en}/mapforge.json` (B es su dueño en las dos subiteraciones);
  - `tests/test_mapforge_overlay.py` y `tests/test_ui_mapforge_world.py`.
- **Antes de la integración:** B usa `tiny_world` con entidades sintéticas.

**Criterios de aceptación.**

1. Mundo sobre `tiny_world`, semillas 0–9:
   - cada dueño está en `countries.txt` antes de `dynamic_tags`, y se conservan `REB`, D01–D50 y los TAG existentes (también los propios del mod);
   - capital propia; archivo de país (color, `graphical_culture` y partidos); historia completa (R1 §2.2); 5 banderas TGA de 93×64, 32 bits y origen abajo a la izquierda;
   - `ruling_party` admitido (H12);
   - culturas con ≥ 50 `first_names` y `last_names`;
   - POPs en cada provincia de tierra y fecha, con la tabla de presencia;
   - localización EN/ES (y FR/DE con `copy_en_to`);
   - 0 errores nuevos en la validación global.
2. Los TAG generados pasan `tag_invalid` y `tag_taken` y no colisionan con el índice. Los nombres son cp1252, únicos por tipo, y los nombres de archivo son ASCII.
3. Los pasos 12–17 tardan ≤ 3 s en total. Regenerar los países no cambia ningún archivo de `map/` (sha).
4. FMG JSON con un fixture sintético con la forma de `getFullDataJson` (200 celdas, 3 estados, 6 provincias, 2 culturas):
   - ninguna provincia de Victoria II cruza una provincia de FMG ni la costura;
   - los estados de FMG pasan a ser países y las provincias de FMG, estados;
   - la y se voltea;
   - un JSON de 60 000 celdas se lee en ≤ 3 s.
5. Con «Quitar los TAG existentes», la auditoría lista las citas de TAG en `events`, `decisions`, `common/{cultures,rebel_types,cb_types}.txt`, `news` e `history/*`. El SimpleFix de `union`/`primary` funciona en el minijuego.
6. Sobre vanilla:
   - un continente en una caja crea ids desde `max_provinces`;
   - **0 px de tierra existente cambian**;
   - los mares tocados conservan su id y regeneran su posición;
   - `forge_overlay_sea_shrunk` salta por debajo del 50 %;
   - dividir y pintar provincias crean todas sus dependencias;
   - `check_map` no empeora la línea base.
7. `THIRD_PARTY_NOTICES.md` cubre las bases de nombres. `test_no_install_content.py` no encuentra en el repositorio ninguna línea de más de 20 caracteres ni ningún archivo copiado de la instalación, con `data/name_bases.py` en lista blanca.
8. Capturas ES/EN, verificación adversarial y ampliación de la lista de comprobación en el juego: el país generado es jugable en 1836, sus banderas aparecen y la cultura nueva usa los gráficos de su grupo.

### Iteración 10 — Pulido, rendimiento, exportación y empaquetado

**Objetivo.** Dejar el Studio listo para el uso diario: rápido, exportable a un zip limpio, empaquetado para Windows y Linux y con una guía de usuario de los flujos principales.

**Entregables.**

- `core/export.py`: zip del mod sin `.vic2studio/`, `*.bak` ni temporales. Los errores bloquean la exportación (nunca el guardado). Limpieza opcional de las copias idénticas a vanilla.
- Perfilado y cachés en el índice y el mapa (con ProcessPoolExecutor si hace falta).
- Actualización de `packaging/` (PyInstaller e Inno Setup).
- Recorrido de bienvenida, revisión de ES/EN y accesibilidad con teclado.
- `docs/usuario/*.md` con los 5 flujos principales; `ARCHITECTURE.md` y `README.md` actualizados.
- `docs/usuario/comprobacion_en_juego.md`: la lista única de comprobación en el juego (§19.5) con todas las reglas [verificar en juego] acumuladas desde la iteración 2, incluidas las 28 del taller de mapas (§19.7). Las respuestas del usuario fijan el valor por defecto de cada opción.

**Reparto entre los 2 agentes.** Agente A: `core/export.py`, `tools/bench_*.py`, optimizaciones en `core/index/**` y `core/map/**`, `packaging/**`, `tests/test_export.py` y las pruebas de rendimiento. Agente B: pulido de `ui/**` (salvo `ui/map/**`, que solo se toca si A lo pide), `ui/dialogs/export.py`, `i18n/**`, `docs/usuario/**`, `README.md`, `ARCHITECTURE.md` y las capturas.

**Criterios de aceptación.**

1. Arranque con el índice en caché en ≤ 3 s; toda tarea larga se puede cancelar.
2. Índice en caliente en menos de 1 s y en frío en menos de 6 s; menos de 600 MB de memoria con el mapa de vanilla abierto.
3. Los ejecutables arrancan en Windows 10 y en Linux limpios.
4. El zip exportado no contiene `.vic2studio/`, `*.bak` ni temporales, y el usuario confirma que el mod carga en el juego.
5. Sin claves i18n ausentes y sin textos cortados con pseudolocalización a 1100×700.
6. La guía de usuario cubre los 5 flujos: crear un país, repartir provincias, montar una guerra de inicio, escribir un evento y crear un mapa nuevo.
7. Todas las pruebas en verde con y sin corpus; capturas finales ES/EN de las 7 salas.

---

## 23. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Semántica del motor que los archivos no demuestran: alcance de `replace_path` en subcarpetas, si se suman los bloques de POP repetidos, qué carpeta de POP usa cada bookmark, si se cargan todos los `.gfx`, qué copia de una historia duplicada gana y si el juego ignora `.vic2studio/` y `*.bak` (los riesgos del taller de mapas, incluidos los tamaños distintos de 5616×2160, van al final de esta tabla) | Opciones explícitas marcadas [verificar en juego], avisos en vez de suposiciones, pruebas que cubren las dos variantes y la lista de comprobación del usuario. |
| Escribir en el juego base (el mod vive dentro de `<juego>/mod`) | `WriteGuard` por realpath, el diario como única vía de escritura dentro del mod y `test_arch_writes`. |
| Guardado interrumpido que deja el mod incoherente (p. ej. `countries.txt` con el TAG pero sin historia) | Diario en dos fases con temporales en la misma carpeta, `.bak` como reversión, reintentos ante `PermissionError` y recuperación idempotente probada con fallos inyectados y `os._exit`. |
| Deshacer inexacto o referencias obsoletas tras deshacer | Instantáneas que se reparsean (exactas por la ida y vuelta byte a byte); la interfaz solo guarda `RecordRef` y re-enlaza al cambiar `version`; prueba de propiedad. |
| Fallo latente del lexer con saltos solo CR | Arreglo y regresión antes de cualquier edición. Hecho en la iteración 1, con las pruebas `test_clausewitz_parser.LineBreakTests.test_cr_only_files` y `test_encoding.EncodingTests.test_cr_only_newlines`; la iteración 2 solo comprueba que siguen pasando. |
| TAG detrás de `dynamic_tags`, copias mal colocadas que duplican ids, `text.csv` copiado entero | `Registry(before=…)`, tabla `LOAD_RULES` (copia a la misma ruta y mayúscula), `00_<P>_overrides.csv` y `test_placement`. |
| Orientación del mapa (sur arriba) y coordenadas de `positions.txt` y de la cámara | Ráster en coordenadas del juego, volteo solo en la vista, una única función de conversión y fixture asimétrico. |
| Romper las invariantes del mapa al editar regiones o crear provincias | Ediciones compuestas que mantienen la invariante tras cada paso, `PairedKeys` para `climate.txt` y prueba de propiedad. |
| Ruido de validación por los fallos de vanilla (13 partidos, 50 `civilized`, 27 colores, 1396/1397, 11108, `HAI_oob`, `annex`) | Línea base por huella calculada sobre la capa del juego y heredados ocultos por defecto. |
| Pérdida de datos del usuario por herramientas que reescriben archivos (el `text.csv` degradado de VSM es un caso real) | El Studio nunca reescribe lo que no edita; códecs sin pérdidas; `loc_copy_degraded` con arreglo; `originals/` antes de la primera escritura. |
| Archivos con errores de sintaxis (las 2 decisiones del usuario) | Solo lectura estructural, editor de texto con diagnósticos y arreglo rápido de la `}`. |
| Rendimiento y memoria (todos los CST de vanilla: +357 MB; vanilla se parsea en unos 3 s) | Índice compacto en caché por huella, CST bajo demanda con LRU, `gc.freeze` en la pasada en frío, `ProvinceFacts` en numpy, repintado por caja y tareas de fondo cancelables. |
| Catálogo de guion incompleto (vocabulario abierto) | Nodos crudos sin pérdidas, herramienta de censo y criterio de cobertura ≥ 95 % de los usos. |
| Copia al mod de archivos grandes (`provinces.bmp` de 36 MB, `cultures.txt`) | Aviso antes de la primera edición, diff en «Cambios pendientes»; la localización usa sobrescrituras. |
| Nombres inválidos en Windows creados desde Linux (`CON.tga`, `<>:"|?*`, rutas largas) y colisiones de mayúsculas | `windows_name_problems`, `path_too_long` y `case_collision` en `prepare()` y en la validación. |
| Cambios externos (Notepad++, Git) o dos instancias a la vez | Huellas base, comprobación al recuperar el foco y antes de confirmar, diálogo de conflicto y bloqueo con caducidad. |
| Conflictos entre los 2 agentes | Commit de contrato, archivos disjuntos con dueño único, registro por descubrimiento, i18n por fragmentos e iconos por sala. |
| Copyright de Paradox en fixtures, catálogos o capturas | Fixtures generados por código, catálogos con solo nombres y tipos, arte leído en tiempo de ejecución, `--no-game-art` en las capturas del repositorio y pruebas que lo vigilan. |
| Pillow `>=10` no garantiza escribir DXT | Escritor DDS propio sin comprimir (la mayoría de los DDS de vanilla lo son) y codificador DXT3 propio en numpy para `colormap_no_shadow.dds` (§18.5). |
| La interfaz abruma al modder (7 salas, unas 30 secciones) | Inicio por flujos, Ctrl+K, contadores en el índice, modo sencillo, «basar en…», asistentes con plan de cambios y revisión de capturas en cada iteración. |
| El mod de destino ya tiene archivos bajo las carpetas reemplazadas: `replace_path` no los oculta (VSM: 2 705 historias, 358 POPs, 265 OOB) | Acción T (papelera) en el plan para cada uno, clase A; regla `replace_path_mod_files_remain` (error); destino «Mod nuevo» recomendado. Prueba con un mod que es copia completa del minijuego. |
| «Solo mapa» sin dueños no se puede jugar, y reemplazar `history/units` deja `oob` colgantes (345 citas) | Opción «Dueños» con «Repartir entre TAG existentes» por defecto; `forge_no_owned_provinces` con confirmación; un OOB vacío por cada ruta citada; `history/diplomacy` y `history/wars` reemplazadas por defecto. |
| Provincias que `fix` crea o retira en el render final quedan sin estado, dueño o POPs | Mundo calculado sobre provincias provisionales antes del ráster y paso `reconcile`; prueba de propiedad tras el render final (medido: 0 provincias sin estado, continente, clima ni cultura). |
| Resultados distintos según la CPU (ufuncs SVML de numpy) | Resultados de la etapa de celdas guardados en `cells.npz`; sin ufuncs trascendentes en las decisiones; `forge_env_changed`; prueba con `NPY_DISABLE_CPU_FEATURES` (p7: hashes idénticos; p1 difería). |
| El motor trata mal una provincia partida por la costura x = 0/W−1 | La costura es frontera obligatoria de provincias y estados (0 provincias que la crucen, como vanilla) y se conserva la vecindad a través de ella; `forge_seam_province` en las importaciones. |
| Teselas de relleno (52–59) o índices de `terrain.bmp` que el juego no usa | Índices aprendidos de la instalación (≥ 0,5 % de su categoría); `terrain_index_placeholder`; propiedad «índice mayoritario ∈ categoría mayoritaria» (0 fallos medidos). |
| Ríos sin marcas de nacimiento y confluencia, o con uniones en diagonal | Trazado por tramos con 0 y 1, 4-conexo entre extremos enteros y limpieza de aislados; anchos y cuotas de la instalación. Medido: 0 diagonales, 586–604 confluencias. Pruebas también a 5616×2160. |
| Puntos de `positions.txt` superpuestos (fuerte, fábrica y unidades en el mismo píxel) | Dirección unitaria × min(d, r) con 8 direcciones. Criterio: < 5 % a menos de 2 px de `unit` y medianas en [5, 16] px (medido 0,8–1,5 % y 5,7–10 px). |
| Generar en el proceso de la aplicación bloquea la interfaz (hasta 874 ms) y suma unos 600 MiB | Proceso trabajador persistente (spawn): bloqueo ≤ 42,9 ms y la interfaz en 33,5 MiB. Criterio «bloqueo ≤ 100 ms» en `bench_mapforge`. |
| Las ediciones se pierden al cambiar parámetros globales (la rejilla dependía de f_tierra y L) | `LatticeSpec` fija desde la pantalla 1; trazos de pincel en coordenadas normalizadas; cambiar la densidad es una acción explícita con aviso. |
| El motor lee mal un CSV con una línea de comentario delante de la cabecera | Sin comentarios en `definition.csv` ni en la localización; en `adjacencies.csv`, la cabecera de vanilla en la línea 1. Prueba de la línea 1. |
| Claves de localización `PROV`/estado duplicadas en otros CSV del mod | `forge_loc_shadowed` con el SimpleFix «Quitar esas claves de los otros CSV»; orden de carga [verificar en juego]. |
| Nombres de archivo con acentos ilegibles en Windows con otra página de códigos | Transliteración a ASCII en las rutas (el id es lo que cuenta, H9); acentos solo en la localización. |
| Los tiempos medidos con numpy 2.5 no se cumplen con los mínimos declarados (numpy 1.24, Pillow 10) | `bench_mapforge` en CI con las versiones mínimas; si falla, se sube el mínimo a numpy ≥ 2.0 (decisión de la iteración 9a). |
| El motor rechaza o dibuja mal un mapa de tamaño distinto de 5616×2160 | 5616×2160 por defecto; los demás tamaños en múltiplos de 24 con `forge_size`; texturas proporcionales con las cabeceras de vanilla; prueba con 2808×1080 en la iteración 10. |
| Regla del motor desconocida para el terreno de una provincia (33 casos distintos en vanilla) | Índice por (estado, categoría): las dos reglas coinciden por construcción (medido); `terrain =` solo en las anulaciones. |
| Exportar unos 3 150 archivos (88 MB) más la papelera es lento en Windows o se interrumpe | Una transacción con diario y recuperación (§6.5) que incluye los movimientos; reintentos ante `PermissionError`; las instantáneas grandes de deshacer van a disco (`before_path`). Medido en Linux: 2,1–3,0 s de fsync y 0,05 s para mover 3 337 archivos. |
| «Sobre vanilla» altera provincias existentes | Arreglo de fragmentos limitado a las ids nuevas y al mar de la caja, y prueba «0 px de tierra existente cambian». |
| Licencias: código, plantillas y nombres de FMG; datos de Paradox | `THIRD_PARTY_NOTICES.md` y cabecera por módulo; sin SVG ni PNG de FMG; perfil de la instalación solo en `<cache_dir>`; prueba de contenido de la instalación con `name_bases.py` en lista blanca (las bases de FMG comparten 245 topónimos con vanilla). |
| Un mundo nuevo deja huérfanas referencias de TAG fuera de `events`/`decisions` (`cultures.txt`, `rebel_types`, `cb_types`, `news`) | TAG existentes conservados sin tierra por defecto; con «Quitar», auditoría por rol TAG en todo el índice y SimpleFix de `union`/`primary`. |
| El formato de exportación de FMG cambia | Solo JSON Full/PackCells con lector tolerante (`fmg_version_unknown`) y fixture sintético por versión. |
| El alcance del taller no cabe en una iteración | 9a (mapa, importación, Solo mapa jugable y trabajador) y 9b (Mundo, FMG, banderas y Sobre vanilla), con contratos propios. |

---

## 24. Decisiones del usuario (26-10-2026)

Respuestas del usuario a las preguntas abiertas del diseño. Mandan sobre cualquier otra parte de este documento.

| # | Pregunta | Decisión | Dónde se aplica |
|---|---|---|---|
| 1 | Columnas de idioma de los CSV | Inglés y español rellenos, como hace el usuario; opción `copy_en_to` para copiar el inglés a francés y alemán | §8 (`settings.languages`) |
| 2 | Carpeta `<mod>/.vic2studio/` | Sí, dentro del mod; la exportación la excluye | §5.4, D16 |
| 3 | `.bak` | Se mantienen junto a cada archivo | D4 |
| 4 | Copias idénticas a vanilla y filas con «?» en `text.csv` | Lo decide el Studio: se señalan (`mod_shadow_identical` como info, `loc_copy_degraded` como aviso) y se ofrecen como SimpleFix con vista previa y confirmación, nunca automáticamente. «Recuperar las filas de vanilla» solo restaura las filas degradadas y respeta las editadas de verdad. La limpieza de copias idénticas manda los archivos a la papelera y nunca toca carpetas con `replace_path` | §11, §11.1, iteración 3 |
| 5 | Arreglos de un clic | Sí: un **SimpleFix** por problema más un **explicador de conflicto** | §11.1, §13.9, iteración 3 |
| 6 | Comprobación en el juego | Una sola vez, al final del proyecto | §19.5, iteración 10 |
| 7 | Rango de ids de eventos | El que se considere conveniente: primer bloque libre de 10 000 ids desde 200 000 000, configurable | D15, §6.4 |
| 8 | Orden del plan | Mapa → países → eventos (se mantiene) | §22 |
| 9 | Mapa nuevo | Una suite que genera el mapa y sus recursos de forma procedural, al estilo de Azgaar's Fantasy Map Generator, y la opción de importar recursos de mapa para quien sepa trabajar con bitmaps | §14.15, §18, iteraciones 9a y 9b |
| 10 | Alcance de la suite de interfaces | La mejor opción posible: modificar las ventanas existentes, sprites e imágenes nuevos y «Duplicar como variante»; sin ventanas nuevas, porque el juego no las abriría | §17.4 |
| 11 | Versión del juego | Solo Heart of Darkness 3.04: los esquemas no distinguen la versión base ni AHD | §10.2, §10.3 |
