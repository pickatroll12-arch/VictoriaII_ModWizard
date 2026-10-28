# Cómo pasar las pruebas

`unittest` de la biblioteca estándar, sin pytest. Todas las órdenes, desde la raíz del repositorio. Las pruebas de
interfaz necesitan `QT_QPA_PLATFORM=offscreen` (sin pantalla); las de núcleo no, pero ponerlo no estorba.

## 1. Batería completa

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests          # ~7 min
```

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python -m unittest discover -s tests
```

Punto de partida (rama `claude/keen-fermi-nw8itc`, iteración 3 cerrada y alfa empaquetada): **1498 pruebas,
`OK (skipped=31)` sin corpus**. Las 31 omitidas son las de corpus. Cualquier otro resultado antes de tocar nada es un problema del
entorno (bibliotecas de Qt, versión de Python): arréglalo antes de seguir.

## 2. Las dos versiones de Python

El proyecto promete Python 3.10 y PySide6 6.5. Antes de la entrega (fase 5) pasa la batería con las dos:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python    -m unittest discover -s tests       # 3.12
QT_QPA_PLATFORM=offscreen .venv310/bin/python -m unittest discover -s tests       # 3.10
```

En las fases intermedias basta 3.12. No uses 3.14: nadie ha pasado la batería con él.

## 3. Pruebas sueltas (lo normal mientras trabajas)

Las pruebas importan sus ayudantes (`_minigame`, `_corpus`, `_qt`…) desde la carpeta `tests/`, así que hay que
ponerla en `PYTHONPATH` (o usar `discover -s tests`). La forma `python -m unittest tests.test_x` **sin**
`PYTHONPATH=tests` falla con `No module named '_corpus'`.

```bash
export PYTHONPATH=tests QT_QPA_PLATFORM=offscreen                                # Windows: $env:PYTHONPATH="tests"
.venv/bin/python -m unittest tests.test_schema_government -v                     # un archivo
.venv/bin/python -m unittest tests.test_schema_criteria.CbTests.test_my_cb -v     # una prueba
.venv/bin/python -m unittest discover -s tests -p "test_schema_*.py"              # todas las de esquemas
.venv/bin/python -m unittest tests.test_arch_writes tests.test_i18n tests.test_packaging tests.test_no_paradox_data
```

La última línea son las cuatro pruebas de reglas (REGLAS.md §2–6): pásalas cada vez que añadas un archivo (hoy:
`OK (skipped=1)` sin corpus).

Todas las pruebas empiezan con `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))` y usan
`tests/_minigame.py` para construir un juego y un mod sintéticos en una carpeta temporal. Mira
`tests/test_validate_fixes.py` (línea ~56: `Project.open(game.game_root, game.mod_root)`) y `tests/test_locsync.py`
para ver cómo se abre un `Project` sobre el minijuego, se edita, se deshace y se guarda.

Las pruebas que abren un `Project` llaman antes a `isolate_appdirs(self)` (en `tests/_layers.py`) para no escribir
en tu perfil: cópialo.

## 4. Con corpus (criterios 1, 2 y 4)

```bash
export VIC2_CORPUS="$HOME/vic2corpus/vanilla:$HOME/vic2corpus/ShagoMod"     # Windows: rutas separadas por ;
export VIC2_GAME="$HOME/vic2corpus/vanilla"                                  # opcional: el juego base
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests
```

```powershell
$env:VIC2_CORPUS="$HOME\vic2corpus\vanilla;$HOME\vic2corpus\ShagoMod"; $env:VIC2_GAME="$HOME\vic2corpus\vanilla"
```

Con corpus no debe quedar ninguna omitida por corpus. Las pruebas de corpus son **de solo lectura**: copian a una
carpeta temporal lo que vayan a abrir como proyecto. Marca las tuyas con
`@unittest.skipUnless(vanilla_root(), "sin corpus")` (de `tests/_corpus.py`).

## 5. Fallos conocidos que no son tuyos

- `test_ui_integration...test_validating_a_large_file_keeps_the_interface_responsive` mide latencia: con la máquina
  cargada (otro proceso compilando, el portátil en ahorro) a veces falla. Repítela sola; si pasa sola, no es tuya.
- Si una prueba de interfaz da un fallo de segmentación al final, repite la batería una vez. Dos veces seguidas ya
  es real: anótalo en el informe.
- Las pruebas de disposición (`test_ui_palette...test_it_folds_at_1100_px...`, `test_ui_smoke...test_rail_is_a_column...`,
  `test_ui_pages...test_the_header_of_a_utf16_file_fits` y otras que comprueban que un texto «cabe») miden con las
  fuentes DejaVu instaladas en el sistema (`fonts-dejavu`). Con otras fuentes pueden fallar antes de tocar nada, y
  también **dejar de fallar** cuando tu cambio sí estropea la disposición. Si tu equipo no da la línea base limpia,
  anota qué falla antes de empezar y no des por buena una prueba de disposición: Claude las pasa en el entorno de
  referencia.
- `test_tasks...test_garbage_frozen_with_a_large_result_is_collected_once_it_is_released` puede fallar en algunas
  combinaciones de Python 3.12 y PySide6 6.12 instaladas con pip: si falla igual en la línea base, no es tuyo.

## 6. Mutantes a mano (fase 5)

Una prueba que no falla cuando el código está mal no prueba nada. Para cada pieza importante:

1. Rompe el código a propósito con un cambio pequeño y realista (invertir una condición, insertar al principio en
   vez de al final, abrir dos transacciones, reescribir el bloque entero, saltarse una clave de localización).
2. Pasa solo las pruebas de esa pieza. **Alguna debe fallar.**
3. Deshaz el cambio (`git checkout -- <archivo>`) y comprueba que vuelven a pasar.
4. Si el mutante sobrevive, añade la prueba que lo mata.

Apunta cada mutante en `INFORME.md`: archivo, cambio, qué prueba lo mató (o qué prueba añadiste). Nunca hagas
commit con un mutante dentro: `git diff` antes de cada commit.
