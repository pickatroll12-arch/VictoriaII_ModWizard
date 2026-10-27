# Tareas para Gemini (ayuda en paralelo)

> **Estado (27-10-2026): las tres entregadas e integradas.** Gemini las subió como `gemini/g1`, `gemini/g2` y
> `gemini/g3`, y el usuario las fusionó en `main` (PR #7, #8 y #9). Claude las revisó: mutaciones propias
> detectadas (8 de 8), `find_unencodable` sin discrepancias contra una referencia en 28 000 textos aleatorios con
> 7 codificaciones y 12 veces más rápida que antes, pruebas de control más estrictas y batería completa con el
> corpus real y con Python 3.13, 3.10 y PySide6 6.5.0 (999 OK). Única desviación: `DescriptorFieldError` admite
> ahora un `params` posicional (compatible con todos los llamadores). Claude completó los dos errores de
> `core/vfs` que la tarea G3 dejaba para él. Este documento queda como modelo de encargo.

Este documento reparte trabajo de **Victoria II Mod Studio** con otro asistente mientras Claude Code cierra la
revisión adversarial de la iteración 2. Las tres tareas son independientes entre sí y de lo que Claude está
cambiando ahora. Cada una dice qué tocar, qué no tocar, cómo probar y qué entregar. Léelas enteras antes de
empezar: los requisitos de las pruebas son tan obligatorios como los del código.

## Contexto mínimo

- Repositorio: `pickatroll12-arch/VictoriaII_ModWizard`, rama de trabajo `claude/keen-fermi-nw8itc`. Aplicación
  de escritorio en **Python 3.10+ y PySide6** para crear mods de Victoria II (motor Clausewitz).
- Lee antes `CONTINUAR_EN_CLAUDE_CODE.md` §2 (decisiones y convenciones) y, si hace falta, `ARCHITECTURE.md`.
- `src/vic2studio/core/` es Python puro: **nunca** importa PySide6. La interfaz está en `src/vic2studio/ui/`.

## Reglas comunes (obligatorias)

1. **Convenciones.** Identificadores en inglés; docstrings y comentarios en español, concisos y en el mismo
   estilo que el código de alrededor. Código compatible con **Python 3.10** (nada de `TestCase.enterContext`,
   `tomllib`, `ExceptionGroup`, `typing.Self`…) y con la API de **Qt 6.5**. Pruebas con `unittest`. Líneas de
   120 caracteres como máximo.
2. **Cómo empieza un archivo de pruebas.** Copia el preámbulo de las pruebas que ya existen (por ejemplo
   `tests/test_encoding.py` o `tests/test_ui_counts.py`):
   - `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))` antes de importar `vic2studio`;
   - si el archivo importa algo de `vic2studio.ui` o de PySide6, `import _qt` **antes** (pone la plataforma
     `offscreen` y aísla preferencias y carpetas de datos);
   - los ayudantes de `tests/` se importan por su nombre (`from _corpus import vanilla_root`), nunca como
     `tests._corpus`: `tests/` no es un paquete.
   Cada archivo nuevo tiene que pasar **de las dos maneras**: con la batería entera desde la raíz y solo, desde
   `tests/`:
   ```bash
   QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
   cd tests && QT_QPA_PLATFORM=offscreen python3 -m unittest test_<tu_archivo>
   ```
3. **Escrituras.** Solo `src/vic2studio/core/fileio.py` escribe archivos en crudo (`tests/test_arch_writes.py` lo
   comprueba). Las pruebas escriben en carpetas temporales.
4. **Datos de Paradox.** Nunca copies al repositorio líneas ni archivos del juego (ni en código, ni en pruebas, ni
   en documentos). El corpus vive fuera del repositorio.
5. **Prueba de regresión.** Cada arreglo lleva una prueba que **falla sin el arreglo** y pasa con él. Compruébalo
   deshaciendo el arreglo (mutación) y di en la entrega qué deshiciste y qué prueba falló.
6. **Datos realistas.** Las pruebas construyen los objetos como los construye el código de verdad (rutas
   `VPath.of(...)`, `Issue` salidos de `descriptor_problems`, `SaveProblem` del núcleo…), no con clases de
   imitación definidas en la prueba: un doble de prueba puede pasar donde el objeto real falla.
7. **Batería completa** antes de entregar (regla 2). Hoy da 978 pruebas OK (4 omitidas sin corpus). Con el corpus
   (variable `VIC2_CORPUS`, rutas separadas por `:`; en Windows `;`), 978 sin omitidas. El corpus está en la
   release `recursos-v1` del repositorio; cómo descomprimirlo **fuera del repositorio** lo explica
   `CONTINUAR_EN_CLAUDE_CODE.md` §4, «Corpus». Las pruebas de «latido» miden pausas de la interfaz: en una
   máquina cargada pueden fallar; repítelas solas antes de darlas por rotas.
8. **No toques** estos archivos, que Claude está cambiando ahora: `src/vic2studio/core/vfs/**`,
   `src/vic2studio/core/project/journal.py`, `recovery.py`, `project.py`, `src/vic2studio/ui/session.py`,
   `src/vic2studio/ui/main_window.py`, `tests/test_arch_writes.py` y `tests/_fake_project.py`. Si una tarea te
   obliga a tocarlos, para y dilo en la entrega.
9. **Entrega.** Un parche por tarea contra la punta de la rama `claude/keen-fermi-nw8itc` (`git format-patch` o
   `git diff`, con los archivos nuevos incluidos), o una rama `gemini/<tarea>` si puedes empujar. Añade un
   resumen en español: qué cambiaste, qué mutaciones hiciste y qué prueba falló con cada una, las medidas que
   pide la tarea y el resultado de la batería (de las dos maneras de la regla 2). Claude lo integrará, lo revisará
   de forma adversarial y pasará la batería con Python 3.13, 3.10 y PySide6 6.5.0, también con el corpus.

---

## G1. Prueba «sin datos de Paradox» (wizard.md §19.5)

**Por qué.** Es una regla del proyecto (§2 del traspaso) que hoy no comprueba ninguna prueba automática.

**Qué hacer.** Un archivo nuevo, `tests/test_no_paradox_data.py`, con dos pruebas:

- **Sin corpus:** `tests/fixtures/` solo contiene rutas permitidas. Hoy son las de `tests/fixtures/shago_mod_min/`
  (la muestra del mod del usuario, con archivos de país sintéticos). Enumera la lista permitida en la prueba
  (por carpetas o patrones), de modo que un archivo nuevo en `tests/fixtures/` fuera de ella haga fallar la prueba
  con un mensaje que diga qué archivo es.
- **Con corpus** (`skipTest` si no hay juego base; usa `vanilla_root()` de `tests/_corpus.py`): ninguna línea de
  **40 o más caracteres** de los archivos de texto de vanilla (`.txt`, `.csv`, `.gui`, `.gfx`, `.lua`, `.asset`,
  `.sfx`, `.map`, `.fx`, `.fnt`) aparece en **ningún archivo de texto** de `src/`, `tests/` ni `docs/`: también
  `.py`, `.md`, `.json`, `.qss` y cualquier otro que no sea binario (salta imágenes, `.pyc`, `__pycache__` y
  cualquier archivo con bytes NUL). Un `.md` o un `.py` es justo donde acabaría una línea copiada.
  Decodifica cada archivo detectando su codificación con `vic2studio.core.encoding.decode_bytes` (vanilla y la
  muestra están en cp1252; el código y los documentos, en UTF-8). Normaliza antes de comparar: quita espacios a
  los lados y junta los espacios internos. **Ignora las asignaciones simples «clave = palabra»** del vocabulario
  del juego (p. ej. `citizenship_policy = limited_citizenship`, que aparece en cualquier archivo de país): sin eso
  la prueba daría falsos positivos con la muestra sintética. Usa un `set` (o un `dict` línea → archivo de origen,
  para el mensaje) de forma que tarde pocos segundos con ~9 000 archivos. Comprueba también que vanilla aportó
  líneas de verdad (más de mil), para que una ruta equivocada no haga pasar la prueba en vacío.
- Si con el corpus encuentras coincidencias reales en el repositorio, **no las metas en una lista blanca**: dalas
  en la entrega (archivo, línea y de qué archivo de vanilla viene) para que se decida qué hacer.

**Hecho cuando:** las dos pruebas pasan (la segunda, con corpus) y las mutaciones lo demuestran: copiar a un `.md`
de `docs/` de una copia del repositorio una línea larga de un archivo de vanilla hace fallar la segunda, y un
archivo de más en `tests/fixtures/` hace fallar la primera. Da en la entrega cuántas líneas de vanilla se buscan
y cuánto tarda.

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
mira cómo lo hace y no dupliques reglas distintas). `\r\n` cuenta como **un** salto y dos `\r` seguidos, como
dos. Las columnas empiezan en 1 tras el salto.

