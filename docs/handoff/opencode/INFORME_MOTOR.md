# Informe — Corte vertical del motor de esquemas (`opencode/it4-motor`)

Agente A de la iteración 4 con alcance reducido: contrato de `docs/diseno/wizard.md` §10 e
implementación punta a punta de `government` y `unit` (ENCARGO_MOTOR.md).

## Fase 0 — Orientación

### Entorno

- **Sistema.** Linux (contenedor), fecha 2026-10-28.
- **Rama.** `opencode/it4-motor`, creada desde `claude/keen-fermi-nw8itc` (sin cambios locales).
- **Python.**
  - Del sistema: 3.14.7 (PRUEBAS.md avisa de no usarlo: «nadie ha pasado la batería con él»).
  - Entorno de trabajo: `.venv/` con Python **3.12.13**, PySide6 6.11.2, numpy y Pillow
    (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`). Todo lo que sigue usa
    `.venv/bin/python`. Python 3.10 existe (`~/.local/bin/python3.10`, 3.10.20) pero sin dependencias;
    se preparará en la fase 4 para la doble batería.
- **Corpus.** Disponible fuera del repositorio (no se sube nada de Paradox):
  - juego vanilla: `~/Documentos/VIIMOD_EDITOR/Victoria.II.v3.04.Inclu.ALL.DLC` (con `map/default.map`,
    `common/governments.txt` y las 21 unidades de `units/`);
  - copia del mod grande (VSM / ShagoMod): `~/Documentos/VIIMOD_EDITOR/VictoriaShagoMod_for testing
    purposes (1)/` (raíz de corpus con `VSM/` y `VSM.mod`).
  - Se usarán con `VIC2_GAME` y `VIC2_CORPUS` tal como pide PRUEBAS.md §4; las pruebas de corpus solo
    trabajan sobre copias temporales (`tests/_corpus.py`).

### Línea base

- **Batería de partida** (antes de tocar nada), con el venv de Python 3.12.13: **1498 pruebas,
  `FAILED (failures=4, skipped=32)`**; los 4 fallos son 3 pruebas de disposición de interfaz:
  - `test_ui_palette.BannerTests.test_it_folds_at_1100_px_and_shows_everything_at_1920` (es y en, cuenta doble);
  - `test_ui_smoke.MainWindowTests.test_rail_is_a_column_with_room_and_a_strip_when_narrow`.
  Con Python 3.14.7 del sistema el resultado es el mismo (mismos 3 fallos).
- **Diagnóstico.** Son exactamente los fallos que PRUEBAS.md §5 declara como «fallos conocidos que no
  son tuyos»: miden que un texto «cabe» con las fuentes DejaVu del sistema; en este entorno las
  familias serif del tema no están (o gana otra, p. ej. Noto Serif, antes que DejaVu Serif) y las
  métricas difieren. No tocan `core/` ni el motor de esquemas. Se anotan y **no se darán por buenas**
  (Claude las pasa en su entorno de referencia): la línea base a vigilar en las fases siguientes es
  «1495 verdes + estos 3 fallos de disposición + 32 omitidas», y toda prueba nueva debe estar en verde.
- Las omitidas son 31 de corpus + 1 de empaquetado (PRUEBAS.md §3); con corpus quedarán menos.

### Lectura realizada

- `AGENTS.md`, `REGLAS.md` y `PRUEBAS.md` enteros; `ENCARGO.md` (tabla «Qué ya existe y debes usar»).
- `docs/diseno/wizard.md`: §2 (H16, H18), §3, §10 entera, §14.4/§14.11/§14.12, §19.3, §22 (iteración 4).
- `ARCHITECTURE.md` §2.2–2.7.
- Código real: `core/clausewitz/nodes.py` entero (API de edición sin pérdidas: `Block.set/append/
  insert_before/insert_after/remove_entry/move`, `Entry`, `Scalar`), `core/project/workspace.py`
  entero (`transaction`, `open`, `create`, `touch`, `delete`, `undo`, `save`), `core/validate/fixes.py`
  hasta `_register_tag` (patrón bytes efectivos → `replace_text` en una transacción), más la API de
  `core/locsync.py` (`LocSync.ensure/rename/delete/target_file`) y `core/index/index.py`
  (`SymbolIndex.refs_to/exists/get/attrs`).

### Notas que condicionan el trabajo

- `history.py` y `recipes.py` quedan solo como contrato (firmas de §10 que lanzan
  `NotImplementedError`); ni `government` ni `unit` los necesitan.
- `tests/_minigame.py` ya trae `governments.txt`, `rebel_types.txt` y `units/{infantry,frigate}.txt`
  (fixtures sintéticos inventados); los criterios 1, 2 y 4 usan el corpus real sobre copias.
- El corpus real gana sobre §2/§14 en caso de conflicto; cualquier desviación se anota aquí.

## Fases siguientes

(Pendientes: se añaden las entradas al cerrar cada fase.)
