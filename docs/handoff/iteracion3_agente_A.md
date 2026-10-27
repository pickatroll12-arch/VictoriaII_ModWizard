# Iteración 3 — Agente A: índice de símbolos, reglas del juego y validación con línea base

Eres el agente A de la iteración 3 de Victoria II Mod Studio. El orquestador ya hizo el commit de contrato (paso 0 de
`docs/diseno/wizard.md` §20). Tú implementas el núcleo; el agente B hace a la vez `core/locsync.py` y la interfaz
contra el mismo contrato. Trabajáis en copias separadas del repositorio y el orquestador integra al final.

## Lee antes de empezar

1. `CONTINUAR_EN_CLAUDE_CODE.md` §2 y §3 (decisiones vigentes y lo que ya existe) y §4 (entorno y corpus).
2. `docs/diseno/wizard.md`:
   - §2: hechos del corpus H1–H25, sobre todo H4–H6, H11–H21 y H23;
   - §3 (invariantes I1–I12), §4 (reglas de dependencia y de escritura), §5.2 (reglas de carga);
   - §7 (índice), §9 (reglas del juego), §11 y §11.1 (validación, SimpleFix y explicador), §19;
   - §22, iteración 3 (entregables y **criterios de aceptación 1 a 5**).
3. El contrato que vas a implementar (docstrings incluidos): `src/vic2studio/core/index/`,
   `src/vic2studio/core/rules/`, `src/vic2studio/core/lua_defines.py` y `src/vic2studio/core/validate/`.
4. Para apoyarte: `core/vfs/` (`VfsSnapshot`, `LayerKind`, `rules.rule_for` y sus `LoadMode`), `core/project/`
   (`Workspace.transaction`, `open`, `touch`, `replace_text`, `delete`, `changeset`, `codecs.codec_for`), el parser
   de `core/clausewitz/` (`parse`, `Block`, `Entry`, `to_source`), `core/csvloc/` (`parse_csv`, `LocalisationDB`,
   incluido el nuevo `from_entries`) y `core/modcheck.py`.

## Tus archivos (solo estos)

- `src/vic2studio/core/index/**`: `index.py`, `builder.py`, `cache.py` y `extractors/*.py`. `model.py` ya está;
  puedes ampliarlo de forma compatible.
- `src/vic2studio/core/rules/**` y `src/vic2studio/core/lua_defines.py`.
- `src/vic2studio/core/validate/**`, con `rules/*.py` y `texts/issues.{es,en}.json`.
- `src/vic2studio/core/modcheck.py` y `src/vic2studio/core/project/codecs.py` (solo para registrar un códec LUA de
  `DocKind.LUA` sobre `LuaDefines`, si lo necesitas).
- `tests/_minigame.py` (eres su único dueño en esta iteración), `tests/_corpus.py`, `tests/test_arch_writes.py` y
  los nuevos `tests/test_index_*.py`, `tests/test_validate_*.py`, `tests/test_rules_*.py` y
  `tests/test_lua_defines.py`.

No toques nada de `ui/`, `i18n/`, `core/locsync.py`, `core/csvloc/`, `tools/` ni las pruebas de interfaz: son de B.
Si necesitas un cambio en un archivo ajeno, descríbelo en tu informe final y no lo hagas.

## Qué entregar

1. **Índice** (§7).
   - `SymbolIndex` con la combinación por regla de carga que describe su docstring.
   - `build_index` con caché JSON-lines comprimido por capa (`FactsCache`, nunca pickle) e índice incremental
     (`apply`).
   - Extractores para todos los tipos `KIND_*` de `core/index/model.py`, con sus referencias (`SymbolRef`).
     Las referencias que hacen falta para las reglas de abajo:
     - en `history/countries`: `primary_culture`, `culture`, `religion`, `government`, `nationalvalue`,
       `ruling_party`, `capital`, tecnologías, invenciones y reformas;
     - en `history/provinces`: `owner`, `controller`, `add_core`, `trade_goods`, culturas y religiones de los
       POPs;
     - en `common/countries.txt`, los archivos de país;
     - en los eventos, `country_event`/`province_event` con id;
     - en los `.gfx`, la textura de cada sprite.
   - Parsea cada archivo una sola vez aunque lo procesen varios extractores.
2. **Reglas del juego** (§9).
   - `GameRules.from_snapshot`, que lee `defines.lua` (con `LuaDefines`), `bookmarks.txt`, `default.map`, la
     cabecera de `provinces.bmp`, `issues.txt` y `governments.txt`.
   - `ids.py`, `names.py` y `colors.py`.
   - `LuaDefines`, sin pérdidas: `to_bytes(from_bytes(b)) == b`.
