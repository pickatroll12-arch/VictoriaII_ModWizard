# Traspaso para Claude Code: cómo continuar

Este documento permite retomar Victoria II Mod Studio en una sesión nueva de Claude Code (en la nube o en local)
sin el contexto de las anteriores. Dice en qué estado está el proyecto, qué se decidió, qué hay implementado, cómo
preparar el entorno y qué hacer después, en orden.

> Léelo entero antes de tocar código. Después, en este orden:
> 1. `docs/diseno/wizard.md`, el diseño del objetivo ampliado (iteraciones 2 a 10). Empieza por §0 (el diseño en
>    una página), §20 (trabajo con 2 agentes), §22 (plan de iteraciones) y §24 (decisiones del usuario, que mandan
>    sobre todo lo demás).
> 2. `ARCHITECTURE.md`: la arquitectura del código. Ojo: todavía marca como «llega en la última ronda de T4» cosas
>    que ya están en el código (§5, paso 4).
> 3. `README.md`: qué funciona hoy y cómo ejecutar, probar, capturar y usar las CLI.
> 4. `docs/requisitos/prompt_maestro_creador_de_mods_victoria_ii.md`: los requisitos originales del usuario.

## Cómo arrancar la sesión

Un mensaje inicial que funciona:

```text
Lee CONTINUAR_EN_CLAUDE_CODE.md entero y continúa desde §5, paso 1. Respóndeme en español.
```

Para trabajo grande el usuario usaba *ultracode* (workflows con varios agentes y verificación adversarial): da
más garantías, pero gasta bastantes más créditos. Sin él, trabaja igual por pasos: reproduce cada fallo antes de
arreglarlo, deja una prueba de regresión que falle sin el arreglo y pasa la batería completa antes de cada commit.

---

## 0. Estado actual (26-10-2026, proyecto en pausa)

- **Rama.** `claude/project-thread-pfuk53`. Los PR #1, #2 y #3 están fusionados en `main`. Esta rama parte de
  `main` (`cfb65a5`) y lleva la última ronda de T4, el arreglo de compatibilidad con Python 3.10/3.11 y este
  traspaso, en un PR abierto contra `main`. Si ese PR ya está fusionado, crea una rama nueva desde `main`.
- **Hecho.**
  - T1–T4 de la iteración 1: integración revisada, pruebas independientes del corpus, verificación adversarial por
    componente, corrección de todos los hallazgos con prueba de regresión, segunda ronda y ronda cruzada entre
    núcleo e interfaz.
  - Última ronda de T4, **parser**: corregida, verificada por un agente independiente, recorregida e integrada
    (commit «Parser: posiciones finales públicas, avisos de UTF-16 y BOM repetidos»). Detalle en §3.
  - Última ronda de T4, **interfaz**: corregida e integrada (commit «Interfaz: árbol grande liberado fuera del
    hilo de la interfaz, etiquetas UTF-16 y repaso»), **sin su segunda revisión adversarial**: la pausa la cortó a
    medias. Es el paso 1 de §5.
  - Compatibilidad con Python 3.10 y 3.11 (§4, «Python 3.10 y 3.11»): tope de PySide6 y pruebas sin
    `enterContext`.
  - Diseño del Wizard (`docs/diseno/wizard.md`) y del taller de mapas (§18), con prototipos medidos en
    `docs/diseno/prototipos/mapforge/` y la licencia MIT de Azgaar's Fantasy Map Generator en
    `THIRD_PARTY_NOTICES.md`.
  - `ARCHITECTURE.md` y `README.md` reescritos según el código y verificados (antes de integrar la última ronda).
- **Pruebas** (en la nube: Python 3.13.17, PySide6 6.12.0, numpy 2.5.3, Pillow 12.3.0): 593 OK con el corpus
  completo y 593 OK con 3 omitidas sin `VIC2_CORPUS`. Con Python 3.10.20 y PySide6 6.11.3: 593 OK con 3 omitidas.
