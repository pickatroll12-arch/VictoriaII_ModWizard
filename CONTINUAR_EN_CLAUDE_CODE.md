# Traspaso para Claude Code: cómo continuar

Este documento permite retomar Victoria II Mod Studio en una sesión nueva de Claude Code (en la nube o en local)
sin el contexto de las anteriores. Dice en qué estado está el proyecto, qué se decidió, qué hay implementado, cómo
preparar el entorno y qué hacer después, en orden.

> Léelo entero antes de tocar código. Después, en este orden:
> 1. `docs/diseno/wizard.md`, el diseño del objetivo ampliado (iteraciones 2 a 10). Empieza por §0 (el diseño en
>    una página), §20 (trabajo con 2 agentes), §22 (plan de iteraciones) y §24 (decisiones del usuario, que mandan
>    sobre todo lo demás).
> 2. `ARCHITECTURE.md`: la arquitectura del código (al día con la iteración 3 integrada).
> 3. `README.md`: qué funciona hoy y cómo ejecutar, probar, capturar y usar las CLI.
> 4. `docs/requisitos/prompt_maestro_creador_de_mods_victoria_ii.md`: los requisitos originales del usuario.

## Cómo arrancar la sesión

Un mensaje inicial que funciona:

```text
Lee CONTINUAR_EN_CLAUDE_CODE.md entero y continúa desde el primer paso sin hacer de §5. Respóndeme en español.
```

Para trabajo grande el usuario usaba *ultracode* (workflows con varios agentes y verificación adversarial): da
más garantías, pero gasta bastantes más créditos. Sin él, trabaja igual por pasos: reproduce cada fallo antes de
arreglarlo, deja una prueba de regresión que falle sin el arreglo y pasa la batería completa antes de cada commit.

---

## 0. Estado actual (28-10-2026)

- **Rama.** `claude/keen-fermi-nw8itc`. La iteración 3 entró en `main` con el PR #10, y la alfa 0.1.0 (con
  GitHub Actions) y la carpeta de handoff `docs/handoff/opencode/`, con el PR #11. Después de eso, esta rama
  integra dos ramas hechas por agentes de OpenCode y revisadas por Claude:
  - `opencode/editor-texto` (DeepSeek-V4.1-Flash): el **editor de texto** de Proyecto › Archivos (encargo
    `ENCARGO_EDITOR`, informe `docs/handoff/opencode/INFORME_EDITOR.md`). Dos rondas de revisión: la primera
    encontró una congelación de 144 s con `map/positions.txt`, una línea perdida tras un `\r` suelto y una
    regresión de disposición; las tres se corrigieron con su prueba.
  - `opencode/it4-motor` (DeepSeek-V4-Pro): el **corte vertical del motor de esquemas** de la iteración 4
    (`ENCARGO_MOTOR.md`, informe `INFORME_MOTOR.md`). Se puntuó con comprobaciones ocultas selladas antes de ver
    el código, el corpus y mutantes: 80/100 en la primera entrega y 93/100 (más 9 de extra) tras una corrección.
    Al integrarlo, Claude arregló las posiciones del CST tras `duplicate`/`create` (`Entities._reread`) y añadió
    la prueba del comentario de línea al cambiar un campo existente.
- **Hecho hasta el 27-10-2026**, ya en `main` (en orden; los mensajes de commit traen el detalle):
  - Los 6 pasos que quedaban de la iteración 1: segunda revisión adversarial de la última ronda de la interfaz
    (19 hallazgos confirmados y corregidos en `9040839`, más el grupo de compatibilidad en `563a709`), aviso al
    arrancar con PySide6 ≥ 6.12 en Python 3.10/3.11 (`093f8b3`), hoja de ruta con la numeración de wizard.md §22
    (`c18b8fd`), documentos al día (`5ba9cc0`), archivos de país sintéticos en la muestra (`7300a2f`, decisión del
    usuario) y capturas de T5 en ES y EN (`3230442`, en `docs/capturas/`).
  - **Iteración 2 (cimientos)**: contrato (`4f5b46d`), implementación con 2 agentes en paralelo (A: núcleo; B:
    descriptor, `Session` y armazón de 7 salas), integración (`97f0386`, `f3ff809`, `d3ed5de`) y prueba de punta a
    punta de la interfaz contra el `Project` real (`59e8847`), que destapó cinco fallos de integración, todos
    corregidos con prueba de regresión y mutación (§3, «Iteración 2»).
  - La batería entera pasa por primera vez con **PySide6 6.5.0**, el mínimo declarado (`563a709`).
  - **Revisión adversarial de la iteración 2, primera ronda** (criterio 11). Se hizo con
    `docs/handoff/workflow_iteracion2_revision.js` sobre `59e8847`: 5 componentes, un revisor y un verificador
    por componente.
    - Salieron 53 hallazgos confirmados con reproducción: 4 altos, 18 medios y 31 bajos.
    - Todos están corregidos en el commit «Correcciones de la revisión adversarial de la iteración 2», cada
      uno con su prueba de regresión.
    - Las pruebas están en `tests/test_review_*.py`: 12 archivos y 86 pruebas.
    - 24 mutaciones, todas detectadas.
    - El detalle está en ARCHITECTURE.md §6.1.
- **Iteración 3 (índice, validación, textos y Ctrl+K): hecha.** §3 («Iteración 3») y ARCHITECTURE.md §6.1 traen
  el detalle:
  - contrato (`914e5ed`), agente A con el núcleo (`7f8e814`) y agente B con `LocSync`, `Session` y la interfaz
    (`c577135`);
  - integración contra el núcleo real con la prueba de punta a punta de la ventana (`61589b1`, `9e38e45`,
    `e7cc27f`), que destapó cinco fallos de integración;
  - revisión adversarial en tres partes (escritura, núcleo e interfaz) y sus correcciones: `4eb166d`, `f148061`,
    `4c1df81`, `c3b1410` y `6d568c7`, todas con prueba de regresión y mutantes;
  - capturas 21 a 26 en `docs/capturas/`.

  Los 8 criterios de wizard.md §22 se cumplen, los del corpus con los archivos reales del usuario.
- **Pruebas** (28-10-2026, con la iteración 4): 1803 en 116 archivos.
  - Con el corpus real del usuario (release `recursos-v1`, descomprimido fuera del repositorio según §4, y copias
    de VSM y de la plantilla: nunca se abren las reales) pasan todas con Python 3.13.17 + PySide6 6.12.0. Solo se
    omite la clase base del arnés de esquemas, y no queda ningún `.vic2studio` en el corpus real.
  - Sin corpus pasan con 40 omitidas (39 de corpus y la clase base) con Python 3.10.20 + PySide6 6.11.3.
  - Las 1494 de la iteración 3 pasaron además con Python 3.10.20 + PySide6 6.5.0, Pillow 10.0 y numpy 1.24 (sin
    `XDG_RUNTIME_DIR`); esa combinación no se ha repetido con las pruebas nuevas.
