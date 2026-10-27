# Tareas para Grok (ayuda en paralelo)

Este documento reparte trabajo de **Victoria II Mod Studio** con otro asistente mientras Claude Code cierra la
revisión adversarial de la iteración 2. Las tres tareas son independientes entre sí y de lo que Claude está
cambiando ahora. Cada una dice qué tocar, qué no tocar, cómo probar y qué entregar.

## Contexto mínimo

- Repositorio: `pickatroll12-arch/VictoriaII_ModWizard`, rama de trabajo `claude/keen-fermi-nw8itc`. Aplicación
  de escritorio en **Python 3.10+ y PySide6** para crear mods de Victoria II (motor Clausewitz).
- Lee antes `CONTINUAR_EN_CLAUDE_CODE.md` §2 (decisiones y convenciones) y, si hace falta, `ARCHITECTURE.md`.
- `src/vic2studio/core/` es Python puro: **nunca** importa PySide6. La interfaz está en `src/vic2studio/ui/`.

## Reglas comunes (obligatorias)

1. **Convenciones.** Identificadores en inglés; docstrings y comentarios en español, concisos y en el mismo
   estilo que el código de alrededor. Código compatible con **Python 3.10** (nada de `TestCase.enterContext`,
   `tomllib`, `ExceptionGroup`, `typing.Self`…) y con la API de **Qt 6.5**. Pruebas con `unittest`.
2. **Escrituras.** Solo `src/vic2studio/core/fileio.py` escribe archivos en crudo (`tests/test_arch_writes.py` lo
   comprueba). Las pruebas escriben en carpetas temporales.
3. **Datos de Paradox.** Nunca copies al repositorio líneas ni archivos del juego (ni en código, ni en pruebas, ni
   en documentos). El corpus vive fuera del repositorio.
4. **Prueba de regresión.** Cada arreglo lleva una prueba que **falla sin el arreglo** y pasa con él. Compruébalo
   deshaciendo el arreglo (mutación) y dilo en la entrega.
5. **Batería completa** antes de entregar, desde la raíz del repositorio:
   ```bash
   QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
   ```
   Hoy da 978 pruebas OK (4 omitidas sin corpus). Con el corpus (variable `VIC2_CORPUS`, rutas separadas por
   `:`; en Windows `;`), 978 sin omitidas. El corpus está en la release `recursos-v1` del repositorio; cómo
   descomprimirlo **fuera del repositorio** lo explica `CONTINUAR_EN_CLAUDE_CODE.md` §4, «Corpus». Las pruebas de «latido» miden pausas de la interfaz: en una máquina
   cargada pueden fallar; repítelas solas antes de darlas por rotas.
6. **No toques** estos archivos, que Claude está cambiando ahora: `src/vic2studio/core/vfs/**`,
   `src/vic2studio/core/project/journal.py`, `recovery.py`, `project.py`, `src/vic2studio/ui/session.py`,
   `src/vic2studio/ui/main_window.py`, `tests/test_arch_writes.py` y `tests/_fake_project.py`. Si una tarea te
   obliga a tocarlos, para y dilo en la entrega.
7. **Entrega.** Un parche por tarea contra la punta de la rama `claude/keen-fermi-nw8itc` (`git format-patch` o
   `git diff`), o una rama `grok/<tarea>` si puedes empujar. Añade un resumen en español: qué cambiaste, qué
   prueba falla sin el arreglo y el resultado de la batería. Claude lo integrará, lo revisará de forma adversarial
   y pasará la batería con Python 3.13, 3.10 y PySide6 6.5.0.

---

## G1. Prueba «sin datos de Paradox» (wizard.md §19.5)

**Por qué.** Es una regla del proyecto (§2 del traspaso) que hoy no comprueba ninguna prueba automática.

**Qué hacer.** Un archivo nuevo, `tests/test_no_paradox_data.py`, con dos pruebas:

- **Sin corpus:** `tests/fixtures/` solo contiene rutas permitidas. Hoy son las de `tests/fixtures/shago_mod_min/`
  (la muestra del mod del usuario, con archivos de país sintéticos). Enumera la lista permitida en la prueba
  (por carpetas o patrones), de modo que un archivo nuevo en `tests/fixtures/` fuera de ella haga fallar la prueba
  con un mensaje que diga qué archivo es.
- **Con corpus** (`skipTest` si no hay juego base; usa `_corpus.vanilla_root()` de `tests/_corpus.py`): ninguna
  línea de **40 o más caracteres** de los archivos de texto de vanilla (`.txt`, `.csv`, `.gui`, `.gfx`, `.lua`,
  `.asset`, `.sfx`, `.map`; decodifica en cp1252 con `errors="replace"`) aparece en los archivos de texto de
  `src/`, `tests/` ni `docs/` (no mires imágenes ni binarios). Normaliza antes de comparar: quita espacios a los
  lados, junta los espacios internos y descarta los comentarios de una línea vacíos. **Ignora las asignaciones
  simples «clave = palabra»** del vocabulario del juego (p. ej. `citizenship_policy = limited_citizenship`, que
  aparece en cualquier archivo de país): sin eso la prueba daría falsos positivos con la muestra sintética. Usa un
  `set` de líneas para que tarde pocos segundos con ~9 000 archivos.