- **Queda**, en orden: §5.

---

## 1. Qué es y qué pidió el usuario

- **Victoria II Mod Studio**: aplicación de escritorio (Windows y Linux) para crear y editar mods de Victoria II
  (motor Clausewitz) de forma 100 % visual, con estética de Victoria II e interfaz en español e inglés.
- El usuario habla **español**: respóndele siempre en español. Los documentos van en español, salvo el resumen en
  inglés del README. Prefiere respuestas ricas y detalladas.
- **Iteración 1** (sección «Instrucciones de Ejecución y Entrega» de los requisitos): propuesta de arquitectura y
  stack (`ARCHITECTURE.md`), estructura de directorios, motor de parseo Clausewitz `.txt` ⇄ JSON y CSV ⇄ JSON y
  ventana principal con estética Victoria II, selector ES/EN y navegación entre 5 módulos. Solo le falta cerrar
  §5, pasos 1 a 6.
- **Objetivo ampliado.** El Wizard debe cubrir 15 capacidades (wizard.md §14): generar el `.mod`; ver, crear y
  editar países, provincias, unidades terrestres, decisiones, eventos, guerras de inicio, casus belli, bookmarks,
  gobiernos nuevos, unidades navales, culturas y regiones; una suite de modificación de interfaces; y un taller
  de mapas nuevos que genera o importa un mapa con todos sus archivos dependientes. El plan las reparte en las
  iteraciones 2 a 10 (la 9 dividida en 9a y 9b).
- **Avance** (lo que se le dijo al usuario el 26-10-2026): alrededor de un 15 % del programa completo por
  esfuerzo; diseño completo, cimientos casi terminados y 0 de las 15 capacidades de edición todavía.

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
  líneas de archivos del juego. Ojo con dos cosas pendientes (§5, paso 5): los archivos de país de
  `tests/fixtures/shago_mod_min` vienen del mod del usuario, pero este los copió de vanilla en parte (bloques de
  partidos y listas `unit_names`), y dos capturas de `docs/capturas/` muestran archivos de vanilla.
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

### Respuestas del usuario (wizard.md §24, 26-10-2026)

Mandan sobre cualquier otra parte del diseño. En resumen:

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

La aplicación tiene 5 módulos en la barra de navegación (Ctrl+1 a Ctrl+5) y todavía no modifica archivos del juego
ni del mod desde la interfaz: la escritura existe en el núcleo y en la CLI `fromjson`, y la edición desde la
interfaz empieza en la iteración 2. Los mensajes de los commits resumen cada ronda: `fadf29e` (núcleo), `899ecca`
(parser), `606811e` (interfaz) y los dos de la última ronda de T4.

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

- **`i18n/`**: `Translator` con cambio de idioma en vivo; 339 claves en paridad ES/EN, que las pruebas recorren
  también con una pseudo-localización para encontrar textos sin traducir.
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
  - Mapa, Países y Eventos: tarjetas de módulo en desarrollo, con la numeración vieja de iteraciones (§5, paso 3).
- **`ui/widgets/navigation.py`**: los nombres de módulo se parten en dos líneas si no caben (antes se recortaban
  a 1100×700 en español).
- **`tools/screenshot.py`**: capturas sin pantalla, con `--open-file`, `--line`, `--search`, `--tab`, `--validate`,
  `--left-tab` y `--report` (opciones en el README). Las de `docs/capturas/` son anteriores a T4.

### Pruebas

