# Traspaso para Claude Code (cloud): cómo continuar

Este documento permite retomar el trabajo en una sesión nueva de Claude Code
(por ejemplo, en la nube) sin el contexto de la sesión local original, que se
pausó el **2026-10-25 a las 23:20 (UTC-3)** porque el usuario tenía que apagar el equipo.

> Léelo entero antes de tocar código. Después lee `docs/requisitos/prompt_maestro_creador_de_mods_victoria_ii.md`
> (los requisitos originales del usuario), `ARCHITECTURE.md` y `README.md`.

---

## 0. Actualización 2026-10-26 (sesión en la nube, rama `claude/project-thread-pfuk53`)

- **Corpus real disponible en la nube**: el usuario subió `Plantilla Mod.zip` y `VictoriaShagoMod_for testing`
  (zip) a la biblioteca del proyecto (`/mnt/project-files/`). Se descomprimen fuera del repo, p. ej. en
  `/home/user/corpus/Plantilla Mod` y `/home/user/corpus/ShagoMod` (con `VSM.mod` + `VSM/`), y se activan con
  `VIC2_CORPUS="/home/user/corpus/Plantilla Mod:/home/user/corpus/ShagoMod"`. A la plantilla le faltan las carpetas
  vanilla `map/`, `events/`, `decisions/`, `units/` e `interface/`; por eso el usuario subió también
  `VICII_SRC_FOR_MODDING.zip` (los datos completos del juego base, sin ejecutables): se descomprimen solo las
  carpetas de datos (sin música, sonido ni vídeos) en `/home/user/corpus/vanilla`. El parser hace ida y vuelta byte a
  byte de sus 4.221 archivos Clausewitz; los únicos con errores son textos en prosa (`history/units/v2dd2.txt`,
  `interface/credits.txt`, `mod/dummy.txt`). Corpus completo para las pruebas:
  `VIC2_CORPUS="/home/user/corpus/vanilla:/home/user/corpus/Plantilla Mod:/home/user/corpus/ShagoMod"`.
  Los datos de Paradox nunca se suben al repositorio. También subió una imagen de
  referencia con los IDs de provincia (HoD) y un `.mod` de ejemplo (`name = "Dark Age Mod"`, `path = "mod/DAM"`,
  `user_dir = "DAM"`).
- **T2 hecha**: sin `VIC2_CORPUS` las pruebas usan la muestra `tests/fixtures/shago_mod_min` y una plantilla
  sintética (`tests/_corpus.py: synthetic_template`). Pasan sin corpus, con la muestra, con el corpus completo y
  con un corpus vacío.
- **Objetivo ampliado del usuario** (además de lo de este documento). El Wizard debe poder: generar el archivo `.mod`;
  ver/crear/editar países, provincias, unidades terrestres, decisiones, eventos, guerras de inicio, casus belli,
  bookmarks, nuevos gobiernos, unidades navales, culturas y regiones; una suite de modificación de interfaces; y una
  suite de creación de mapas nuevos desde cero con sus dependencias. El diseño y el plan de iteraciones para cubrirlo
  están en `docs/diseno/wizard.md` (cuando exista) y en la hoja de ruta de `ARCHITECTURE.md`.

---

## 1. Qué es y qué pidió el usuario

- **Victoria II Mod Studio**: aplicación de escritorio (Windows + Linux) para crear y editar mods de
  Victoria II (motor Clausewitz) de forma 100 % visual, con estética de Victoria II e interfaz ES/EN.
- El usuario habla **español**: responde siempre en español.
- Pidió **esfuerzo máximo** y activó *ultracode* (orquestación con workflows y verificación adversarial).
- **Primer entregable (iteración 1)**, según la sección "Instrucciones de Ejecución y Entrega" de los requisitos:
  1. Propuesta de arquitectura y stack → `ARCHITECTURE.md` ✅
  2. Estructura de directorios del proyecto → `ARCHITECTURE.md` §árbol ✅
  3. Motor de parseo Clausewitz `.txt` ⇄ JSON y CSV ⇄ JSON → `src/vic2studio/core/clausewitz/`, `src/vic2studio/core/csvloc/` ✅
  4. Prototipo de la ventana principal con estética Victoria II, selector ES/EN y navegación entre los 5 módulos ✅ (con la integración casi terminada, ver §3)

## 2. Decisiones ya tomadas (no las reabras sin motivo)

- **Stack: Python 3.10+ + PySide6 (Qt 6) + numpy + Pillow.** Al principio se recomendó Tauri + Rust,
  pero en el equipo del usuario no había toolchain de Rust ni webkit2gtk, y PySide6 6.11 y numpy ya
  estaban instalados. La justificación completa, con benchmarks del mapa, está en `ARCHITECTURE.md`.
