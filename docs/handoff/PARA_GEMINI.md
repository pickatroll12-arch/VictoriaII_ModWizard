# Tareas para Gemini (ayuda en paralelo)

> **Estado (27-10-2026).**
> - **Primera tanda (G1–G3): entregada e integrada.** Gemini la subió como `gemini/g1`, `gemini/g2` y `gemini/g3`,
>   el usuario la fusionó en `main` (PR #7, #8 y #9) y Claude la revisó: 8 de 8 mutaciones detectadas,
>   `find_unencodable` 12 veces más rápida y sin discrepancias en 28 000 textos aleatorios, y la batería completa
>   en verde. Sus encargos siguen abajo como modelo.
> - **Segunda tanda (G4–G7): hecha por Claude.** La plataforma de Gemini se cayó y el usuario pidió a Claude que
>   las asumiera. Están en `claude/keen-fermi-nw8itc`, cada una con sus pruebas, corpus y mutaciones:
>   - G4 (`8c33ae6`): `core/tablecsv.py` y `core/map/definition.py`. Ida y vuelta exacta de `definition.csv`
>     (3248 ids y 56 filas sin id); 12 mutaciones, todas muertas.
>   - G5 (`e3bae3e`): `core/map/bmp.py`. Los 3 mapas de vanilla vuelven idénticos e iguales a Pillow; lee en
>     41 ms y escribe en 57 ms (Pillow, 74 ms); 11 de 11 mutaciones.
>   - G6 (`b412730` y `b973bb9`): `core/gfx/dds.py`. `colormap.dds` reescrito sale idéntico y
>     `colormap_water.dds`, con la misma cabecera y el mismo tamaño; 10 de 10 mutaciones. Pillow 10.0 y 10.1 leen
>     X8R8G8B8 como si fuera de 24 bits (corregido en 10.2); el lector propio, no.
>   - G7 (`ac3df50`): `core/gfx/flags.py`. Las 1345 banderas de 93×64 de vanilla salen idénticas; 11 de 11
>     mutaciones.
>
>   Si Gemini vuelve, sus próximas tareas serán una tercera tanda: estas cuatro ya no hay que hacerlas.

Este documento reparte trabajo de **Victoria II Mod Studio** con otro asistente. Ahora mismo Claude Code está en la
iteración 3 con dos agentes (A: índice de símbolos y validación, en `core/index`, `core/validate` y `core/rules`; B:
localización editable e interfaz, en `core/locsync.py` y `ui/`). Las tareas de la segunda tanda eran
independientes entre sí y de lo que hacen ellos. Cada una dice qué crear, cómo probar y qué entregar; quedan como
modelo de encargo, porque ya están hechas (ver el estado de arriba).

## Contexto mínimo

- Repositorio: `pickatroll12-arch/VictoriaII_ModWizard`, rama de trabajo `claude/keen-fermi-nw8itc`. Aplicación
  de escritorio en **Python 3.10+ y PySide6** para crear mods de Victoria II (motor Clausewitz).
- Lee antes `CONTINUAR_EN_CLAUDE_CODE.md` §2 (decisiones y convenciones) y, de `docs/diseno/wizard.md`, la §2 (los
  hechos del corpus H1, H4, H8, H22 y H23), la §3 (invariantes, sobre todo I3: sin pérdidas) y las secciones que
  cite cada tarea.
- `src/vic2studio/core/` es Python puro: **nunca** importa PySide6. Puede usar numpy y Pillow (dependencias del
  proyecto: `numpy>=1.24`, `Pillow>=10`).

## Reglas comunes (obligatorias)

1. **Convenciones.** Identificadores en inglés; docstrings y comentarios en español, concisos y en el mismo
   estilo que el código de alrededor (mira `src/vic2studio/core/encoding.py` o `core/vfs/model.py`). Código
   compatible con **Python 3.10** (nada de `TestCase.enterContext`, `tomllib`, `ExceptionGroup`,
   `typing.Self`…). Pruebas con `unittest`. Líneas de 120 caracteres como máximo.
2. **Cómo empieza un archivo de pruebas.** Copia el preámbulo de las pruebas que ya existen (por ejemplo
   `tests/test_encoding.py`):
   - `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))` antes de importar `vic2studio`;
   - los ayudantes de `tests/` se importan por su nombre (`from _corpus import vanilla_root`), nunca como
     `tests._corpus`: `tests/` no es un paquete;
   - ninguna de estas tareas necesita Qt: no importes `_qt` ni PySide6.

   Cada archivo nuevo tiene que pasar **de las dos maneras**: con la batería entera desde la raíz y solo, desde
   `tests/`:
   ```bash
   QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
   cd tests && python3 -m unittest test_<tu_archivo>
   ```
3. **Sin escrituras a disco.** Estos módulos convierten bytes en datos y datos en bytes: `to_bytes`/`write_*`
   **devuelven** `bytes`, nunca escriben archivos. Solo `src/vic2studio/core/fileio.py` escribe en crudo, y lo
   comprueba `tests/test_arch_writes.py`; el guardado del proyecto escribe lo que tú devuelves. Las pruebas que
   necesiten archivos usan carpetas temporales.
4. **Datos de Paradox.** Nunca copies al repositorio archivos, líneas, píxeles ni paletas del juego: ni en código,
   ni en pruebas, ni en documentos. Las pruebas construyen sus datos de forma sintética (con numpy, Pillow o bytes
   escritos a mano). El corpus vive fuera del repositorio, y las pruebas que lo leen se saltan si no está.
   `tests/test_no_paradox_data.py` vigila que ninguna línea de vanilla acabe en el repositorio.
5. **Prueba de regresión y mutaciones.** Cada comportamiento importante tiene una prueba que **falla si se
   rompe**. Compruébalo rompiéndolo a propósito (mutación) y di en la entrega qué rompiste y qué prueba falló.
6. **Datos realistas.** Prueba con los casos difíciles de verdad (anchos impares, filas con relleno, saltos de
   línea mezclados, valores raros como `223.`), no solo con el caso feliz.
7. **Ida y vuelta exacta.** Donde la tarea pide «sin pérdidas», `to_bytes(from_bytes(b)) == b` **byte a byte**
   para cualquier entrada válida, también con el corpus real. Es el invariante I3 del proyecto.
8. **Batería completa** antes de entregar (regla 2). Hoy da 1094 pruebas OK (5 omitidas sin corpus). Con el
   corpus (variable `VIC2_CORPUS`, rutas separadas por `:`; en Windows `;`), ninguna omitida. El corpus no está en el
   repositorio: pídeselo al usuario; cómo descomprimirlo **fuera del repositorio** lo explica
   `CONTINUAR_EN_CLAUDE_CODE.md` §4, «Corpus». Las pruebas de «latido» miden pausas de la interfaz: en una máquina
   cargada pueden fallar; repítelas solas antes de darlas por rotas.
9. **Archivos.** **Solo creas** los archivos que nombra tu tarea; **no modifiques ningún archivo existente**
   (tampoco `pyproject.toml`, `requirements.txt`, `tests/_corpus.py`, `tests/_minigame.py` ni
   `tests/test_arch_writes.py`). Si una tarea te obliga a tocar algo existente, para y dilo en la entrega.
10. **Entrega.** Una rama por tarea, `gemini/g4`…`gemini/g7`, creada desde la punta actual de
    `claude/keen-fermi-nw8itc`, con un pull request **contra `claude/keen-fermi-nw8itc`** (no contra `main`).
    Claude la revisará de forma adversarial y la integrará él mismo: no hace falta fusionarla. Si no puedes
    empujar, un parche por tarea (`git format-patch`, con los archivos nuevos incluidos).

    En la descripción, un resumen en español con:
    - qué hiciste;
    - qué mutaciones hiciste y qué prueba falló con cada una;
    - las medidas que pide la tarea;
    - el resultado de la batería, de las dos maneras de la regla 2, sin y con corpus.

---

## G4. Tablas `;` sin pérdidas y `definition.csv` (wizard.md §4.1, §6.1, §16.1 y H4)

**Por qué.** `map/definition.csv` (id → color de provincia) y `map/adjacencies.csv` son tablas separadas por `;`.
El Studio tiene que leerlas, cambiar una fila y escribirlas sin tocar nada más (iteración 5, editor de mapa).
El formato real es irregular:

- la cabecera `province;red;green;blue;x;x`;
- 3 248 filas con id y 56 filas sin id al final;
- valores como `1825;208;17;223.;Zouar;x`, con el `223.` que el motor lee como 223 (al estilo `atoi`);
- `adjacencies.csv` empieza con líneas de comentario `#From;To;Type;Through;Data;Comment`, `#` y `# American
  Straits`.

**Qué crear.**

1. `src/vic2studio/core/tablecsv.py`, la tabla genérica:
   - `Table.from_bytes(data)` detecta la codificación con `vic2studio.core.encoding.decode_bytes`; los archivos
     del juego están en cp1252. `Table.to_bytes()` devuelve la tabla en esa misma codificación.
   - **Sin pérdidas** (regla 7). Se conservan:
     - el salto de línea de cada fila (CRLF, LF o CR, mezclados);
     - que la última fila tenga o no salto;
     - un BOM si lo hay;
     - las filas en blanco y los comentarios `#`.
   - Cada fila (`TableRow`) tiene `line` (desde 1), `kind` (dato, comentario o en blanco), `raw` (su texto exacto,
     sin el salto), `fields` (`raw` partido por `;`) y su salto.
   - Editar:
     - `row.set(column, value)` regenera **solo esa fila**, con los demás campos tal cual;
     - `insert(index, fields)` y `append(fields)` usan el salto predominante del archivo;
     - `remove(row)`.
     - Un valor con `;` o un salto de línea lanza `ValueError` sin cambiar nada.
   - `cell_int(text) -> int | None` imita a `atoi`: espacios delante, signo opcional y dígitos; se para en el
     primer carácter que no es dígito (`"223."` → 223, `" 12abc"` → 12). Si no hay ningún dígito, None.
2. `src/vic2studio/core/map/__init__.py` (paquete) y `src/vic2studio/core/map/definition.py`, encima de
   `tablecsv`, con la API de §16.1:
   - `DefinitionRow(line, id, rgb, name, raw)` (`id` None en las filas sin id).
   - `DefinitionTable.parse(text_or_bytes) -> tuple[DefinitionTable, list[Problem]]`. `Problem` es
     `vic2studio.core.validate.model.Problem`; créalo directamente con `Severity.WARNING`.
     - Una primera fila cuyo primer campo no es un entero es la cabecera.
     - Las filas sin id se toleran.
     - Códigos de problema: `definition_bad_row` (un id con colores que no son números),
       `definition_duplicate_id` y `definition_duplicate_color`.
   - `id_of(rgb)`, `rgb_of(pid)` e `ids()`.
   - `add(pid, rgb, name)` añade `pid;r;g;b;name;x` tras la última fila con id, delante de las filas sin id.
   - `set_rgb(pid, rgb)` y `to_bytes()`, sin pérdidas en las filas no tocadas.
   - Los textos de los tres códigos, en `src/vic2studio/core/map/texts/map.es.json` y `map.en.json`, con las
     claves `issue.definition_bad_row` y demás. `core/texts.py` los carga solo.

**Pruebas:** `tests/test_tablecsv.py` y `tests/test_map_definition.py`.

- Sintéticas:
  - la ida y vuelta con saltos mezclados, sin salto final, con BOM, con comentarios y con líneas en blanco;
  - `set` de un campo cambia exactamente una línea del resultado (compáralo con `difflib`);
  - `cell_int` en todos sus casos;
  - una cabecera, filas sin id, `223.`, ids y colores repetidos;
  - `add` delante de las filas sin id.
- Con corpus (`vanilla_root()` de `tests/_corpus.py`; `skipTest` si no hay juego):
  - ida y vuelta exacta de `map/definition.csv` y `map/adjacencies.csv`;
  - 3 248 ids (del 1 al 3248) y 56 filas sin id;
  - la fila de 1825 da `(208, 17, 223)`.
- Mide cuánto tarda `parse` + `to_bytes` de `definition.csv` y dalo en la entrega.

**Hecho cuando:** todo lo anterior pasa, las mutaciones lo demuestran y la batería sigue en verde.

---

## G5. Códec BMP propio con numpy (wizard.md D11, §6.1, §16.1 y H1)

**Por qué.** El mapa del juego son BMP enormes: `map/provinces.bmp` (24 bits, 5616×2160, cabecera de 54 bytes,
36 391 736 B), y `terrain.bmp` y `rivers.bmp` (8 bits con paleta, 1 078 B de cabecera, 12 131 640 B). El editor
de mapa (iteración 5) los cambia píxel a píxel, y guardarlos tiene que reproducir el archivo exacto salvo los
píxeles tocados. Pillow no lo garantiza, así que el proyecto tiene su propio códec (D11).

**Qué crear:** `src/vic2studio/core/map/bmp.py` (y `core/map/__init__.py` si G4 aún no lo ha creado; si las dos
lo crean, que sea idéntico y vacío salvo un docstring de una línea):

- **`read_bmp(data) -> BmpImage`** para BMP sin compresión (`BI_RGB`) de 24 bits y de 8 bits con paleta, con alto
  positivo (filas de abajo arriba, lo normal) y negativo (de arriba abajo).
  - `BmpImage.pixels` es un `numpy.ndarray`: `(alto, ancho, 3)` `uint8` en orden **RGB** para 24 bits, y
    `(alto, ancho)` `uint8` con los índices de la paleta para 8 bits. `BmpImage.palette` es `(n, 4)` `uint8`, tal
    como está en el archivo (BGRA).
  - **Orden de las filas:** igual que `numpy.asarray(PIL.Image.open(...))`, es decir, la fila 0 es la de arriba
    de la imagen tal como la enseña un visor. En los mapas del juego esa fila es la `y` del motor (H1); no la
    voltees.
- **`write_bmp(img) -> bytes`** con `write_bmp(read_bmp(b)) == b` **byte a byte** (regla 7). Para eso,
  `BmpImage` guarda todo lo que no son píxeles:
  - la cabecera entera (también los campos que no se usan);
  - la paleta y el hueco que haya entre cabecera y píxeles;
  - el contenido de los bytes de relleno de cada fila (pueden no ser cero);
  - lo que haya después de los píxeles.

  Si se cambian los píxeles, se escriben en su sitio con el mismo formato.
- **`new_bmp(pixels, palette=None) -> bytes`**: un BMP nuevo y estándar. 24 bits si `pixels` es `(alto, ancho, 3)`,
  8 bits si es `(alto, ancho)` con paleta. Cabecera de 54 B (más 1 024 B de paleta en 8 bits), filas de abajo
  arriba y relleno a 4 bytes con ceros.
- **`read_bmp_header(data) -> tuple[int, int, int]`** (ancho, alto, bits por píxel), sin decodificar los píxeles.
- Un BMP que no está en esos formatos (comprimido, 32 bits, cabecera rara) lanza `BmpError(ValueError)` con un
  código (`bmp_unsupported`, `bmp_truncated`…). El error se copia bien con `pickle` (mira cómo lo hacen los
  errores de `tests/test_pickle_errors.py`).

**Rendimiento (obligatorio y medido).** `read_bmp` y `write_bmp` de `provinces.bmp` sin recorrer píxeles en
Python: `numpy.frombuffer`, recortes y `reshape`. Mídelos y compáralos con
`numpy.asarray(Image.open(path).convert("RGB"))`. No pueden tardar más del doble que Pillow. Da las cifras en la
entrega.

**Pruebas:** `tests/test_map_bmp.py`.

- Sintéticas, construidas con Pillow y a mano:
  - 24 y 8 bits;
  - anchos que obligan a rellenar (1, 2, 3, 5 y 7 píxeles);
  - alto negativo;
  - relleno con bytes distintos de cero;
  - bytes de más al final;
  - una paleta de menos de 256 colores.
- En todos esos casos: la ida y vuelta exacta y los píxeles iguales a los de Pillow.
- Una imagen **asimétrica** de prueba (un solo píxel rojo en la columna 1 de la fila 0) fija la orientación.
- Editar un píxel y escribir solo cambia sus 3 bytes (o su byte, en 8 bits).
- `new_bmp` se relee con Pillow igual.
- Con corpus:
  - ida y vuelta exacta de `provinces.bmp`, `terrain.bmp` y `rivers.bmp`;
  - sus píxeles, iguales a los de Pillow;
  - `read_bmp_header` da (5616, 2160, 24) y (5616, 2160, 8);
  - `provinces.bmp` tiene 3 275 colores distintos (H4).

**Hecho cuando:** todo lo anterior pasa, el rendimiento cumple y las mutaciones lo demuestran.

---

## G6. DDS sin comprimir: escritor y lector (wizard.md D11, §17.3, §18.5 y H8, H23)

**Por qué.** Las texturas del mapa y de la interfaz son DDS. Pillow las lee (también las comprimidas DXT1/3/5),
pero no garantiza escribirlas, así que el proyecto escribe DDS **A8R8G8B8 sin comprimir** con las mismas cabeceras
que vanilla. Valores medidos en el corpus:

| Archivo | Tamaño | `flags` | `pitchOrLinearSize` | Mips | Formato de píxel | `caps` |
|---|---|---|---|---|---|---|
| `map/terrain/colormap.dds` (1880×720) | 5 414 528 B | `0x81007` | 5 414 400 (= ancho·alto·4) | 0 | `flags` `0x41`, 32 bits, máscaras R `0xFF0000`, G `0xFF00`, B `0xFF`, A `0xFF000000` | `0x1000` |
| `map/terrain/colormap_water.dds` (936×360) | 1 796 960 B | `0xA1007` | 1 347 840 (= ancho·alto·4) | 10, hasta 1×1 | el mismo | `0x401008` |

**Qué crear:** `src/vic2studio/core/gfx/__init__.py` (paquete) y `src/vic2studio/core/gfx/dds.py`:

- **`write_dds(rgba, *, mipmaps=False) -> bytes`**:
  - `rgba` es `(alto, ancho, 4)` `uint8`. La cabecera es de 128 bytes (`"DDS "` + 124), con los campos de la
    tabla (`flags` `0x81007`, o `0xA1007` con mips, y `pitchOrLinearSize` = ancho·alto·4).
  - Los píxeles van en orden BGRA, filas de arriba abajo.
  - Con `mipmaps`, niveles hasta 1×1: cada uno es el anterior reducido a la mitad (redondeando hacia abajo, con
    un mínimo de 1) con un filtro de caja que funcione con lados impares, y `mipMapCount` dice cuántos hay.
    Compruébalo con `colormap_water`: 936×360 da 10 niveles y 1 796 960 B.
- **`read_dds(data) -> DdsImage`**: el nivel 0 en RGBA `(alto, ancho, 4)` `uint8` y la información de la cabecera
  (`DdsInfo`).
  - A8R8G8B8 y X8R8G8B8 los lee él mismo, con numpy (X8: alfa 255).
  - DXT1, DXT3 y DXT5 se los pasa a Pillow (`Image.open(BytesIO(data)).convert("RGBA")`).
  - Lo que no reconoce lanza `DdsError(ValueError)` con un código; se copia bien con `pickle`.
- **`dds_info(data) -> DdsInfo`**: ancho, alto, `flags`, `pitch`, mips, `fourcc` (o None), bits por píxel,
  máscaras y `caps`, sin decodificar nada.

**Pruebas:** `tests/test_gfx_dds.py`.

- Sintéticas:
  - `write_dds` de imágenes con lados impares y que no son potencia de dos, con y sin mips;
  - Pillow las relee **iguales** a la entrada (el nivel 0);
  - `read_dds` también;
  - el tamaño total cuadra con la suma de los niveles;
  - `dds_info` da los campos de la tabla;
  - X8R8G8B8 hecho a mano.
- Con corpus:
  - `dds_info` de `colormap.dds`, `colormap_water.dds` y `colormap_no_shadow.dds` (DXT3);
  - `write_dds(read_dds(colormap_water.dds).rgba, mipmaps=True)` tiene **el mismo tamaño y los mismos campos de
    cabecera** que el original. Di en la entrega si algún byte de la cabecera difiere, cuál y por qué.
  - `read_dds` de un DDS DXT del juego no falla y coincide con Pillow.

**Hecho cuando:** todo lo anterior pasa y las mutaciones lo demuestran.

---

## G7. Banderas TGA (wizard.md §14.2 y H22)

**Por qué.** Cada país tiene 5 banderas en `gfx/flags/`: `<TAG>.tga`, `<TAG>_communist.tga`, `_fascist`,
`_monarchy` y `_republic`. Son TGA de 32 bits, 93×64, con el origen abajo a la izquierda (descriptor `0x08`). En
vanilla, 1 038 van con RLE (tipo 10). El asistente de países (iteración 6) generará las banderas a partir de una
imagen cualquiera.

**Qué crear:** `src/vic2studio/core/gfx/flags.py` (y `core/gfx/__init__.py` si G6 aún no lo ha creado; si las
dos lo crean, que sea idéntico):

- Constantes `FLAG_SIZE = (93, 64)` y `FLAG_SUFFIXES = ("", "_communist", "_fascist", "_monarchy", "_republic")`.
- **`write_tga(rgba) -> bytes`**: TGA tipo 2, sin comprimir, de 32 bits, descriptor `0x08`, filas de abajo
  arriba y píxeles en BGRA, con numpy. `rgba` va en orden de arriba abajo, como `numpy.asarray(Image)`.
- **`fit_flag(img, *, mode="cover", focus=(0.5, 0.5)) -> PIL.Image.Image`**: lleva una imagen cualquiera
  (RGB, RGBA, P o L) a 93×64 RGBA.
  - `cover` escala hasta cubrir y recorta alrededor de `focus` (fracciones de ancho y alto: (0, 0) es arriba a
    la izquierda).
  - `contain` escala hasta caber y rellena con transparente.
  - `stretch` deforma.
  - Usa un remuestreo de calidad (`LANCZOS`).
- **`make_flag_set(images) -> dict[str, bytes]`**: de `{sufijo: imagen}` a `{sufijo: TGA}` para los sufijos de
  `FLAG_SUFFIXES`; un sufijo que no está en la lista lanza `ValueError`.
- Todas las salidas se releen con Pillow para verificarlas: 93×64, RGBA, mismos píxeles. Si no coinciden, lanza
  `ValueError`.

**Pruebas:** `tests/test_gfx_flags.py`.

- Sintéticas:
  - `write_tga` de una imagen asimétrica (un solo píxel en una esquina): Pillow la relee igual (orientación) y la
    cabecera tiene tipo 2, 32 bits y descriptor `0x08`;
  - `fit_flag` en sus tres modos con imágenes más anchas, más altas y del mismo aspecto: tamaño, recorte
    centrado y con `focus` en un extremo, y transparencia de `contain`;
  - `make_flag_set` con los 5 sufijos y con uno inválido.
- Con corpus: lee un par de banderas de `gfx/flags/` del juego con Pillow, pásalas por `fit_flag` (ya son de
  93×64, así que no deben cambiar) y por `write_tga`, y compara los píxeles. Ningún píxel ni archivo del juego
  entra en el repositorio (regla 4).

**Hecho cuando:** todo lo anterior pasa y las mutaciones lo demuestran.

---

# Primera tanda (hecha): G1–G3

Se conserva como modelo. Las cifras y las reglas de esta parte son las de entonces (978 pruebas, otros
archivos vetados).

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