- **Iteración 4: hecha e integrada** (rama `opencode/it4-claude`, Claude Opus 5.5 en OpenCode, encargo
  `ENCARGO_IT4.md`; el PR #12 llevó antes a `main` el editor de texto y el corte del motor). Claude Code la puntuó
  con comprobaciones ocultas selladas antes de ver el código (41 de 44), 11 de 11 mutantes y el corpus: **93/100 a
  la primera**, sin fallos de producto. Al integrarla se actualizó una prueba de disposición desfasada (la franja de
  Guerra ya cabe en una línea en inglés), la hoja de ruta pasó a «iteración 5 en curso» y `doc --kind` dejó de
  empezar con una línea en blanco. El informe, con las decisiones 1–4, los criterios, los mutantes y la revisión,
  está en `docs/handoff/opencode/INFORME_IT4.md`.
- **Lo siguiente: la iteración 5, el editor de mapa** (§5.5).
- **Segunda tanda de Gemini (G4–G7): hecha por Claude.** La plataforma de Gemini se cayó y el usuario pidió
  asumirlas. Son piezas del núcleo para iteraciones futuras, en archivos nuevos:
  - G4 (`8c33ae6`): `core/tablecsv.py` y `core/map/definition.py`;
  - G5 (`e3bae3e`): el códec BMP, `core/map/bmp.py`;
  - G6 (`b412730` y `b973bb9`): DDS A8R8G8B8, `core/gfx/dds.py`;
  - G7 (`ac3df50`): banderas TGA, `core/gfx/flags.py`.

  El detalle (corpus y mutaciones) está en el estado de `docs/handoff/PARA_GEMINI.md`. Todas pasan en Python 3.13
  y 3.10 con Pillow 12.3, en 3.10 con Pillow 10.0 y PySide6 6.5, y en 3.10 con Pillow 10.3, con y sin corpus
  (`VIC2_GAME`).
  - **Hecho en la integración.** El visor de imágenes (`ui/viewers/image_viewer.py`) ya decodifica con
    `core/gfx/dds.read_dds` los DDS sin comprimir de 24 y 32 bits. Con Pillow 10.0–10.1, X8R8G8B8 se veía con
    los colores corridos. Lo que ese lector no admite sigue yendo a Pillow.

---

## 1. Qué es y qué pidió el usuario

- **Victoria II Mod Studio**: aplicación de escritorio (Windows y Linux) para crear y editar mods de Victoria II
  (motor Clausewitz) de forma 100 % visual, con estética de Victoria II e interfaz en español e inglés.
- El usuario habla **español**: respóndele siempre en español. Los documentos van en español, salvo el resumen en
  inglés del README. Prefiere respuestas ricas y detalladas.
- **Iteración 1** (sección «Instrucciones de Ejecución y Entrega» de los requisitos): propuesta de arquitectura y
  stack (`ARCHITECTURE.md`), estructura de directorios, motor de parseo Clausewitz `.txt` ⇄ JSON y CSV ⇄ JSON y
  ventana principal con estética Victoria II, selector ES/EN y navegación entre 5 módulos. Cerrada el 27-10-2026
  (§0); la navegación ya es la de 7 salas de la iteración 2.
- **Objetivo ampliado.** El Wizard debe cubrir 15 capacidades (wizard.md §14): generar el `.mod`; ver, crear y
  editar países, provincias, unidades terrestres, decisiones, eventos, guerras de inicio, casus belli, bookmarks,
  gobiernos nuevos, unidades navales, culturas y regiones; una suite de modificación de interfaces; y un taller
  de mapas nuevos que genera o importa un mapa con todos sus archivos dependientes. El plan las reparte en las
  iteraciones 2 a 10 (la 9 dividida en 9a y 9b).
- **Avance.** El 26-10-2026 se le dijo al usuario «alrededor de un 15 % del programa completo por esfuerzo». Con la
  iteración 2 integrada están los cimientos (VFS, proyecto transaccional, diario, deshacer, 7 salas) y la primera
  de las 15 capacidades (el `.mod`); faltan las iteraciones 3 a 10.

## 2. Decisiones tomadas (no las reabras sin motivo)

### De la iteración 1, vigentes

- **Stack: Python 3.10+ con PySide6 ≥ 6.5 (< 6.12 en Python 3.10 y 3.11), numpy ≥ 1.24 y Pillow ≥ 10.** Se empezó
  recomendando Tauri + Rust, pero el equipo del usuario no tenía toolchain de Rust ni webkit2gtk y sí PySide6 y
  numpy. La justificación, con medidas del mapa, está en `ARCHITECTURE.md` §1.
- **El núcleo (`vic2studio.core`) no depende de Qt**; la interfaz está en `vic2studio.ui`. Por eso los mensajes
  del núcleo van en tablas `MESSAGES` es/en de cada módulo: `vic2studio.i18n` importa QtCore.
- **Sin pérdidas.** El parser construye un árbol de sintaxis concreto con *trivia*: reescribir un archivo sin
  cambios da los mismos bytes, y editar un valor cambia solo ese texto. El CSV también hace ida y vuelta byte a
  byte. La codificación del juego es cp1252, con sus 5 bytes indefinidos conservados.
- **Escritura atómica con `.bak`** (`core/fileio.py`) y `FileChangedError` si el archivo cambió fuera de la
  aplicación. El juego base es de solo lectura: todo se escribe en la carpeta del mod.
- **Estética 100 % procedural** (QPainter y numpy): ninguna textura, fuente ni imagen del juego.
- **Los datos de Paradox nunca se suben al repositorio.** El corpus vive fuera. En los documentos tampoco se copian
  líneas de archivos del juego. Los archivos de país de `tests/fixtures/shago_mod_min` son sintéticos desde
  `7300a2f` (el usuario lo decidió: los originales compartían bloques con vanilla), y las capturas de
  `docs/capturas/` solo muestran la muestra (`3230442`).
- **Solo se usa Heart of Darkness 3.04** como versión de referencia (decisión 11 del usuario).
- **Convenciones.** Identificadores en inglés; docstrings y comentarios en español, concisos. Todo texto visible
  pasa por `tr()` con paridad ES/EN. Pruebas con `unittest`. Código compatible con Python 3.10 (sintaxis y
  biblioteca estándar: nada de `TestCase.enterContext`, `tomllib`, `ExceptionGroup`, etc.) y con la API de
  Qt 6.5.
- **Cancelación cooperativa** (`core/cancel.py`): las funciones largas aceptan `cancelled=`, una función sin
  argumentos que devuelve True cuando hay que parar, y lanzan `Cancelled`.
- **Preferencias** en INI (`src/vic2studio/settings.py`). En pruebas y capturas, `VIC2STUDIO_SETTINGS_DIR=<carpeta
  temporal>` evita tocar la configuración real.

### Del diseño del Wizard

wizard.md §1 resuelve en 19 decisiones (D1–D19) las contradicciones entre las tres propuestas de diseño: 7 salas
por flujos, sin capa `services/`, deshacer por instantáneas, copia desde vanilla al guardar, `.bak` más diario,
CST vivo solo en el hilo de la interfaz, rango de ids de eventos, etc.

### De la iteración 2, vigentes

- **Solo `core/fileio.py` escribe en crudo** (`tests/test_arch_writes.py`, regla AST, sin excepciones), y todo lo
  que se guarda en el mod pasa por `Session` → `Project` → diario (`core/project/journal.py`) y `WriteGuard`. El
  descriptor `.mod` vive fuera de la carpeta del mod: se nombra `DESCRIPTOR_REL` (`"@descriptor.mod"`); sin `.mod`,
  el sitio donde se creará es `<juego>/mod/<Carpeta>.mod`.
- **`Session` (`ui/session.py`) es el único puente con Qt.** Abre en segundo plano y cede el `Workspace` al hilo
  de la interfaz (`bind_to_current_thread`); «Descartar» cierra con `discard=True` (sin autoguardado); el
  autoguardado lo decide el núcleo (`autosave_due`, y `write_recovery` borra el de la sesión si ya no hay sucios).
- **Las pruebas de la ventana corren dos veces**: contra el `Project` falso (`tests/_fake_project.py`, rápido y
  con fallos a la carta, que imita la API del real) y contra el real (`tests/test_ui_real_project.py`). Si cambias
  la API del núcleo, cambia el falso a la vez.
- **Textos**: la interfaz, en `i18n/<idioma>.json` más fragmentos `i18n/<idioma>/<área>.json`; el núcleo, en
  `core/**/texts/*.<idioma>.json` (mensajes de guardado y etiquetas `undo.*` de los pasos que crea). `load_catalog`
  rechaza claves repetidas entre todos.
- **PySide6 6.5 o 6.6 piden numpy < 2** (ruedas de shiboken6 compiladas con NumPy 1.x): está en el README y en
  `requirements.txt`; no se sube el mínimo de PySide6 sin preguntar al usuario.

### Respuestas del usuario (wizard.md §24, 26-10-2026)

Mandan sobre cualquier otra parte del diseño. Dos más, del 28-10-2026, al cerrar la iteración 4:

- **`first_names` y `last_names` son obligatorios en una cultura** cuando el mod parte de vanilla (las 226 de
  vanilla los llevan); el esquema `culture` los marca así.
- **`defines.lua` sin códec propio** mientras no compense: un códec solo si es barato. Hoy `end_date` se edita con
  `core/lua_defines.py` y `Workspace.restore_bytes` (10 líneas, sin pérdidas y con deshacer), y un códec tocaría
  `DocKind`, el registro de códecs, las reglas de carga y `test_project_codecs`. Se revisa si otra iteración
  necesita editar más de `defines.lua`.

Las del 26-10-2026, en resumen:

1. Columnas de idioma de los CSV: inglés y español rellenos; opción `copy_en_to` para copiar el inglés al francés y
   al alemán.
2. La carpeta `<mod>/.vic2studio/` va dentro del mod; la exportación la excluye.
3. Se mantienen los `.bak` junto a cada archivo.
4. Las copias idénticas a vanilla y las filas con «?» de `text.csv` se señalan (`mod_shadow_identical`, info;
   `loc_copy_degraded`, aviso) y se ofrecen como arreglo con vista previa y confirmación, nunca automático. La
   limpieza manda a la papelera y nunca toca carpetas con `replace_path`.
5. Arreglos de un clic: un **SimpleFix** por problema y un **explicador de conflicto**.
6. La comprobación en el juego se hace una sola vez, al final del proyecto (iteración 10).
7. Ids de eventos: el primer bloque libre de 10 000 ids a partir de 200 000 000, configurable.
8. Orden del plan: mapa, después países, después eventos.
9. Mapa nuevo: una suite que lo genera de forma procedural al estilo de Azgaar's Fantasy Map Generator, más la
   importación de recursos para quien trabaja con bitmaps.
10. Suite de interfaces: modificar las ventanas existentes, sprites e imágenes nuevos y «Duplicar como variante»;
    sin ventanas nuevas, porque el juego no las abriría.
11. Solo Heart of Darkness 3.04: los esquemas no distinguen la versión base ni AHD.

## 3. Qué hay implementado

La ventana tiene 7 salas (Ctrl+1 a Ctrl+7): Proyecto, Mapa, Naciones, Guerra, Eventos, Interfaz y Textos. En
Proyecto funcionan Inicio, Descriptor .mod, Archivos, Validación y Cambios pendientes. En Textos funcionan Todos
los textos, Pendientes de traducir y Archivos CSV. Además están el panel Problemas y Ctrl+K. El resto de
secciones son tarjetas que dicen qué harán y en qué iteración llegan. Desde la iteración 2 la interfaz **sí escribe en el mod**, siempre a
través de `Session` y del diario: el descriptor `.mod` (crear y editar), «Nuevo mod» y, en general, cualquier
documento abierto en el `Workspace`. Lo de la iteración 1 sigue igual salvo lo que dice «Iteración 2» más abajo.
Los mensajes de los commits resumen cada ronda: `fadf29e` (núcleo), `899ecca` (parser), `606811e` (interfaz), los
dos de la última ronda de T4 y los de §0.

### Núcleo (`src/vic2studio/core`, sin Qt)

- **`encoding.py` y `fileio.py`.** Detección sin pérdidas de cp1252, UTF-8 con y sin BOM y UTF-16: LE con BOM
  (`utf-16`), BE con BOM (`utf-16-be-bom`, un codec propio que registra el módulo) y sin BOM (`utf-16-le`,
  `utf-16-be`, por los NUL alternos). `GAME_UNREADABLE` agrupa las cuatro UTF-16. `split_extra_boms` separa los BOM
  repetidos, `match_bom(data, encoding)` ajusta una codificación explícita al BOM real del archivo y
  `detect_newline` devuelve `"\r"` si el archivo solo usa CR. `fileio` lee con huella (`FileStamp`), escribe de
  forma atómica con `.bak`, lanza `FileChangedError` (mensaje ES/EN) si el archivo cambió desde que se leyó y da a
  los archivos nuevos los permisos por defecto.
- **`cancel.py`.** `Cancelled`, `raise_if_cancelled` y el tipo `CancelCheck`. Lo usan `tokenize`, `parse` y
  `parse_file`, `parse_csv`, `read_csv_file`, `LocalisationDB.from_dirs` y `check_mod`.
- **`clausewitz/`.**
  - Lexer por tandas de 8 192 caracteres y parser iterativo, sin límite de anidación y tolerante a errores.
    Consulta la cancelación cada 16 384 elementos. Las líneas cuentan el CR suelto como salto y los comentarios
    acaban en CR o LF.
  - Diagnósticos con línea, columna y mensaje ES/EN: `unclosed_block`, `unexpected_close_brace`, `missing_value`,
    `missing_key`, `unterminated_string`, `invalid_key`, `unexpected_operator`, `invalid_character`,
    `multiline_string`, `control_character`, `invisible_character`, `non_game_encoding`,
    `suspicious_close_brace` y, desde la última ronda, `unreadable_encoding` (error, UTF-16) y `stray_bom` (aviso,
    BOM UTF-8 delante de cp1252), en `diagnostics.ENCODING_CODES`. `parse_file` los da él mismo, así que la CLI,
    «Validar mod» y el visor los reciben del mismo sitio.
  - **Posiciones finales públicas** (última ronda): `lexer.end_position(token)`, `Entry.value_end` (línea y columna
    del último carácter del valor leído, o `None` si el código lo creó o cambió, o si la entrada no tiene posición
    propia) y `Block.close_position` (la `}` leída, o `None`). El índice de estructura del visor solo usa esta API.
  - **BOM repetidos**: `parse_file` los quita del texto y `Document.extra_boms` los cuenta. `to_source` no los
    incluye (igual que no incluye el BOM de la codificación), y `write_file` los repone solo si se guarda en la
    misma codificación y esta lleva BOM. Ojo: `csvloc` hace lo contrario en `to_source` (los incluye).
  - API de edición que conserva el formato: `set` (con `op=`), `append`, `insert_before`, `insert_after`,
    `insert_entry`, `move`, `remove` y `find`/`find_all` con filtro por valor, `remove_entry`, `clone`, `close`
    (añade la `}` que falta), `find_path`, `get_path`, `path_of`, `index_by_key` y `Block.from_pairs`. Los
    comentarios se editan con `comments`, `line_comment`, `open_comment` y `trailing_comments`;
    `Document.unclosed_blocks()` y `Document.check_text()` sirven para formularios.
  - Los tokens no se mutan: el serializer compara con el orden leído, así que mover, reordenar, quitar y deshacer
    dan el texto exacto. Deduce la sangría del archivo y despliega en varias líneas un bloque de una línea que
    pasaría de 80 caracteres o que recibe comentarios (sin reinicios del escritor desde la última ronda).
  - Los errores de la API son `EditError` (subclase de `ValueError`) y `EditTypeError`, con 40 códigos y mensaje
    ES/EN.
  - `write_file(verify=True)` relee el texto generado y no escribe si el árbol cambia, si queda una `}` tragada o
    si aparecen errores de sintaxis nuevos (`SourceMismatchError`, con la ruta de la entrada y la línea; con
    `near_errors=True` y un mensaje propio cuando la edición está junto a errores de sintaxis). Hace el `.bak`
    solo en el primer guardado de la sesión y admite `expected=` para detectar cambios externos.
  - JSON: `to_json`, `from_json`, `iter_json` (sin recursión), `simplify`, `walk` y `format_canonical`.
  - CLI: `python -m vic2studio.core.clausewitz check|tojson`. Recorre `CLAUSEWITZ_SUFFIXES` (una sola definición,
    en `parser.py`), `.map` incluido, y sale con 1 si algún archivo tiene un error, también UTF-16.
  - Con el corpus completo, la prueba recorre 12 054 archivos (27,4 MB) con ida y vuelta byte a byte; `parse_file`
    de todos tarda unos 9 s.
- **`csvloc/`.** Formato CSV del juego: `;`, 13 idiomas, marcador `x` en la columna 14 y campos extra tras ella.
  - Modelo editable (`LocalisationFile.set`, `add_row`, `add_rows`, `rename_key`, `remove_row`…) con
    `InvalidFieldError` y mensajes ES/EN.
  - BOM repetidos en `LocalisationFile.extra_boms`: la primera clave queda limpia y guardar en la misma
    codificación da los mismos bytes.
  - `lint` con 9 códigos: `missing_end_marker`, `too_few_columns`, `duplicate_key`, `empty_key`, `key_whitespace`,
    `semicolon_in_quotes`, `unencodable_character`, `non_game_encoding` y `header_row`.
  - `LocalisationDB` fusiona carpetas como el juego. `add_file` respeta la prioridad de carpetas, y `keys()` y
    `overrides()` siguen el orden de carga también después de `define()`.
  - CLI: `python -m vic2studio.core.csvloc check|tojson|fromjson`.
- **`modfile.py`.** Descriptor `.mod`: `read_descriptor`, `find_descriptor` y `write_descriptor`, que edita sin
  perder comentarios o genera uno nuevo en cp1252 con CRLF. Un valor con comillas o saltos de línea lanza
  `DescriptorFieldError`. Un `.mod` en UTF-16 se guarda en cp1252 y nunca se prefiere a uno legible
  (`ModDescriptor.game_readable`).
- **`modcheck.py`.** Validación de un mod completo: `check_mod` (con progreso y cancelación), `check_file`,
  `collect_files` (solo las 16 carpetas que lee el juego), `check_descriptor` e `is_mod_root`. Reenvía los
  diagnósticos del parser (también los de codificación, que ahora traen línea y columna 1:1 y sus argumentos en
  `issue.diagnostic.args`) y del lint, y añade `no_game_folders` (aviso), `read_error`, `folder_error`,
  `check_failed` y 7 códigos `descriptor_*`.

### Interfaz (`src/vic2studio/ui`) y resto

- **`i18n/`**: `Translator` con cambio de idioma en vivo; 670 claves de la interfaz (catálogo y fragmentos) más
  17 del núcleo, en paridad ES/EN, que las pruebas recorren también con una pseudo-localización para encontrar
  textos sin traducir.
- **`settings.py`**: preferencias en INI; `VIC2STUDIO_SETTINGS_DIR` las desvía.
- **`ui/tasks.py`**: tareas en segundo plano con `TaskRunner(parent, *, pool=...)`.
  - Grupos de hilos: `POOL_PREVIEW` (2 hilos), `POOL_IMAGES` (1), `POOL_VALIDATION` (1) y, desde la última ronda,
    `POOL_RELEASE` (1) para `release_in_background(value, dismantle)`, que suelta objetos grandes por trozos tras
    `RELEASE_DELAY` (0,1 s).
  - `cancel_all()` y `wait_for_tasks(timeout_ms=-1)`, compatible con Qt 6.5. `app.main` los llama al salir.
  - Mientras corre una tarea, el recolector cíclico está parado. Al terminar, si quedan más de 100 000 objetos
    nuevos, se congelan (`gc.freeze`) y los resultados entregados se vigilan con referencias débiles para
    descongelar cuando mueren. Por eso ningún resultado puede formar un ciclo
    (`test_results_of_the_application_tasks_die_by_reference_counting`). Desde la última ronda, `_Job` entrega en
    una lista que vacía quien recibe, así que el hilo de la tarea no retiene el resultado (arregla una prueba
    intermitente del recolector).
- **`ui/viewers/`**:
  - `clausewitz_viewer.py`: pestañas Estructura, Código, Diagnósticos y JSON. El índice plano en preorden
    (`StructureIndex`) y el documento del código se construyen en la tarea, y la Estructura es un modelo perezoso
    que entrega las raíces por lotes. «Expandir todo» está acotado a 5 000 filas. Al cambiar de archivo, el
    análisis viejo se desmonta en segundo plano (`dismantle_load`, trozos de `RELEASE_CHUNK` = 4 096): soltar
    5 MB cuesta 182–220 ms en 824 pasos con un hueco máximo de 23–25 ms. Un archivo UTF-16 sale en rojo
    («Ilegible para el juego») en la cabecera y en la pestaña Diagnósticos. Al reintentar un fallo de lectura, el
    fallo sigue a la vista hasta la respuesta o hasta `LOADING_DELAY_MS` (150 ms, en `viewers/common.py`).
  - `code_view.py`: el documento se prepara en el hilo de la tarea, el resaltado es perezoso y las marcas de
    diagnóstico solo se pintan en las líneas visibles. Su docstring explica por qué destruir un documento enorme
    sigue costando 159–349 ms en el hilo de la interfaz (§6).
  - `diagnostics.py`: una tabla común (`DiagnosticsView`) para el visor, el lint y la validación.
  - `image_viewer.py`: TGA, DDS, BMP, PNG, JPG y GIF con Pillow, en segundo plano; el reintento ya no parpadea.
  - `localisation_editor.py`: tabla de solo lectura con filtro rápido y lint.
  - `validation_panel.py`: «Validar mod» con progreso y cancelación.
  - `common.py`: `describe_os_error`, `file_stamp`, `ElidedLabel` (recorta primero la ruta y conserva la
    codificación) y `ViewerHeader`.
- **`ui/pages/`**:
  - Proyecto y Archivos: rutas del juego y del mod, explorador con filtro, ficha del archivo (con nombre de las
    codificaciones UTF-16 y salto de línea en los valores), vista previa y «Validar mod».
  - Localización: el CSV se lee en segundo plano y se puede cancelar.
  - Las secciones planificadas de las 7 salas son tarjetas «en desarrollo» con la iteración de wizard.md §22
    (`ui/pages/planned.py`), y la hoja de ruta de Inicio tiene los 10 hitos (`c18b8fd`).
- **`ui/widgets/navigation.py`**: los nombres de módulo se parten en dos líneas si no caben (antes se recortaban
  a 1100×700 en español).
- **`tools/screenshot.py`**: capturas sin pantalla, con `--open-file`, `--line`, `--search`, `--tab`, `--validate`,
  `--left-tab` y `--report` (opciones en el README); desde la iteración 2 también `--hall`, `--section`,
  `--dialog`, `--demo-game`, `--demo-changes` y `--fake-project`. Las de `docs/capturas/` son las de T5
  (`3230442`), sobre la muestra.

### Iteración 2 (cimientos)

- **`core/vfs/`**: `paths` (`VPath`, claves sin mayúsculas, `windows_name_problems`, `long_path_problem`,
  `DESCRIPTOR_REL`), `rules` (cómo carga el juego cada carpeta), `guard` (`WriteGuard`: solo el mod y su `.mod`,
  por `realpath`) y `vfs` (`VirtualFS`: capas juego, dependencias y mod, `replace_path`, `resolve`, `stack`,
  `list`, `mod_target`).
- **`core/project/`**: `model` (documentos, eventos, `ChangeSet`, `SaveReport`, `ProjectSettings`), `codecs`,
  `documents`, `undo` (instantáneas), `workspace` (transacciones con nombre, deshacer y rehacer, cambios
  externos, `changeset`, `save`, autoguardado), `journal` (guardado multiarchivo todo o nada, `.bak`,
  `originals/`, papelera, recuperación), `recovery`, `lock` (segunda instancia en solo lectura), `settings`
  (`.vic2studio/project.json`, que se deshace y se guarda como un documento más) y `project` (`Project.open`,
  `close(discard=)`, `restore_session`, `discard_session`).
- **`core/appdirs.py`** (carpetas de datos y caché fuera del mod; `VIC2STUDIO_DATA_DIR` y `VIC2STUDIO_CACHE_DIR`
  las desvían) y **`core/texts.py`** (textos del núcleo por idioma).
- **`core/modfile.py`**: `DescriptorSpec`, `render_descriptor` (oro: `tests/fixtures/shago_mod_min/VSM.mod`),
  `descriptor_problems`, `create_mod_skeleton` (todo o nada con el diario), `sanitize_folder` y `taken_folders`.
- **Interfaz**: `ui/session.py`; `ui/shell/` (salas, barra de secciones, panel de cambios pendientes, historial);
  `ui/halls/` (registro por descubrimiento de las 7 salas); `ui/halls/project/` (Inicio, Descriptor .mod,
  Cambios pendientes); `ui/dialogs/` (revisión antes de guardar —D13: solo si se copia del juego, se manda algo a
  la papelera o hay problemas—, conflicto con «Conservar mis cambios», «Recargar del disco» y «Comparar»,
  recuperación y «Nuevo mod»); `ui/widgets/layer_badge.py` (capa de cada archivo en el explorador). Guardar con
  contador (Ctrl+S), deshacer y rehacer (Ctrl+Z, Ctrl+Y, Ctrl+Mayús+Z), título con `*`, pregunta al cerrar o al
  cambiar de mod con cambios.
- **Fallos que destapó la prueba de punta a punta** (`59e8847`), ya corregidos: «Descartar» dejaba autoguardado y
  se ofrecía al reabrir; deshacerlo todo no borraba el autoguardado anterior; las etiquetas `undo.*` del núcleo
  no tenían texto; sin `.mod` no se podía crear el descriptor (`FileNotFoundError` al guardar); el formulario
  aceptaba carpetas como «CON .x» que el guardado rechaza.
- **Revisión adversarial** (primera ronda): 53 hallazgos corregidos. Los cuatro altos:
  - `<juego>/mod` se aceptaba como carpeta del mod. Ahora la rechaza `mod_root_problem`, y `VirtualFS` lanza
    `InvalidModRootError`.
  - Un diario pendiente se aplicaba a medias al reabrir. Ahora la recuperación no toca nada si no puede
    llevarlo entero a un lado, y no se guarda encima: `save_journal_pending`.
  - Ctrl+S o cerrar perdían lo tecleado en el descriptor. Ahora lo confirma `MainWindow.commit_edits`.
  - Restaurar un autoguardado y sufrir otro corte lo perdía. Ahora `restore_session` escribe el autoguardado
    nuevo antes de borrar el huérfano.

  La lista completa está en ARCHITECTURE.md §6.1, y cada regresión en su `tests/test_review_*.py`.
- **Fallos de Qt 6.5** (`563a709`), ya corregidos: etiquetas que se mostraban un instante como ventana suelta
  (`setVisible` antes de tener padre; prueba `StrayWindowTests`), botón «Resolver» que `QDialogButtonBox` volvía a
  mostrar, flecha de orden que recortaba los títulos de la tabla de diagnósticos.

### Iteración 3 (índice, validación, textos y Ctrl+K)

El detalle de diseño está en ARCHITECTURE.md §2.3, §2.6, §2.7 y §8.1.1, y los criterios y la revisión en §6.1.

- **`core/index/`**: `SymbolIndex` de la vista efectiva, con 9 familias de extractores (`@extractor`, por
  descubrimiento) y caché `FactsCache` (JSON-lines con gzip por capa en `<cache_dir>/index/`). Es incremental
  (`apply`) y admite varias dependencias. La búsqueda va por id y por nombre localizado, sin acentos (`fold`), y
  `short_name` da el id que ve el usuario. Vanilla se indexa en unos 2,3 s en frío y en 0,3 s desde la caché.
- **`core/validate/`**: `ValidationContext` (inmutable, con lo sin guardar, `None` si está borrado), 9 familias y
  91 códigos (`@rule`), `Validator` con `check_failed`, línea base del juego y las dependencias a la fecha de
  trabajo (`baseline_for`, caché en `<cache_dir>/baseline/`), 5 arreglos con plan = aplicación (`FixError`, 12
  motivos con texto ES/EN), explicador con título y frase propios por código, textos en `texts/issues.{es,en}.json`.
- **`core/rules/`** (`GameRules`, `ids`, `names`, `colors`) y **`core/lua_defines.py`** (editor de `defines.lua`
  sin pérdidas).
- **`core/locsync.py`**: `LocSync`, la política de dónde se escribe cada texto. Si gana el mod, la fila se edita
  en su sitio; si gana el juego, va a `00_<P>_overrides.csv`; las claves nuevas van a `00_<P>_<área>.csv`. Tiene
  vista efectiva e indicadores, y lee en segundo plano.
- **`core/csvloc/degraded.py`**: la única definición de fila degradada (H15), que comparten la regla
  `loc_copy_degraded` y el filtro de Textos.
- **Interfaz**:
  - `Session` construye el índice, lee los textos y valida en segundo plano.
  - Proyecto › Validación: tabla con heredados ocultos, [Arreglar ▾] con `FixPlanDialog`, [¿Por qué?] con el
    explicador en segundo plano, informe desfasado y «Reintentar la línea base».
  - El panel Problemas.
  - Textos › Todos los textos y Pendientes de traducir, editables, con filtros y «Añadir clave».
  - Ctrl+K con la ficha en su línea.
  - `ui/widgets/busy.py`, el cursor de espera de lo síncrono.
- **Herramientas**: `tools/screenshot.py --check --explain N --palette TEXTO --texts-search --texts-filter
  --demo-index`. Cada captura comprueba el explicador y guarda en el informe lo que se vería mal
  (`checks.explainer_shots`).
- **Fallos que destapó la prueba de punta a punta** (`9e38e45`, `e7cc27f`), ya corregidos:
  - lo borrado sin guardar no llegaba al índice ni al validador;
  - un borrado hacía que el archivo del juego pareciera ausente;
  - F7 tras Ctrl+Z validaba con el índice viejo;
  - «Validando…» se quedaba en la barra de estado;
  - los partidos salían en Ctrl+K con la ruta del archivo.
- **Revisión adversarial** en tres partes: escritura, núcleo (16 hallazgos) e interfaz (21). Todo está corregido
  con prueba de regresión y mutantes. El resumen está en ARCHITECTURE.md §6.1. Las pruebas son
  `tests/test_index_review_it3.py`, `test_validate_review_it3.py` y `test_ui_review_it3.py`, además de las
  ampliaciones de los módulos de cada pieza.

### Pruebas

1803 pruebas en 116 archivos `tests/test_*.py`. Las del motor de esquemas son `test_schema_*` (con el arnés
`tests/schema_harness.py`), y las del editor de texto, `test_textsplice` y `test_ui_script_editor`. Las de la iteración 3 son `test_index_*`, `test_validate_*`,
`test_rules_*`, `test_lua_defines`, `test_locsync`, `test_loc_effective`, `test_ui_loc_edit`, `test_ui_validation`,
`test_ui_palette`, `test_contract_it3`, `test_e2e_it3` y los tres `test_*_review_it3`; las de G4–G7,
`test_tablecsv`, `test_map_*` y `test_gfx_*`. Sin corpus se omiten 54, las que necesitan vanilla, VSM o la
plantilla reales. Antes de la iteración 3 eran 1089 pruebas en 70 archivos (las de la iteración 1 más `test_vfs_*`, `test_project_*`,
`test_journal_*`, `test_undo_*`, `test_workspace_*`, `test_recovery_autosave`, `test_lock`, `test_arch_writes`,
`test_texts`, `test_appdirs`, `test_modfile_write`, `test_ui_shell`, `test_ui_session`, `test_ui_descriptor`,
`test_ui_new_mod`, `test_ui_roadmap`, `test_ui_real_project`, de Gemini `test_no_paradox_data`,
`test_cr_line_counts` y `test_pickle_errors`, y los doce `test_review_*` de la revisión adversarial…). Las que
lanzan un proceso hijo (cortes con `os._exit`) calculan `tests/` desde `__file__`, así que funcionan con
`discover -s tests` desde la raíz. Sin corpus se omiten 5: valores pegados al token siguiente, el
`.csv.bak`, la carpeta vanilla, las líneas de vanilla en el repositorio y el criterio 3 de la iteración 2 sobre
vanilla + VSM.
`tests/_qt.py` aísla preferencias, datos y caché en carpetas temporales y crea un `XDG_RUNTIME_DIR` si falta.

Antes de la iteración 2 eran 593 pruebas en 22 archivos `tests/test_*.py` (parser `test_clausewitz_*`, CSV `test_csvloc_*`, `test_encoding`,
`test_modcheck`, `test_i18n`, `test_tasks` y la interfaz `test_ui_*`). Sin corpus se omiten 3: la de valores
pegados al token siguiente, la del `.csv.bak` y la que necesita la carpeta vanilla. Sin corpus, las pruebas usan
la muestra `tests/fixtures/shago_mod_min` y una plantilla sintética (`tests/_corpus.py`). Los tearDown de interfaz
comprueban que no queda ninguna `MainWindow` viva. Hay pruebas de latido que miden el mayor hueco del hilo de la
interfaz: en una máquina cargada pueden fallar; repítelas solas antes de darlas por rotas.

## 4. Entorno y corpus

```bash
python3 -m pip install -r requirements.txt
# Bibliotecas del sistema que necesita Qt offscreen en un contenedor Debian o Ubuntu:
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 fonts-dejavu

QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" python3 -m unittest discover -s tests
```

### Corpus

El corpus real no está en el repositorio: son archivos del juego. Sin él, la batería pasa entera con 3 pruebas
omitidas, que basta para casi todo el trabajo. Para las pruebas de corpus hacen falta tres carpetas: el juego
base, el mod plantilla del usuario y su Shago Mod.

- **En el equipo del usuario** (Claude Code en local): apunta a la instalación del juego y a los mods.
- **En la nube**: en el proyecto anterior el usuario los subió como zips (`Plantilla Mod.zip`,
  `VictoriaShagoMod_for testing`, un zip sin extensión, y `VICII_SRC_FOR_MODDING.zip`, los datos del juego sin
  ejecutables). Una sesión nueva no los tiene: si los necesitas, pídeselos al usuario y descomprímelos **fuera del
  repositorio**:

```bash
mkdir -p /home/user/corpus && cd /home/user/corpus
unzip -q "<ruta>/Plantilla Mod.zip" -d "Plantilla Mod"
unzip -q "<ruta>/VictoriaShagoMod_for testing" -d ShagoMod
unzip -q <ruta>/VICII_SRC_FOR_MODDING.zip -d . -x 'VICII_SRC_FOR_MODDING/.directory' \
    'VICII_SRC_FOR_MODDING/music/*' 'VICII_SRC_FOR_MODDING/sound/*' 'VICII_SRC_FOR_MODDING/movies/*' \
    'VICII_SRC_FOR_MODDING/tutorial/*' 'VICII_SRC_FOR_MODDING/launcher/*' 'VICII_SRC_FOR_MODDING/battleplans/*'
mv VICII_SRC_FOR_MODDING vanilla
```

Quedan 8 861 archivos en `vanilla`, 8 499 en `Plantilla Mod` y 8 564 en `ShagoMod`. Las pruebas de corpus se
activan con las tres rutas (separadas por `:`; en Windows, por `;`):

```bash
VIC2_CORPUS="/home/user/corpus/vanilla:/home/user/corpus/Plantilla Mod:/home/user/corpus/ShagoMod" \
    QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" python3 -m unittest discover -s tests
```

En vanilla, los únicos archivos Clausewitz con errores de sintaxis son textos en prosa (`history/units/v2dd2.txt`,
`interface/credits.txt` y `mod/dummy.txt`). A la plantilla le faltan, entre otras, las carpetas `map/`, `events/`,
`decisions/`, `units/` e `interface/`.

### Python 3.10 y 3.11

El mínimo declarado es Python 3.10. Se encontró y acotó un fallo de PySide6, no del proyecto:

- **PySide6 6.12.0 suelta referencias de más a `None`, `True` y `False`**: una por cada tarea de `QThreadPool`
  (con o sin valor de retorno, también con `QRunnable.create`) y alguna más al emitir señales con argumentos
  `object`. Desde Python 3.12 esos objetos son inmortales y no pasa nada; con 3.10 y 3.11 el proceso aborta tarde
  o temprano («Fatal Python error: none_dealloc», «bool_dealloc» o «free(): invalid size»). Con PySide6 6.11.3 el
  recuento queda en 0 en 3.10, 3.11 y 3.12. Reproducción mínima:

  ```python
  import sys
  from PySide6.QtCore import QCoreApplication, QRunnable, QThreadPool
  app = QCoreApplication([])
  class R(QRunnable):
      def run(self): pass
  pool, before = QThreadPool(), sys.getrefcount(None)
  for _ in range(200): pool.start(R())
  pool.waitForDone()
  print(sys.getrefcount(None) - before)  # 6.12.0 con Python 3.10/3.11: -200; 6.11.3: 0
  ```

- **Arreglo hecho**: `pyproject.toml` y `requirements.txt` piden `PySide6>=6.5,<6.12` en Python < 3.12, y
  `tests/test_ui_smoke.py` ya no usa `TestCase.enterContext` (3.11+), sino `UiTestCase.enter_context`.
- **Aviso al arrancar** (`093f8b3`, `src/vic2studio/compat.py`, sin Qt): la aplicación y `tests/_qt.py` paran con un mensaje claro
  si encuentran esa combinación; `VIC2STUDIO_ALLOW_BROKEN_PYSIDE=1` lo salta.

Para probar con 3.10 (en la nube hay uno en `/root/.local/bin/python3.10`):

```bash
/root/.local/bin/python3.10 -m venv /tmp/py310
/tmp/py310/bin/pip install "PySide6-Essentials>=6.5,<6.12" "numpy>=1.24" "Pillow>=10"
QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" PYTHONDONTWRITEBYTECODE=1 \
    /tmp/py310/bin/python -m unittest discover -s tests
```

El usuario usa Python 3.14 en local; nadie ha pasado la batería con 3.14 todavía (su recolector incremental puede
cambiar las pausas que miden las pruebas de latido).

### PySide6 6.5, el mínimo declarado

Pasar la batería con PySide6 6.5.0 encontró tres fallos de verdad (§3, «Iteración 2»). Para repetirlo:

```bash
uv venv -p python3.10 /tmp/v650 && uv pip install -p /tmp/v650/bin/python \
    "PySide6-Essentials==6.5.0" "numpy==1.24.0" "Pillow==10.0.0"
cd tests && env -u XDG_RUNTIME_DIR QT_QPA_PLATFORM=offscreen PYTHONPATH=../src \
    /tmp/v650/bin/python -m unittest discover -s .
```

Con PySide6 6.5 o 6.6 y numpy 2, cada import de PySide6 escribe una traza falsa en stderr y falla
`test_tasks.ShutdownTests`: es la combinación de dependencias, no el código.

## 5. Próximas tareas, en orden

### 0. Hecho: fallo de segmentación al pintar y segunda ronda de la revisión (27-10-2026)

**Fallo de segmentación intermitente.** Estaba en la iteración 1 desde `9040839` y ya está corregido.

- *Síntoma.* Con varias baterías a la vez, `test_ui_integration` con corpus moría al pintar un degradado en el
  hilo de la interfaz.
- *Causa.* `tasks._resume_gc` contaba los objetos jóvenes con `len(gc.get_objects(0))` desde el hilo de la última
  tarea. Esa lista retenía también objetos de la interfaz. Si la interfaz soltaba entretanto su `QPainter` o su
  `QBrush`, la última referencia moría en la tarea y el objeto de Qt se destruía fuera de su hilo.
- *Cómo se encontró:*
  - `faulthandler`;
  - la traza nativa de `gdb`, con los demás hilos quietos;
  - en 3 de 12 fallos, un hilo de tarea estaba justo en esa línea.
- *Arreglo.* Ahora se cuenta con `gc.get_count()[0]` más lo que `release_in_background` descontó del contador
  (`_gc_released`).
- *Pruebas.* La prueba determinista es
  `test_tasks.test_resuming_the_collector_holds_nothing_the_interface_owns`. En la prueba de esfuerzo, el código
  antiguo reventó unas 12 veces en unas 130 ejecuciones, y el nuevo 0 en 78.
- *Regla:* **nada que retenga objetos ajenos (`gc.get_objects`, `gc.get_referrers`…) en un hilo de tarea.**

**Segunda ronda de la revisión adversarial.** Fue una lectura de los arreglos de `57e4365`. Dejó dos cambios:

- **F4 (media).** Un mod copiado o renombrado tras un guardado cortado no se podía volver a guardar nunca: su
  diario ajeno bloqueaba con `save_journal_pending`. Ahora un diario ajeno no bloquea.
- **F2 (baja).** `create_mod_skeleton` se tragaba un `KeyboardInterrupt` llegado tras confirmar.

Cada uno tiene su prueba y su mutación. Otros dos quedan sin código, con su motivo en ARCHITECTURE.md §6.1. Si
quieres otra ronda con varios agentes, el guion es `docs/handoff/workflow_iteracion2_revision.js`, apuntado al
commit de las correcciones; pero solo si el usuario lo pide (ultracode u «usa un workflow»).

### 1. Capturas, README e informe de la iteración 2 (criterio 10): hechos

Capturas ES/EN a 1100×700 y 1920×1080 de Inicio, Descriptor .mod, Archivos, Cambios pendientes y el diálogo de
revisión, revisadas a mano (textos cortados, claves crudas, columnas estrechas):

```bash
python3 tools/screenshot.py --out DIR --lang all --size 1100x700 --mod tests/fixtures/shago_mod_min/VSM \
    --demo-game --demo-changes --no-game-art \
    --page project:home,project:descriptor,project,project:pending --dialog save_review
```

**Hecho (27-10-2026).**

- Las 20 capturas se regeneraron después de las correcciones y se revisaron una a una, sin defectos.
- Se subieron 10 a `docs/capturas/` (de la 11 a la 20): las 5 vistas, en español a 1100×700 y en inglés a
  1920×1080. Las texturas no se comprimen, y las 20 pesarían unos 20 MB; la orden de arriba regenera todas.
- El README describe ya la iteración 2: 7 salas, proyecto, descriptor, guardado con diario, deshacer y
  recuperación.
- El informe de la iteración 2 se dio al usuario en el chat.

### 2. Criterios con corpus: hechos (27-10-2026)

El usuario subió el corpus a la release `recursos-v1` del repositorio. Se descarga por la API de GitHub (la URL
directa da 404 porque el repositorio es privado; el proxy de la nube pone la autenticación):

```bash
curl -sSL -H "Accept: application/octet-stream" -o <nombre> \
    https://api.github.com/repos/pickatroll12-arch/VictoriaII_ModWizard/releases/assets/<id>
```

(los `id` y los sha256 salen de la release). Se descomprime fuera del repositorio como dice §4. Con él, los
criterios 1 y 3 se cumplen: 1089 pruebas OK sin omitir ninguna, ida y vuelta de 12 054 archivos y el criterio 3
sobre vanilla real + VSM. Además, el Shago Mod completo abre sobre vanilla en 0,12 s, su `somaliland_shago.txt`
roto se abre en solo lectura y guardar sin cambios no escribe nada.

### 3. Iteración 3 (wizard.md §22): hecha (27-10-2026)

Índice de símbolos, validación con línea base, localización editable sincronizada y Ctrl+K. Contrato, 2 agentes,
integración contra el núcleo real con la prueba de punta a punta de la ventana, revisión adversarial en tres
partes con sus correcciones, capturas 21 a 26 e informe. Los 8 criterios se cumplen (ARCHITECTURE.md §6.1). Lo
que quedó sin código, con su motivo, está en §6.

### 4. Iteración 4 (wizard.md §22): hecha (28-10-2026)

Motor de esquemas y editor genérico: gobiernos, casus belli, bookmarks, culturas, unidades terrestres y navales
(capacidades 4, 9, 10, 11, 12 y 13). Mismo ritmo.

**Ya hecho (corte vertical, `opencode/it4-motor`, integrado).**
- El contrato completo de wizard §10 en `core/schema/`.
- `Record` y `Entities`, con la vista efectiva, una transacción por operación e ids validados.
- `SingleFile` y `OnePerFile`, y `MappingTable` sobre las 14 tablas de `rebel_types.txt`.
- Los esquemas `government` y `unit`, con vistas `land` y `naval`.
- `tests/schema_harness.py` (`SchemaContract`) y sus pruebas.

**Hecho después (rama `opencode/it4-claude`).** Los esquemas `casus_belli`, `bookmark`, `culture`/`culture_group`,
`event_modifier` y `readonly`; los compañeros `ActivateUnit` y `UnitNamesSlot`; docgen, la CLI y
`docs/referencia/`; `schema_problems` en F7; toda la interfaz (formularios, selectores, editor de entidades, las 7
secciones, matriz de rebeldes y `end_date`); `Session.entities`; `restore_vanilla`. Siguen como contrato
`history.py` (iteración 5), el guion (`Record.script`, iteración 7) y las recetas con nombre (iteración 6).

Las decisiones y desviaciones del motor están en `docs/handoff/opencode/INFORME_MOTOR.md`. Lo que la iteración 3
deja preparado:

- `SymbolIndex` y `GameRules` son la fuente de los selectores (`SymbolPicker`) y de las validaciones de
  esquema.
- `LocSync.ensure` crea las claves de cada entidad, y `Session.edit` hace la transacción.
- Ctrl+K ya emite `symbol_activated`: con la iteración 4 tiene que abrir el editor de la entidad en vez del
  archivo (`MainWindow.open_symbol`).
- Las reglas nuevas se registran con `@rule` y necesitan `issue.<código>`, `explain.title.<código>` y
  `explain.outcome.<código>` en ES y EN. `test_validate_rules` exige un caso por código y una frase propia en el
  explicador.

### 5. Iteración 5 (wizard.md §22): lo siguiente

Editor de mapa: provincias, POPs, modos de mapa, regiones, continentes, climas y estrechos (capacidades 3 y 14),
con el reparto de wizard.md §22 (agente A: `core/map/**` y los esquemas del mapa; agente B: `ui/map/**` y la sala
Mapa). Lo que dejan preparado las iteraciones anteriores:

- `core/map/{bmp,definition}.py` y `core/tablecsv.py` (G4–G5, sin pérdidas) y el índice de provincias, regiones,
  continentes y climas (iteración 3).
- El motor de esquemas (iteración 4): los esquemas del mapa (`province_history`, `pops`, `region`…) se escriben
  como los de la 4, con su prueba de 3 líneas. `history.py` (historia fechada, §10.6) sigue como contrato y es la
  pieza nueva más delicada de esta iteración: la historia de provincias depende de la fecha de trabajo.
- `SectionSpec` y el registro de esquemas: las secciones de Mapa salen solas si su esquema declara `hall="map"`.
- Las lecciones de las rondas con agentes (`docs/handoff/opencode/INFORME_*.md`): probar con el corpus real (el
  mapa de vanilla es grande), medir el hilo de la interfaz y mantener la vista efectiva tras deshacer y guardar.

### Método de trabajo (wizard.md §20)

- **Contrato primero.** Cada iteración empieza con un commit de contrato: dataclasses, `Protocol` y funciones que
  lanzan `NotImplementedError`.
- **2 agentes con archivos disjuntos.** Cada archivo compartido (`ui/main_window.py`, `i18n/__init__.py`,
  `pyproject.toml`…) tiene un único dueño por iteración. Esquemas, salas, reglas y extractores se registran por
  descubrimiento, y los textos van en fragmentos JSON. El agente B trabaja contra el contrato y el minijuego hasta
  la integración.
- **Una copia del repositorio por agente.** En T4, dos agentes editando el mismo árbol rompieron baterías ajenas;
  las rondas siguientes trabajaron en copias aisladas (`cp -a` del repositorio fuera de él, sin remoto, o
  worktrees en `.claude/worktrees/`, ignorada por git) y el orquestador integró con `git diff HEAD` y
  `git apply --3way`. Para pasar la batería mientras se sigue editando, cópiala a una carpeta temporal
  (`git ls-files` más lo modificado) y ejecútala allí.
- **Integrar contra el núcleo real.** Los falsos dejan avanzar en paralelo, pero esconden diferencias: en la
  iteración 2 la prueba de punta a punta contra el `Project` real encontró cinco fallos que las pruebas contra el
  falso no veían.
- **Ritmo.** Contrato, implementación en paralelo, integración, verificación adversarial (cada verificador
  reproduce cada hallazgo antes de reportarlo), correcciones con una prueba de regresión que falla antes del
  arreglo, mutaciones para comprobar que las pruebas detectan el fallo, segunda ronda, capturas e informe al
  usuario en español.
- **Commits** con mensaje en español que resume el cambio y las pruebas. Nunca subas datos del juego.

## 6. Límites conocidos que se dejaron a propósito

Medidos sobre una máquina de 4 CPU compartidas.

| Límite | Medida | Por qué se dejó |
|---|---|---|
| Mostrar la pestaña Código de un archivo de 20 MB (1,3 M líneas) | 0,61–0,70 s en el hilo de la interfaz: `QPlainTextEdit.setDocument` maqueta todos los bloques | Crear los `QTextLayout` en la tarea lo baja a 0,23–0,28 s, pero alarga cada carga grande unos 6 s (+30 %) y ocupa unos 350 MB más aunque la pestaña no se abra. Documentado en `code_view.py`. |
| Destruir ese documento al pasar a otro archivo (NF-DOC-DELETE) | 159–349 ms en el hilo de la interfaz | Vaciarlo por trozos tarda 1,4–1,9 s y retiene el GIL; reutilizarlo cuesta lo mismo; destruirlo en otro hilo no es seguro (sus bloques apuntan a motores de fuente del hilo de la interfaz). Documentado en `code_view.py`. |
| Cancelar el JSON de un archivo grande y cambiar de archivo (NF-JSON-HELD-ROOT) | Pausa de unos cientos de ms si la tarea JSON aún retiene la raíz | Solo rendimiento; desmontar solo toca objetos del visor, nunca el árbol del núcleo. |
| Validar un archivo grande (NF-VALIDATE-TREE-RELEASE) | Huecos de 206–260 ms con 7,9 MB al soltar su árbol en `core.modcheck.check_file` | Pasa con holgura el límite de 0,5 s; trocearlo sería en el núcleo. |
| Basura congelada en cadena (GC) | Con dos resultados grandes seguidos, la basura cíclica congelada con el primero no se recoge hasta que no vive ningún resultado vigilado | Recogerla antes obliga a recorrer el resultado vivo (0,4 s con 3 MB, 2,5 s con 20 MB) o a una pasada completa por tarea (17–28 ms por clic). Lo fija `test_garbage_frozen_with_a_chain_of_large_results_waits_for_the_last_one`. |
| Ediciones junto a texto descartado en archivos con errores de sintaxis | Tras evitar que el texto nuevo se pegue a la palabra siguiente, un ~10 % de documentos rotos aleatorios aún se releen distinto (entradas tras un bloque sin cerrar acaban dentro de él, o un valor suelto forma asignación con un operador descartado) | `write_file(verify=True)` rechaza el 100 % (0 escrituras inseguras en unos 33 000 documentos) con un mensaje propio. El Wizard abre esos archivos en modo solo texto (D17). |
| Bloque de una línea dentro de otro con un comentario nuevo | Se reescribe una vez desde la `{` exterior | Coste acotado a una línea; caso raro. |
| `ClausewitzViewer.cancel()` solo para el JSON | El análisis sigue con la vista oculta | Un reanálisis debe terminar aunque la vista esté oculta; el JSON se rehace al volver. |
| Tabla de validación con el divisor al mínimo | Con VSM queda barra horizontal y «Mensaje» mide 100 px | A ese ancho no caben las cuatro columnas; la ayuda emergente muestra la ruta entera. |
| `SourceMismatchError` no se puede pasar por `pickle` | Su `__init__` pide 3 argumentos | Hoy no se usan procesos. Hay que arreglarlo antes de que un error de guardado cruce al proceso trabajador del taller de mapas (wizard.md §18.4). |
| Deshacer tras guardar una copia hecha desde el juego (iteración 3) | Deja en el mod una copia idéntica en vez de quitarla | Inofensivo, y la validación la señala (`mod_shadow_identical`, con su arreglo). Quitarla al deshacer exige que el diario sepa borrar lo que creó un guardado anterior. |
| Planear, aplicar y guardar en el hilo de la interfaz (iteración 3) | Con VSM, la papelera de 8 462 copias: unos 3 s al aplicar y 4,7 s al guardar | Tocan el `Workspace`, que es de un solo hilo (I12). Hay cursor de espera y la barra de estado dice lo que se hace (`ui/widgets/busy.py`). |
| Primera edición del `text.csv` de VSM (iteración 3) | Unos 0,1 s analizando 3,6 MB en el hilo de la interfaz | Por debajo del límite de 0,5 s; una API para adoptar un modelo leído en segundo plano no compensa todavía. |
| `LocSync.entries()` con VSM (iteración 3) | 0,15–0,3 s por edición (21 661 claves) | Se reutiliza mientras nada cambia, y la página oculta no se refresca. Trocearlo sería un índice de localización incremental. |
| Construir la ventana | Unos 0,65 s | Hallazgo opcional 23 de la revisión de la iteración 3; se reducirá con el empaquetado (iteración 10). |
| Editor de texto con archivos de más de 1 MB | Cada pausa al teclear en `map/positions.txt` (1,35 MB) cuesta 0,6–1 s; uno de 200 KB, 50–80 ms | Reanalizar el documento entero en cada pausa (`replace_text`) en el hilo de la interfaz (I12). En vanilla solo pasa con `positions.txt`. |
| ~~`Entities` tras borrar la copia del mod de algo que también está en vanilla~~ | **Resuelto en la iteración 4**: `list` y `open` leen la capa de debajo de la lápida, y editar revive el documento (`Entities.restore_vanilla`, §10.5) | — |
| ~~F7 sobre un archivo con cambios sin guardar~~ | **Resuelto en la iteración 4**: se abre en el editor de texto, que enseña la memoria, en su línea | — |
| `defines.lua` sin códec propio (iteración 4) | `end_date` se cambia con `Workspace.restore_bytes` sobre el documento binario | `test_project_codecs` exige que el tipo LUA siga sin códec; un códec LUA es de `core/project` (iteración 10). |
| Renombrar entidades (iteración 4) | Ni el botón ni `Entities.rename`; el id de un bookmark (`name`) no se edita en el formulario | Llega con el renombrado seguro (§15); los `on_rename` de los compañeros siguen como contrato. |

## 7. Problemas detectados en el mod del usuario (Shago Mod)

Se le reportaron al usuario y **no se han corregido**: no lo pidió y su mod no está en este repositorio. Los de los
archivos que creó el usuario se comprueban con la muestra `tests/fixtures/shago_mod_min`; los demás, con el mod
completo del corpus.

- Falta la `}` final de `political_decisions` en `decisions/somaliland_shago.txt` y `decisions/zulu_expancionshago.txt`.
- `00_VSM_countries.csv`:
  - `GEL_reactionary` y `MAJ_reactionary` tienen un `Geledi;` sobrante que desplaza las columnas;
  - en `SOM_ADJ` la columna del español dice «Somalisch»;
  - `SOM` en inglés dice «Somaliland».
- `00_VSM_decisions.csv`: seis textos ingleses entre comillas con un `;` dentro (el juego no interpreta comillas y
  el `;` desplaza las columnas). Ninguna fila de sus tres CSV lleva la `x` final, que el juego no necesita.
- Warsangali (WRL) usa los partidos `MAJ_*` de Majeerteen, y Somalia arranca con `ruling_party = SOM_socialist`
  siendo monarquía absoluta, que en VSM solo admite liberales, conservadores y reaccionarios.
- `nationalvalue = nv_tradition`, que no existe, en GEL, MAJ, SOM y WRL (el juego solo define `nv_order`,
  `nv_liberty` y `nv_equality`).
- Los partidos de 5 de los 6 países nuevos (todos menos el Imperio Zulú) usan `social_policy`, que no está entre
  los asuntos de partido de `common/issues.txt`.
- El `governments.txt` de VSM pone `election = yes` en `absolute_monarchy` sin `duration`.
- SIL (Silesia) tiene historia, archivo de país, banderas, localización y núcleos (`add_core`) en las provincias
  682–685, pero no está registrado en `common/countries.txt`.
- **VSM es una copia completa del juego**: de sus 8 563 archivos, 8 462 son idénticos a los de vanilla, 29 difieren
  (5 de `common/`, una bandera, una historia de POPs, 21 historias de provincia y `text.csv`) y 72 son nuevos.
  `VSM.mod` no declara `replace_path`. Consecuencias para el Wizard:
  - Editar en el Studio un archivo del juego modificará la copia de VSM (criterio 3 de la iteración 2).
  - Las 8 462 copias idénticas saldrán como `mod_shadow_identical` (info), con limpieza opcional a la papelera.
  - `replace_path` no oculta los archivos del propio mod. Si el taller de mapas exportara a VSM con «Solo mapa» o
    «Mundo», seguirían cargándose sus 2 705 historias de provincia, 358 archivos de POPs, 265 OOB, 5 guerras y 4
    diplomacias. Por eso el diseño los manda a la papelera antes de exportar (paso 0 de wizard.md §18.8, regla
    `replace_path_mod_files_remain`) y recomienda el destino «Mod nuevo» (§18.1).
- El `text.csv` de VSM (3,6 MB, igual que el de `Plantilla Mod`) sustituye al de vanilla. Tiene 3 438 filas
  degradadas, de 3 430 claves: un `?` donde vanilla tiene una letra acentuada, a veces junto a 1 o 2 caracteres
  más. 3 de esas claves las gana otro archivo que carga antes, así que en partida salen rotas 3 427 en francés,
  alemán y español. Lo señala `loc_copy_degraded`, con el arreglo «Recuperar las filas de vanilla» (3 438 filas).
- CSR solo tiene sus 5 banderas (`gfx/flags/CSR*.tga`, que vanilla no trae), sin registro, historia ni textos
  (`flag_tag_not_registered`, información).
- `history/units/v2dd2.txt` (un diario en prosa) y `history/units/1861/HAI_oob.txt` (en UTF-8) son idénticos a los
  de vanilla: son problemas heredados del juego, no del mod.
- Erratas en los textos en español: «Tecnoligias», «modernizal», «Formameros» y «Uncivilizef».