**Rendimiento (obligatorio y medido).** `find_unencodable` recorre documentos enteros de varios MB cuando un
guardado falla por un carácter imposible. Tu versión **no puede ser más lenta que la actual**. Mídelo y da las dos
cifras en la entrega, con un texto de unos 22 MB así:

```python
line = "province_id = { owner = ENG controller = ENG core = ENG añadido = sí }\r\n"
text = line * 300_000 + "c = Ω\r\n"
```

(La versión actual tarda alrededor de 1 s en la máquina de la nube.) Recorrer el texto carácter a carácter en
Python es lo que la hace lenta; hay maneras de dejar ese recorrido a funciones escritas en C.

**Pruebas:** en un archivo nuevo, `tests/test_cr_line_counts.py` (preámbulo de la regla 2, con `import _qt` porque
importa `project_page`):
- `find_unencodable` con LF, CRLF, solo CR, mezcla y `\r\r` (línea y columna exactas);
- que la línea que da coincide con la que da el parser para la misma entrada (`parse(texto)`: la entrada tiene
  `.line`), con un texto que mezcle los tres saltos;
- una comparación con una implementación de referencia sencilla sobre miles de textos aleatorios (con semilla
  fija) de saltos y caracteres mezclados;
- `encode_text` lanzando `UnencodableTextError` con la posición correcta, también en su `str()`;
- `gather_facts` (es una función: mira cómo la usa `tests/test_ui_counts.py`) con solo CR, CRLF, LF, vacío y
  `\r\r`.