- **El núcleo (`vic2studio.core`) no depende de Qt.** La UI está en `vic2studio.ui`.
- **Sin pérdidas:** el parser es un árbol de sintaxis concreto con *trivia*, de modo que reescribir un archivo
  sin cambios da los mismos bytes. El CSV también hace ida y vuelta byte a byte.
  La codificación del juego es **cp1252** (con los 5 bytes indefinidos preservados) y se detecta UTF-8.
  Ver `core/encoding.py`.
- **Escritura atómica con `.bak`** (`core/fileio.py`). El juego base es de solo lectura y todo se escribe en la carpeta del mod.
- **Estética 100 % procedural** (QPainter + numpy): nada de texturas, fuentes ni imágenes del juego, por copyright.
- **Convenciones:** identificadores en inglés; docstrings y comentarios en español, concisos.
  Pruebas con `unittest` de la biblioteca estándar. Sintaxis compatible con 3.10 (compruébalo con
  `ast.parse(src, feature_version=(3, 10))`).
- **Preferencias de la app** en INI (`src/vic2studio/settings.py`). En pruebas y capturas usa
  `VIC2STUDIO_SETTINGS_DIR=<carpeta temporal>` para no tocar la configuración real.

## 3. Estado exacto al pausar

El trabajo iba en un workflow de 4 fases. El script está en `docs/handoff/workflow_iteracion1.js`.
Sirve de referencia: contiene los **contratos de API** y los prompts de verificación. Sus rutas son
locales y hay que adaptarlas.

| Fase | Estado |
|---|---|
| 1. Construcción: parser, CSV, UI, docs | ✅ Completa |
| 2. Integración parser/CSV ↔ UI | ⚠️ **Interrumpida casi al final** (el agente fue detenido a las 23:18 mientras retocaba `project_page.py`, `localisation_page.py` y `viewers/localisation_editor.py`). Las pruebas pasan, pero nadie revisó el resultado final. |
| 3. Verificación adversarial (parser, csv, ui, docs) | ❌ No ejecutada |
| 4. Corrección de hallazgos + 2.ª ronda | ❌ No ejecutada |

**Pruebas al pausar** (Python 3.14.7, PySide6 6.11.2):
- Con el corpus completo: `Ran 288 tests … OK`.
- Sin corpus: `OK (skipped=33)`.
- Con la muestra mínima `tests/fixtures/shago_mod_min`: 4 fallos, porque esas pruebas esperan el corpus completo (ver tarea T2).

### Lo que hay implementado

- `core/clausewitz/`: lexer con regex maestra; parser iterativo (sin límite de anidación) y tolerante a errores.
  - Diagnósticos con código, línea y columna, y mensajes ES/EN. Códigos: `unclosed_block`, `unexpected_close_brace`,
    `missing_value`, `missing_key`, `unterminated_string`, `invalid_key`, `unexpected_operator`, `invalid_character`,
    `multiline_string`, `control_character`, `non_game_encoding` y `suspicious_close_brace`, que da una pista de dónde falta la `}`.
  - API de edición que conserva el formato.
  - `to_json`/`from_json`/`simplify`/`walk`/`format_canonical`, y `write_file(verify=True)`.
  - CLI: `python -m vic2studio.core.clausewitz check|tojson`.
  - Corpus: 7.832 archivos y 14,7 MB en ~6 s, con 0 fallos de bytes.
- `core/csvloc/`: formato CSV de Vic2 (`;`, 13 idiomas, marcador `x`, campos extra tras la `x`).
  - `lint` con 9 códigos y `LocalisationDB` (mod > vanilla, gana la primera clave).
  - CLI: `check|tojson|fromjson`.
- `core/modfile.py` (descriptor `.mod`) y `core/modcheck.py` (validación de un mod completo).
- `i18n/`: `Translator` con cambio de idioma en vivo y 180+ claves con paridad ES/EN, verificada por pruebas, incluida pseudo-localización.
- `ui/`: tema procedural (terciopelo, bronce, pergamino, madera), `MainWindow` y 5 páginas.
  - **Proyecto y Archivos**: rutas, explorador y vista previa con pestañas Estructura/Código fuente/Diagnósticos/JSON, imágenes, y botón **Validar mod**.
  - **Localización**: tabla de solo lectura con buscador y lint.
  - **Mapa, Países y Eventos**: tarjetas de "módulo en desarrollo".
- `tools/screenshot.py`: capturas offscreen. Las de muestra están en `docs/capturas/`.

## 4. Preparar el entorno en la nube

```bash
pip install "PySide6>=6.5" "numpy>=1.24" "Pillow>=10"
# Bibliotecas del sistema que suele necesitar Qt offscreen en contenedores Debian/Ubuntu:
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 fonts-dejavu
export QT_QPA_PLATFORM=offscreen
export VIC2STUDIO_SETTINGS_DIR=/tmp/vic2studio-settings
python3 -m unittest discover -s tests -v
```

### Corpus de pruebas