3. **Validación** (§11).
   - `Validator`, `build_context`, `game_only_snapshot`, `compute_baseline` y `BaselineCache`: caché fuera del
     mod con `core.appdirs`, a través de `core.fileio`.
   - Las familias de reglas `syntax` (lo que hoy hace `modcheck.check_file`, sobre los bytes del contexto),
     `files`, `descriptor`, `countries`, `provinces`, `localisation`, `events` y `decisions`.
   - Los códigos del catálogo de §11 que aplican a esas familias. Textos ES/EN de cada `issue.<código>`, de cada
     `fix.<clave>` y del explicador (`explain.*`).
   - Una regla que lanza da `check_failed` y no aborta la validación.
4. **SimpleFix** (§11.1). `register_tag`, que inserta justo antes de `dynamic_tags`, delante de los comentarios que
   lo preceden (D7, H11). Además `convert_to_cp1252`, `add_closing_brace`, `restore_vanilla_loc_rows` y
   `trash_identical_copies`. En todos:
   - `plan` deja el proyecto idéntico, pila de deshacer incluida;
   - `apply` es una transacción deshacible en un paso.
5. **Explicador** (§11.1). `explain` para cada código, con la pila de capas, la línea real de cada una y su
   veredicto. Uno genérico para los códigos sin explicador propio.
6. **Pruebas**:
   - Sin corpus: el minijuego ampliado. Añade ahí datos inventados de culturas, religiones, gobiernos,
     ideologías, `issues.txt`, tecnologías, invenciones, bienes, unidades, `bookmarks.txt`, `defines.lua`,
     `map/definition.csv`, `default.map`, `region.txt`, `continent.txt`, un `provinces.bmp` diminuto y sprites
     `.gfx`. Prueba cada extractor, cada regla, la línea base, cada arreglo y el explicador.
   - Con corpus (`skipUnless(VIC2_CORPUS)` vía `tests/_corpus.py`): los **criterios 1 a 5 de la iteración 3**.
     Recuentos exactos; menos de 6 s en frío y menos de 1 s desde la caché; reprocesar solo el archivo cambiado.
     Validación exacta de VSM sobre vanilla (`/home/user/corpus/vanilla` y `/home/user/corpus/ShagoMod/VSM`); los
     heredados de vanilla; «Registrar SIL» con su diff de 1 línea y Ctrl+Z.
   - Si una cifra de los criterios no cuadra con el corpus real, no ajustes el código para forzarla: mídela,
     explica la diferencia y deja la cifra real en la prueba con un comentario.
   - Comprueba con mutaciones que tus pruebas detectan los fallos importantes (deshaz un arreglo, mira que algo
     falle, restáuralo).

## Reglas del proyecto (obligatorias)

- Identificadores en inglés; docstrings y comentarios en español, concisos. Compatible con Python 3.10.
  `core` nunca importa PySide6.
- **Escrituras.** Solo `core/fileio.py` escribe en crudo. `tests/test_arch_writes.py` lo comprueba con un
  recorrido AST.
  - La caché del índice y la de la línea base escriben fuera del mod (rutas de `core/appdirs.py`) a través de
    `fileio`. Añádelas a la lista permitida de esa prueba con su justificación.
  - Validar e indexar nunca escriben en el mod (I4).
- **Hilos (I12).** Los extractores y las reglas reciben bytes o instantáneas, nunca el CST vivo del `Workspace`.
- **Datos de Paradox.** Nunca subas datos de Paradox al repositorio; los del minijuego son inventados.
  `test_no_paradox_data` lo vigila.
- **Pruebas:**
  - cada arreglo de un fallo lleva su prueba de regresión;
  - antes de terminar, pasa la batería entera con
    `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests` desde la raíz, sin corpus y con
    `VIC2_CORPUS="/home/user/corpus/vanilla:/home/user/corpus/Plantilla Mod:/home/user/corpus/ShagoMod"`;
  - si te da tiempo, también con `/tmp/py310/bin/python` (Python 3.10 + PySide6 6.11.3).
- **Carga compartida.** El agente B está pasando pruebas a la vez en la misma máquina, así que las pruebas de
  latencia (las que miden huecos del hilo de la interfaz) pueden fallar por la carga. Repítelas solas antes de
  darlas por rotas.
- **Contrato.** Puedes ampliarlo (métodos o campos nuevos con valor por defecto), pero no cambies las firmas
  existentes: B las está usando. Anota cada ampliación en tu informe.

## Al terminar

- Haz commit en tu copia (worktree), en commits con mensaje en español que resuma el cambio y sus pruebas.
  **No hagas push.**
- Tu respuesta final es un informe para el orquestador:
  - qué está hecho y qué no;
  - las cifras reales del corpus frente a las de los criterios;
  - las ampliaciones del contrato;
  - los resultados de las baterías;
  - lo que B o el orquestador necesitan saber para integrar.