- Si con el corpus encuentras coincidencias reales en el repositorio, **no las metas en una lista blanca**: dalas
  en la entrega (archivo, línea y de qué archivo de vanilla viene) para que se decida qué hacer.

**Hecho cuando:** las dos pruebas pasan (la segunda, con corpus) y una mutación lo demuestra (p. ej. copiar a una
carpeta temporal del repositorio una línea larga de un archivo de vanilla hace fallar la segunda, y un archivo de
más en `tests/fixtures/` hace fallar la primera).

---

## G2. Líneas mal contadas en archivos con saltos solo CR

**Por qué.** Algunos archivos de vanilla usan solo `\r` como salto de línea (`map/region_sea.txt`). El parser ya
los cuenta bien, pero dos sitios cuentan las líneas solo por `\n` (riesgo de `ARCHITECTURE.md` §6.3, «Línea mal
contada en archivos solo CR»):

- `src/vic2studio/core/encoding.py`, `find_unencodable`: con `a = 1`, `b = 2` y `c = Ω` separados por CR da
  línea 1 y columna 17 en vez de línea 3 y columna 5. Ese resultado llega a `UnencodableTextError`
  (`encode_text`, `write_file`) y al problema de guardado `save_unencodable`.
- `src/vic2studio/ui/pages/project_page.py`, `gather_facts` (`facts.lines`): un archivo de 3 líneas solo CR sale
  con 1.

**Qué hacer.** Contar como salto `\r\n`, `\n` y un `\r` suelto, igual que el lexer (`core/clausewitz/lexer.py`;
mira cómo lo hace y no dupliques reglas distintas). `\r\n` cuenta como **un** salto. Las columnas empiezan en 1
tras el salto. Cuida el rendimiento: `find_unencodable` recorre textos de varios MB.

**Pruebas:** en un archivo nuevo, `tests/test_cr_line_counts.py`: `find_unencodable` con LF, CRLF, solo CR y
mezcla (línea y columna exactas), `encode_text` lanzando `UnencodableTextError` con la posición correcta y
`gather_facts` (es una función: mira cómo la usa `tests/test_ui_counts.py`) con 3 líneas solo CR.

**Hecho cuando:** las pruebas nuevas fallan sin el arreglo y pasan con él, y la batería completa sigue en verde.

---

## G3. Errores del núcleo que no pasan por `pickle`

**Por qué.** El taller de mapas (iteración 9, wizard.md §18.4) usará un proceso trabajador, y un error que no se
puede serializar con `pickle` no cruza de un proceso a otro. Hoy `pickle.loads(pickle.dumps(error))` falla con
(riesgo de `ARCHITECTURE.md` §6.3, «Errores de guardado que no pasan por `pickle`»):

| Clase | Archivo | Fallo actual |
|---|---|---|
| `SourceMismatchError` | `src/vic2studio/core/clausewitz/serializer.py` | su `__init__` pide 3 argumentos: `TypeError` |
| `UnencodableTextError` | `src/vic2studio/core/encoding.py` | pide 2: `TypeError` |
| `DescriptorFieldError` | `src/vic2studio/core/modfile.py` | recibe el mensaje como código: `KeyError` |
| `DescriptorProblemsError` | `src/vic2studio/core/modfile.py` | se rehace a partir de su texto: `AttributeError` |
| `DescriptorWriteError` | `src/vic2studio/core/modfile.py` | su `args` por defecto es un `mappingproxy`: `TypeError` |
| `SaveProblem` | `src/vic2studio/core/project/model.py` | igual, por el `mappingproxy` |
| `ReadOnlyDocumentError` | `src/vic2studio/core/project/workspace.py` | pide 2: `TypeError` |
| `InvalidPathError` | `src/vic2studio/core/vfs/paths.py` | pide 2: `TypeError` (**no toques este archivo**: dilo en la entrega) |
| `WriteOutsideModError` | `src/vic2studio/core/vfs/guard.py` | pide 2: `TypeError` (**no toques este archivo**: dilo en la entrega) |

`EditError`, `FileChangedError`, `InvalidFieldError` y `WrongThreadError` ya se recuperan: úsalas de modelo.

**Qué hacer.** El cambio más pequeño en cada clase (un `__reduce__` o pasar los argumentos a
`super().__init__`), sin cambiar su interfaz pública, sus mensajes (`message(lang)`) ni lo que vale `str(error)`.
Para `mappingproxy`, convierte a `dict` solo al serializar.

**Pruebas:** un archivo nuevo, `tests/test_pickle_errors.py`, que construya cada error con datos realistas (mira
cómo los crean las pruebas existentes: `grep -rn "SourceMismatchError(" tests src`), lo pase por
`pickle.dumps`/`pickle.loads` y compruebe que la copia tiene el mismo tipo, el mismo `str()`, los mismos
`message("es")` y `message("en")` cuando existan, y los mismos atributos públicos.

**Hecho cuando:** la prueba nueva pasa con todas las clases salvo las dos de `core/vfs` (que se marcan con
`expectedFailure` y un comentario que diga que quedan para Claude), falla sin los arreglos y la batería completa
sigue en verde.