El corpus real **no está en el repo**: son ~640 MB con archivos del juego de Paradox.
- `tests/fixtures/shago_mod_min/` contiene **solo archivos creados por el usuario** de su mod "Shago Mod" (`VSM.mod`):
  sus 4 decisiones, los 3 `00_VSM_*.csv` y los 6 países nuevos.
  `decisions/somaliland_shago.txt` y `decisions/zulu_expancionshago.txt` tienen **errores reales**:
  les falta la `}` final de `political_decisions`.
- En el equipo del usuario el corpus completo era `"<carpeta>/Plantilla Mod"` (mod plantilla con archivos vanilla)
  más el contenido de texto de `VictoriaShagoMod1.0.zip`. Se activa con `VIC2_CORPUS` (rutas separadas por `:`).
  Sin corpus, esas pruebas se omiten.

## 5. Próximas tareas, en orden

**T1. Revisar y cerrar la integración interrumpida.** Lee `ui/pages/project_page.py`, `ui/pages/localisation_page.py`,
`ui/viewers/*.py`, `ui/tasks.py` y `tests/test_ui_integration.py`, y confirma que esté todo esto:
- vista previa en hilo de fondo;
- pestañas Estructura/Código fuente/Diagnósticos/JSON;
- doble clic en un diagnóstico salta a la línea y al nodo;
- los `.csv` abren en Localización;
- vista previa de imágenes con Pillow;
- descriptor `.mod`;
- "Validar mod" con progreso y tabla;
- Localización con modelo de solo lectura, filtro, conmutador de comentarios y lint traducido, cargando el `text.csv` de 3,6 MB en menos de 3 s;
- `tools/screenshot.py --open-file/--validate`.

**T2. Hacer las pruebas independientes del corpus completo.** Con `VIC2_CORPUS=tests/fixtures/shago_mod_min` fallan:
- `test_csvloc_corpus.CorpusRoundTripTests.test_single_edit_changes_single_line`
- `test_clausewitz_edit.RandomEditTests.test_set_on_corpus_changes_only_the_token`
- `test_modcheck.UserModTests.test_user_mod_has_exactly_the_known_errors`, que espera además `history/units/v2dd2.txt`, un diario de desarrollo de Paradox que tiene `missing_key` en la línea 4
- `test_ui_integration.ValidationTests.test_validate_user_mod_finds_both_unclosed_blocks`

Haz que se adapten a lo que haya disponible, o que se omitan con un motivo claro, sin debilitar lo que comprueban cuando sí está el corpus completo.

**T3. Verificación adversarial por componente** (la fase 3 que no llegó a correr). Usa los prompts `verify` de
`COMPONENTS` en `docs/handoff/workflow_iteracion1.js`:
- parser, con esfuerzo máximo;
- csv;
- ui, revisando capturas en ES y EN a 1100x700 y 1920x1080;
- docs: que el árbol de `ARCHITECTURE.md` coincida con los archivos reales y que los comandos del README funcionen.

Que cada verificador reproduzca cada hallazgo antes de reportarlo.

**T4. Corregir los hallazgos** con pruebas de regresión y una segunda ronda de verificación. Después, **actualiza
`ARCHITECTURE.md` y `README.md`** para que reflejen el código real (añadidos posteriores a los contratos: `settings.py`, `ui/tasks.py`,
`ui/viewers/`, `core/modfile.py`, `core/modcheck.py`).

**T5. Informar al usuario** en español: qué se entregó, resultado real de las pruebas y capturas. Propón la iteración 2:
- VFS vanilla + mod;
- generador del `.mod`;
- editor de localización editable con sincronización de claves;
- validador global.

Las iteraciones siguientes: 3 mapa, 4 asistente de países con banderas `.tga`, 5 eventos y decisiones, 6 empaquetado.
Ver la hoja de ruta en `ARCHITECTURE.md`.

## 6. Problemas detectados en el mod del usuario (Shago Mod)

Se le reportaron al usuario y **no se han corregido**: el usuario no lo pidió y su mod no está en este repo.
- Falta la `}` final en `decisions/somaliland_shago.txt` y en `decisions/zulu_expancionshago.txt`.
- `00_VSM_countries.csv`:
  - `GEL_reactionary` y `MAJ_reactionary` tienen un `Geledi;` sobrante que desplaza columnas;
  - en `SOM_ADJ` la columna Spanish dice "Somalisch";
  - `SOM` en inglés dice "Somaliland".
- `00_VSM_decisions.csv`: textos entre comillas con `;` dentro (el juego no interpreta comillas) y ninguna fila tiene la `x` final.
- Warsangali (WRL) usa los partidos `MAJ_*`, y Somalia arranca con `ruling_party = SOM_socialist` siendo monarquía absoluta.
- Erratas en los textos en español ("Tecnoligias", "modernizal", "Formameros", "Uncivilizef").