**Hecho cuando:** las pruebas nuevas fallan sin el arreglo y pasan con él, la medida de rendimiento lo cumple y la
batería completa sigue en verde.

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

`EditError`, `InvalidFieldError` y `WrongThreadError` sí se recuperan bien. **`FileChangedError` no lanza, pero
su copia no es igual al original**: no des una clase por buena porque `pickle.loads` no falle.

**Qué hacer.** El cambio más pequeño en cada clase (un `__reduce__` o pasar los argumentos a
`super().__init__`), sin cambiar su interfaz pública, sus mensajes (`message(lang)`), lo que vale `str(error)` ni,
en las dataclasses, su `repr()`. Un `mappingproxy` no se puede serializar: que viaje como `dict` y que la copia
vuelva a tener un `mappingproxy` si el original lo tenía.

**Pruebas:** un archivo nuevo, `tests/test_pickle_errors.py`, con **todas** las clases de la tabla más las cuatro
del párrafo de debajo (para que las que funcionan no dejen de hacerlo), construidas con datos reales (regla 6;
mira cómo las crean el núcleo y las pruebas: `grep -rn "SourceMismatchError(" tests src`). Por ejemplo,
`DescriptorProblemsError` con los `Issue` que devuelve `descriptor_problems(DescriptorSpec("", "CON", "x"), None,
creating=True)`, `DescriptorWriteError` con un `SaveProblem` real, `SaveProblem` con los `args` por defecto y con
`args` propios, uno con `rel=DESCRIPTOR_REL`, y `ReadOnlyDocumentError` con un `VPath`. La copia debe tener el
mismo tipo, el mismo `str()`, los mismos `message("es")` y `message("en")` cuando existan, los mismos atributos
públicos y, si es una dataclass, el mismo `repr()`; las rutas `VPath` siguen siendo `VPath`.

**Hecho cuando:** la prueba nueva pasa con todas las clases salvo las dos de `core/vfs` (que se marcan con
`expectedFailure` y un comentario que diga que quedan para Claude), falla sin los arreglos y la batería completa
sigue en verde.
