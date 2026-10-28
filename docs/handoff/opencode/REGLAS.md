# Reglas del proyecto que no se ven leyendo un archivo

Son las que han costado fallos en las iteraciones 2 y 3. Varias las comprueba una prueba (entre paréntesis): si la
rompes, la batería lo dice. Las demás las comprueba Claude al revisar tu rama.

## 1. Invariantes (wizard §3)

- **I1. Solo el mod.** Solo se escribe en `<mod>/` y en su `.mod`. Nunca en el juego base.
- **I3. Sin pérdidas.** Lo que no se edita se conserva byte a byte: comentarios, sangría, orden, comillas, `1.0`
  frente a `1`, finales de línea CRLF y la codificación cp1252. Edita el árbol (`Block.set/insert_*`), nunca
  regeneres un bloque entero. (`test_noop_save`, `test_clausewitz_edit`.)
- **I4. Leer no escribe.** Abrir, listar, validar, `Recipe.plan()` y docgen no abren nada con `create=True`, no
  llaman a `replace_*` y no guardan. (`test_validation_writes_nothing` y similares.)
- **I5. Todo es reversible.** Toda modificación va dentro de **una** `ws.transaction(...)` (o `project.edit(...)`)
  con una etiqueta de deshacer `undo.<algo>` que tenga texto ES/EN. Crear un CB con sus compañeros y sus claves es
  una sola transacción: un Ctrl+Z lo deshace entero.
- **I6. Nada desaparece.** Las claves que el esquema no conoce se conservan y se exponen como «Otros campos».
- **I7. Vista efectiva.** Lee siempre a través del `Workspace` (`ws.open`, `ws.peek`) o del `VirtualFS`, nunca del
  disco: un documento sin guardar es la verdad.
- **I11. Lo heredado no cuenta.** Si vanilla ya tiene un problema (por ejemplo `annex` en `peace_order`), no es del
  mod.
- **I12. Un CST vivo no cambia de hilo.** El `Workspace` es de un solo hilo (lanza `WrongThreadError`). A un hilo de
  fondo solo se le pasan bytes, texto o instantáneas inmutables (`vfs.snapshot()`).
- **Nunca `gc.get_objects()`** en un hilo de tareas: recorre objetos vivos de otro hilo y dio fallos
  intermitentes en la iteración 3 (`tests/test_tasks.py` explica el caso).

## 2. Quién escribe en disco (`test_arch_writes`)

Un recorrido del AST de `src/` prohíbe `open(..., "w")`, `Path.write_*`, `os.replace/remove/mkdir`, `shutil.*` y
compañía fuera de `core/fileio.py`, y las funciones de escritura de `fileio` fuera de `core/project/journal.py` y
`lock.py`. Tu código **nunca** escribe archivos: cambia documentos del `Workspace` y el guardado lo hace el diario.
Las CLI escriben en la salida estándar. Lo que deba escribir archivos de verdad (la referencia de docgen) va en
`tools/`, fuera de `src/`.

## 3. Capas e imports

- `vic2studio.core` **no importa Qt** (`test_arch_writes` lo comprueba importándolo sin PySide6).
- Sintaxis de **Python 3.10** en todo `src/` (también lo comprueba): nada de `type X = ...`, `except*` está bien
  pero no hace falta, nada de genéricos PEP 695 (`class A[T]`), nada de `typing.override`. Usa
  `from __future__ import annotations`.
- Sin dependencias nuevas: solo la biblioteca estándar, numpy, Pillow (y PySide6 fuera de `core`).
- Registro por descubrimiento (`pkgutil.iter_modules`): ninguna lista central de esquemas.

## 4. Textos (ES y EN siempre a la par)

- Docstrings y comentarios **en español**; identificadores **en inglés**. Densidad de comentarios como el código
  de alrededor: el porqué y el hecho del corpus que lo motiva (H16, H17…), no lo que el código ya dice.
- Los textos del núcleo van en `core/**/texts/<área>.<es|en>.json` (objeto plano). Los tuyos, en
  `core/schemas/texts/<kind>.{es,en}.json`. `core/texts.load_texts` los fusiona y **falla si una clave se repite
  entre archivos**: usa espacios de nombres (`schema.government.field.election`, `issue.<código>`…).
- Mismas claves en ES y EN, mismos `{marcadores}` (`test_i18n`). Nada de texto visible escrito en código.
- **Cada código de problema nuevo** necesita `issue.<código>`, `explain.title.<código>` y
  `explain.outcome.<código>` en ES y EN. El `outcome` dice **qué verá el jugador** en el juego, no qué regla se
  rompe (ver los 48 de `core/validate/texts/issues.es.json`).
- Tono: español neutro, frases cortas, sin «por favor», sin signos de exclamación, comillas «latinas».

## 5. Empaquetado (`test_packaging`)

Un archivo de textos nuevo en `core/**/texts/` entra solo en el ejecutable (lo cubre el patrón
`core/**/texts/*.json` del spec), pero `test_packaging` exige que **cada archivo de textos tenga una clave en
`SMOKE_KEYS`** de `src/vic2studio/app.py`. Por cada `<kind>.es.json` nuevo, añade una clave suya a esa tupla (es
el único cambio permitido en `app.py`).

## 6. Datos de Paradox y el corpus (`test_no_paradox_data`)

- **Nunca** subas datos del juego: ni archivos, ni fragmentos copiados de vanilla en pruebas, fixtures, textos o
  `docs/referencia/`. Los ejemplos se inventan (el minijuego es sintético). docgen documenta el esquema, no copia
  valores de vanilla.
- El corpus vive **fuera** del repositorio. Las pruebas de corpus solo leen y trabajan sobre copias en carpetas
  temporales (`tests/_corpus.copy_user_mod`).
- **Nunca abras el mod real del usuario (VSM) como proyecto**, ni dejes `.vic2studio/` dentro del corpus.

## 7. Git

- Rama **`opencode/it4-nucleo`**. Push con `git push -u origin opencode/it4-nucleo` al final de cada fase.
- **No** abras PR, no fusiones, no toques `main` ni `claude/keen-fermi-nw8itc`, no reescribas historia
  (`rebase`, `--amend` de algo ya subido, `push --force`).
- Mensajes de commit **en español**: primera línea corta en imperativo («Motor de esquemas: tipos y campos»), y
  un cuerpo que diga qué y por qué. Sin identificadores de modelo en commits, código ni documentos.
- Antes de cada commit: `git status` limpio de basura (`.venv*`, `__pycache__`, `*.bak`, nada del corpus).

## 8. Archivos que no son tuyos

Todo lo que no está en la lista de ENCARGO.md. En especial: `ui/**`, `i18n/**`, `core/validate/**`,
`core/index/**`, `core/project/**`, `core/clausewitz/**`, `tests/test_validate_*.py`, `tests/test_arch_writes.py`,
`pyproject.toml`, `packaging/**`, `.github/**`, `README.md`, `ARCHITECTURE.md`, `CONTINUAR_EN_CLAUDE_CODE.md` y
`docs/diseno/**`. Si crees que hace falta cambiar uno (un fallo, una API que falta), **no lo cambies**: anótalo en
`INFORME.md` («Peticiones para Claude») con el archivo, el cambio y el porqué, y sigue rodeándolo.