593 pruebas en 22 archivos `tests/test_*.py` (parser `test_clausewitz_*`, CSV `test_csvloc_*`, `test_encoding`,
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
- **Pendiente** (§5, paso 2): un aviso al arrancar si alguien ya tiene esa combinación instalada.

Para probar con 3.10 (en la nube hay uno en `/root/.local/bin/python3.10`):

```bash
/root/.local/bin/python3.10 -m venv /tmp/py310
/tmp/py310/bin/pip install "PySide6-Essentials>=6.5,<6.12" "numpy>=1.24" "Pillow>=10"
QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" PYTHONDONTWRITEBYTECODE=1 \
    /tmp/py310/bin/python -m unittest discover -s tests
```

El usuario usa Python 3.14 en local; nadie ha pasado la batería con 3.14 todavía (su recolector incremental puede
cambiar las pausas que miden las pruebas de latido).

## 5. Próximas tareas, en orden

### 1. Segunda revisión adversarial de la última ronda de la interfaz

La pausa la cortó. Lo que hay que intentar tumbar (diff: el commit «Interfaz: árbol grande liberado…»):

| Id | Qué se arregló |
|---|---|
| NF-TREE-RELEASE | El análisis viejo se desmonta en segundo plano por trozos (`release_in_background`, `dismantle_load`); nada de Qt sale de su hilo (`load.document = None` antes de entregar). |
| TASKS-HANDOFF-RACE | `_Job` ya no retiene lo entregado: era la causa de una prueba intermitente del recolector. |
| NF-7 y NF-UNREADABLE-BADGE | Nombres de las 4 codificaciones UTF-16 en el visor y en la ficha; insignia roja «Ilegible para el juego». |
| REVIEW-DIAG-TAB-UNREADABLE | La pestaña Diagnósticos ya no dice «Sin diagnósticos» en verde para un archivo UTF-16. |
| NF-R3-HEADER-BLINK, NF-IMAGE-BLINK y NF-IMAGE-CANCEL | Reintentar un fallo de lectura ya no parpadea (visor de scripts e imágenes) y cancelar no deja «cargando…». |
| REVIEW-HEADER-ELIDE, REVIEW-FACTS-WRAP y REVIEW-NAV-NAMES | Cabecera, ficha y navegación sin textos cortados a 1100×700. |
| NF-FACTS-PARTIAL | La ficha ya no llama cp1252 a un UTF-8 de más de 2 MiB según dónde caiga el corte de lectura. |
| NF-SINGULAR-LINE | «1 línea» en singular. |

Para cada uno: reprodúcelo contra `cfb65a5` y contra el código actual, comprueba que su prueba falla sin el
arreglo (mutación) y busca regresiones (API de Qt posterior a 6.5, Python 3.10, hilos o temporizadores vivos,
textos sin traducir). Sin arreglar a propósito: NF-DOC-DELETE y dos más (§6).

Un choque que apareció al integrar las dos rondas, ya resuelto en la prueba: la interfaz se escribió cuando un
UTF-16 solo ASCII no daba ningún diagnóstico, y ahora `parse_file` da `unreadable_encoding`. Así que la pestaña
Diagnósticos de un UTF-16 muestra esa fila en la tabla, y el estado vacío «Ilegible para el juego»
(`viewer.unreadable_text`) ya no se ve nunca. Decide si se quita ese estado y sus claves o si se deja como red de
seguridad.

### 2. Aviso al arrancar con PySide6 6.12 en Python 3.10/3.11

`app.main` y `tests/_qt.py` deberían detectar la combinación rota (Python < 3.12 y PySide6 ≥ 6.12) y parar con un
mensaje claro (en la aplicación, un `QMessageBox` traducido con claves nuevas en `i18n/{es,en}.json`; en las
pruebas, un error al importar `_qt`) en vez de abortar al rato. Con prueba.

### 3. Hoja de ruta de las páginas con la numeración nueva

Las tarjetas de Mapa, Países y Eventos y su hoja de ruta (`roadmap.*`), y los avisos de solo lectura de
Localización (`localisation.roadmap` y `loc.read_only`), siguen el plan viejo (mapa en la 3, países en la 4,
eventos en la 5, edición de textos en la 2). wizard.md §22 manda: editor de mapa en la 5, países en la 6, eventos
y decisiones en la 7 y localización editable en la 3. El usuario ya lo vio en una captura y se le dijo que se
corregiría.

### 4. Documentos al día con la última ronda

- `ARCHITECTURE.md` y `README.md` marcan con «Llega en la última ronda de T4» cosas que ya están: quita las marcas,
  describe la API real (§3 de este documento) y actualiza la tabla «Riesgos del código actual» (§6.3 de
  `ARCHITECTURE.md`) y el número de pruebas.
- La sección de requisitos del README ya explica el tope de PySide6 en Python 3.10/3.11 (§4); `ARCHITECTURE.md`
  §1.4 y §7 aún no lo mencionan.
- wizard.md tiene puntos viejos: §21 da por pendientes `detect_newline` → `"\r"`, el escritor de `modfile` e
  `insert_before` (ya hechos, con otra firma); §23 dice que el arreglo de CR está «en curso» (hecho, con
  `LineBreakTests.test_cr_only_files` y `test_encoding.test_cr_only_newlines`); §14.1 trata `dependencies` como
  clave desconocida del descriptor, pero `modfile.ModDescriptor.dependencies` ya la lee y escribe.

### 5. Datos de Paradox en el repositorio: decisión del usuario

- Los archivos de `tests/fixtures/shago_mod_min/VSM/common/countries/` son del mod del usuario, pero comparten con
  vanilla buena parte de los bloques de partidos (63 de 77 líneas) y las listas `unit_names` enteras. Pregúntale si
  los sustituimos por versiones sintéticas (las pruebas que los usan son las de la muestra).
- `docs/capturas/03_estructura_provincia.png` y `04_localizacion_text_csv.png` muestran archivos de vanilla: se
  sustituyen en el paso 6 por capturas de su mod.

### 6. T5: informe final al usuario

En español: qué se entregó en la iteración 1 (T1–T4), el resultado real de las pruebas, los límites conocidos
(§6), los problemas de su mod (§7) y el plan (wizard.md §22, empezando por la iteración 2). Acompáñalo de capturas
en ES y EN a 1100×700 y 1920×1080, revisadas a mano (textos cortados, claves crudas, columnas estrechas), y
sustituye con ellas las de `docs/capturas/` (solo archivos del mod del usuario o de la muestra). Por ejemplo:

```bash
python3 tools/screenshot.py --out capturas --lang all --size 1100x700 --page project \
    --mod tests/fixtures/shago_mod_min/VSM --validate --left-tab validation
python3 tools/screenshot.py --out capturas --lang all --size 1920x1080 --page project \
    --mod tests/fixtures/shago_mod_min/VSM --open-file decisions/zulu_expancionshago.txt --tab diagnostics
```

El 26-10-2026 se le enviaron capturas de vista previa (antes de la última ronda de la interfaz): Proyecto con la
Estructura, Código con el error de `somaliland_shago.txt`, Validar mod (3 953 archivos en unos 4 s, 3 errores,
405 avisos y 3 152 notas), Localización, Editor de Mapa planificado, la interfaz en inglés y la ventana a
1100×700 con los nombres de módulo cortados.

### 7. Iteración 2 (wizard.md §22): cimientos

**Objetivo.** Abrir o crear un mod sobre vanilla y recorrer las 7 salas con tres garantías probadas: nada se
escribe fuera del mod, todo cambio se deshace y un guardado de varios archivos es todo o nada. Entrega la
capacidad 1 (el `.mod`).

**Entregables.** Commit de contrato; `core/vfs/` (rutas, reglas de carga, `WriteGuard` y `VirtualFS`);
`core/project/` (documentos, transacciones con nombre, deshacer por instantáneas, guardado con diario,
recuperación, bloqueo, cambios externos y autoguardado); generador del `.mod` (`DescriptorSpec`,
`render_descriptor`, `create_mod_skeleton`); `ui/session.py`, el armazón de 7 salas (las que no existen, como
tarjeta con su iteración) con Ctrl+1..7 y Ctrl+S/Z/Y; Inicio, Descriptor .mod y Archivos; i18n por fragmentos. El
reparto entre los 2 agentes está en §22: A hace el núcleo y B el descriptor y la interfaz. Lee también §21, los
cambios en el código existente (con las salvedades del paso 4). Parte ya está hecha: el arreglo de CR (el
criterio 2 ya se cumple), `Block.insert_before` y la API de `ui/tasks.py`.

**Criterios de aceptación** (resumen de los 11):
1. La batería pasa sin corpus, con la muestra y con el corpus completo, y se mantiene la ida y vuelta byte a byte.
2. `parse("a = 1 # c\rb = 2\r")` da 2 entradas en las líneas 1 y 2, y `detect_newline` devuelve `"\r"`.
3. Cambiar un CB en el minijuego con mod vacío crea solo `<mod>/common/cb_types.txt`; sobre VSM modifica su copia
   con un diff de 1 línea; el juego base no cambia.
4. Abrir y guardar sin cambios no escribe nada ni crea `.vic2studio/`.
5. `WriteGuard` rechaza rutas del juego, `..` y enlaces que salen del mod, y admite `<juego>/mod/VSM/**` y
   `<juego>/mod/VSM.mod`.
6. Un fallo inyectado en cada paso de un guardado de 3 archivos deja, tras `recover()`, todo como antes o todo
   como después, y recuperar dos veces da lo mismo.
7. Deshacer y rehacer son exactos byte a byte.
8. `render_descriptor(DescriptorSpec("Shago Mod", "VSM", "VSM"))` es igual a `tests/fixtures/shago_mod_min/VSM.mod`.
9. `test_arch_writes`: ninguna escritura cruda fuera de `core/fileio.py`, y dentro del mod solo escribe el diario.
10. Capturas ES/EN a 1100×700 y 1920×1080 sin textos cortados ni claves crudas.
11. Verificación adversarial con hallazgos reproducidos y pruebas de regresión. «El mod nuevo aparece en el
    lanzador y carga» va a la lista de comprobación en el juego, que se entrega al final (decisión 6).

### Método de trabajo (wizard.md §20)

- **Contrato primero.** Cada iteración empieza con un commit de contrato: dataclasses, `Protocol` y funciones que
  lanzan `NotImplementedError`.
- **2 agentes con archivos disjuntos.** Cada archivo compartido (`ui/main_window.py`, `i18n/__init__.py`,
  `pyproject.toml`…) tiene un único dueño por iteración. Esquemas, salas, reglas y extractores se registran por
  descubrimiento, y los textos van en fragmentos JSON. El agente B trabaja contra el contrato y el minijuego hasta
  la integración.
- **Una copia del repositorio por agente.** En T4, dos agentes editando el mismo árbol rompieron baterías ajenas;
  las rondas siguientes trabajaron en copias aisladas (`cp -a` del repositorio fuera de él, sin remoto) y el
  orquestador integró con `git diff HEAD` y `git apply --3way`.
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
- El `text.csv` de VSM (3,6 MB, igual que el de `Plantilla Mod`) sustituye al de vanilla, y 3 430 de sus claves
  tienen un texto distinto. En 3 242 hay un `?` donde vanilla tiene una letra acentuada, así que esos textos salen
  rotos en francés, alemán y español (`loc_copy_degraded`, con el arreglo «Recuperar las filas de vanilla» en la
  iteración 3).
- `history/units/v2dd2.txt` (un diario en prosa) y `history/units/1861/HAI_oob.txt` (en UTF-8) son idénticos a los
  de vanilla: son problemas heredados del juego, no del mod.
- Erratas en los textos en español: «Tecnoligias», «modernizal», «Formameros» y «Uncivilizef».
