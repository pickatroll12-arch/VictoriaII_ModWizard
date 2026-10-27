# Victoria II Mod Studio

Aplicación de escritorio para **Windows y Linux** que permite crear, editar y
gestionar mods de **Victoria II** de forma visual, sin editores de texto
externos. La versión de referencia del juego es *Heart of Darkness* 3.04.

Incluye su propio motor de lectura y escritura de los archivos del juego
(sintaxis de llaves `{}` de Clausewitz y los `.csv` de localización), que
conserva cada byte de lo que no se edita: comentarios, tabulaciones, CRLF y la
codificación Windows-1252 que exige el juego.

La interfaz imita la estética de Victoria II (bronce envejecido, pergamino,
terciopelo, madera, serifas clásicas) con texturas generadas por código, y se
puede usar en **español o inglés**, cambiando de idioma en tiempo real.

> Proyecto independiente, sin relación con Paradox Interactive. La aplicación
> trabaja sobre la copia de Victoria II que tenga instalada cada usuario y no
> incluye gráficos, fuentes ni archivos del juego (ver
> [Licencias y datos](#licencias-y-datos)).

## Estado del proyecto

Versión **0.1.0**, pre-alfa.

- **Iteración 1**: cerrada. Incluye el motor de archivos, el visor y la
  validación.
- **Iteración 2** (los cimientos): integrada y revisada. Llegan:
  - un sistema de archivos virtual juego base + mod;
  - el proyecto transaccional, con guardado todo o nada, deshacer y
    recuperación tras un corte;
  - el generador del descriptor `.mod`;
  - la ventana de 7 salas.

- **Iteración 3** (índice, validación y textos): integrada y revisada. Llegan:
  - el índice de símbolos de la vista efectiva (juego, dependencias, mod y
    cambios sin guardar), con caché e incremental;
  - la validación cruzada con línea base, que no culpa al mod de los fallos
    del juego, con arreglos de un clic y el explicador «¿Por qué?»;
  - la localización editable y sincronizada en la sala Textos;
  - el buscador universal Ctrl+K.

La iteración 2 pasó dos rondas de revisión adversarial: 55 hallazgos
confirmados, todos corregidos con su prueba de regresión. La iteración 3 pasó
la suya, por componentes, con las correcciones también probadas con
mutaciones. Lo siguiente es la
[iteración 4](docs/diseno/wizard.md#22-plan-de-iteraciones), el motor de
esquemas. El estado detallado está en el
[documento de traspaso](CONTINUAR_EN_CLAUDE_CODE.md).

### Qué funciona hoy

La ventana tiene **7 salas** (Ctrl+1 … Ctrl+7): Proyecto, Mapa, Naciones,
Guerra, Eventos, Interfaz y Textos. Cada sala tiene sus secciones en una barra
lateral, o en una franja si la ventana es estrecha. Lo que aún no existe es una
tarjeta que dice qué hará y en qué iteración llega.

- **Proyecto › Inicio**: el juego base (solo lectura) y los mods de su carpeta
  `mod/` como tarjetas.
  - Un clic abre el mod.
  - «Crear mod nuevo» crea la carpeta, el descriptor y las carpetas básicas
    sin copiar nada del juego, todo o nada; una plantilla es opcional.
  - «Abrir otra carpeta» abre un mod que está fuera de `mod/`.
  - Debajo, «¿Qué quieres hacer?» y la hoja de ruta de las 10 iteraciones.
- **Proyecto › Descriptor .mod**: un formulario para `name`, `path`,
  `user_dir`, `dependencies` y `replace_path`.
  - Muestra cómo quedará el archivo y sus problemas mientras escribes.
  - Editar un campo conserva los comentarios y el resto del archivo.
  - Un `.mod` en UTF-16, que el juego no lee, se pasa a Windows-1252.
- **Proyecto › Archivos**: las rutas del juego y del mod, un explorador con la
  capa de cada archivo (juego, dependencia o mod) y la vista previa:
  - scripts Clausewitz (`.txt`, `.mod`, `.gfx`, `.gui`, `.sfx`, `.asset`,
    `.map`), con las pestañas Estructura, Código fuente, Diagnósticos y JSON, y
    buscador. Un archivo en UTF-16 sale en rojo («Ilegible para el juego»);
  - imágenes (`.tga`, `.dds`, `.bmp`, `.png`, `.jpg`, `.jpeg`, `.gif`);
  - los `.csv` de `localisation/`, que se abren en Textos.
  - «Validar mod» (F7) lanza el validador del núcleo y lleva a Proyecto ›
    Validación. La pestaña «Validación» del panel izquierdo conserva el
    análisis de la iteración 1, archivo a archivo, sobre el disco.
- **Proyecto › Validación** (F7): el informe del validador sobre la vista
  efectiva, con los cambios sin guardar, en segundo plano y cancelable.
  - Columnas de gravedad, mensaje, entidad, archivo y línea; doble clic abre el
    archivo en esa línea.
  - Los problemas que ya tiene el juego base salen como **heredados** y se
    ocultan; un conmutador los enseña, en cursiva.
  - **[Arreglar]** enseña antes el plan de cambios con su diff y pide
    confirmación. Arreglos de esta iteración: registrar un TAG antes de
    `dynamic_tags`, convertir a Windows-1252, añadir la `}` que falta,
    recuperar las filas de vanilla de una copia degradada de `text.csv` y
    mandar a la papelera las copias idénticas al juego. Todo se deshace con
    Ctrl+Z y nada se escribe hasta guardar.
  - **[¿Por qué?]** abre el explicador: las capas en el orden en que las carga
    el juego, cada una con su línea real y su veredicto, y lo que verá el
    jugador.
  - El panel acoplable **Problemas** da lo mismo en compacto.
- **Proyecto › Cambios pendientes**: lo que escribirá Guardar, archivo a
  archivo, con su diff. Se puede descartar un archivo.
- **Textos › Todos los textos** y **Pendientes de traducir**: la localización
  efectiva, editable en la tabla, con los textos en inglés, español, francés y
  alemán, su archivo ganador y su origen.
  - Editar una clave sigue la regla del juego (gana la primera clave por orden
    alfabético de archivo): si gana un CSV del mod, se edita en su sitio; si
    gana el juego, se escribe en `localisation/00_<prefijo>_overrides.csv`, sin
    copiar nunca el CSV del juego.
  - «Añadir clave», filtros («creadas por el Studio», «sin traducir»,
    «sustituyen a vanilla» y «degradadas») y buscador sin mayúsculas ni
    acentos.
- **Textos › Archivos CSV**: cada CSV en una tabla de solo lectura, con
  buscador y el lint traducido.
- **Ctrl+K**: busca cualquier símbolo del índice (países, provincias, partidos,
  culturas, eventos, decisiones, claves de localización…) por su id o por su
  nombre en el idioma de la interfaz («549», «Berlín», «PRU»,
  «north_german»), y también las salas y secciones. Intro abre el archivo en
  su línea.

**Editar, guardar y deshacer.** Cada cambio es un paso con nombre que se
deshace (Ctrl+Z) y se rehace (Ctrl+Y, o Ctrl+Mayús+Z); el Historial lista los
pasos. Guardar (Ctrl+S) escribe todo o nada a través de un diario:

- un corte a mitad (el disco lleno, cerrar el proceso) deja el mod como antes o
  como después;
- se guarda la copia `.bak` y el original en `.vic2studio/originals/`;
- antes de copiar un archivo del juego al mod o de mandar algo a la papelera,
  se pide confirmación;
- si un archivo cambió fuera del Studio, se pregunta («Conservar mis cambios»,
  «Recargar del disco» o «Comparar»);
- el trabajo sin guardar se autoguarda, y al reabrir se ofrece recuperarlo;
- abrir el mismo mod en otra instancia lo deja en solo lectura.

El Studio solo escribe en la carpeta del mod y en su `.mod`, nunca en el juego
base.

El núcleo (`vic2studio.core`, sin Qt) se puede usar desde Python o desde la
terminal:

- `encoding` y `fileio`: detección sin pérdidas de Windows-1252 (con sus cinco
  bytes indefinidos), UTF-8 con y sin BOM, UTF-16 LE y BE con BOM (`utf-16` y el
  codec propio `utf-16-be-bom`) o sin él, y BOM repetidos; escritura atómica con
  copia `.bak` y `FileChangedError` si el archivo cambió fuera de la aplicación.
- `clausewitz`: parser tolerante a errores con árbol sintáctico concreto
  (`to_source` devuelve el texto exacto), diagnósticos en ES/EN (también de la
  codificación: error con UTF-16, aviso con UTF-8 o con un BOM UTF-8 delante de
  Windows-1252), BOM repetidos en `Document.extra_boms`, posiciones finales
  públicas (`Entry.value_end`, `Block.close_position`), API de edición
  que conserva el formato (`set`, `remove`, `move`, `insert_before`,
  `insert_after`, `clone`, `close`, `find_path`, `from_pairs`, comentarios con
  `line_comment`, `open_comment` y `trailing_comments`), errores `EditError`
  con código y mensaje ES/EN, `write_file(verify=True)`, que no escribe si el
  texto generado no se relee igual que el árbol editado, y JSON (`to_json`,
  `from_json`, `iter_json`).
- `csvloc`: CSV de localización sin pérdidas (incluidos los BOM repetidos, en
  `LocalisationFile.extra_boms`), lint con 9 códigos y `LocalisationDB`, que
  fusiona las carpetas como el juego: un CSV del mod sustituye al de vanilla
  con el mismo nombre y, si una clave se repite, gana el primer archivo en
  orden alfabético (de ahí el prefijo `00_` de los mods).
- `modfile` (descriptor `.mod`: leer, editar sin perder comentarios y generar
  uno nuevo en cp1252 con CRLF) y `modcheck` (validación de un mod completo).
- `cancel`: cancelación cooperativa; las funciones largas aceptan
  `cancelled=` y lanzan `Cancelled`.
- `index`: el índice de símbolos (`SymbolIndex`). Hay extractores registrados
  por descubrimiento para países, partidos, provincias de tierra y de mar,
  regiones, continentes, climas, culturas, religiones, gobiernos, ideologías,
  asuntos, tecnologías, invenciones, bienes, edificios, tipos de POP,
  unidades, CB, eventos, decisiones, bookmarks, guerras, sprites, imágenes y
  claves de localización. Guarda en caché los hechos de cada archivo, en
  JSON-lines comprimido por capa (nunca `pickle`), y solo reprocesa lo que
  cambia.
- `validate`: la validación cruzada.
  - Reglas por familia: sintaxis, archivos, descriptor, países, provincias,
    localización, eventos, decisiones y `peace_order`.
  - Línea base del juego en caché, para marcar los heredados.
  - Arreglos con plan previo (`FixError` con código y texto ES/EN).
  - Explicador para cada código.
- `rules` (`GameRules`, ids, nombres y colores) y `lua_defines`, que lee y
  cambia `defines.lua` sin perder ni un byte de lo demás.
- `locsync`: edita la localización con la política del juego, sobre la vista
  efectiva (también lo que no se ha guardado).

### Qué viene

El diseño del objetivo ampliado está en
[docs/diseno/wizard.md](docs/diseno/wizard.md) y sustituye a la hoja de ruta y
a las partes planificadas de ARCHITECTURE.md. Cubre las iteraciones 2 a 10 (la
9 dividida en 9a y 9b), con el plan en
[§22](docs/diseno/wizard.md#22-plan-de-iteraciones) y las decisiones del
usuario en [§24](docs/diseno/wizard.md#24-decisiones-del-usuario-26-10-2026).
Las salas y el proyecto transaccional de la iteración 2 son la base de las
[15 capacidades](docs/diseno/wizard.md#14-las-15-capacidades). Esta es la
iteración en que llega cada una:

1. Generar el archivo `.mod` (2, hecha).
2. Países: asistente, ficha, banderas `.tga` e historial (6).
3. Provincias (5; las nuevas, 9).
4. Unidades terrestres (4).
5. Decisiones (7).
6. Suite de modificación de interfaces `.gui`/`.gfx` (8).
7. Eventos (7).
8. Guerras de inicio (6).
9. Casus belli (4).
10. Bookmarks o fechas de inicio (4).
11. Gobiernos nuevos (4).
12. Unidades navales (4).
13. Culturas (4).
14. Regiones, continentes y climas (5).
15. Taller de mapas nuevos: generación procedural al estilo de Azgaar's
    Fantasy Map Generator o importación de bitmaps, con todos sus archivos
    dependientes (9a y 9b).

La iteración 3 (hecha) añadió el índice de símbolos, la validación con línea
base, la localización editable sincronizada y Ctrl+K, que necesitan todas las
capacidades. La 4 trae el motor de esquemas y la 10, el pulido, la exportación
a zip y el empaquetado final. Los prototipos del taller de mapas están en
[docs/diseno/prototipos/mapforge/](docs/diseno/prototipos/mapforge/README.md).

## Requisitos

- Python **3.10** o superior.
- [PySide6](https://pypi.org/project/PySide6/) ≥ 6.5 (Qt 6), numpy ≥ 1.24 y
  Pillow ≥ 10 (ver `requirements.txt`). Con Python 3.10 y 3.11, PySide6 tiene
  que ser anterior a la 6.12: la 6.12.0 suelta referencias de más a `None`,
  `True` y `False`, y en esas versiones de Python el programa aborta al rato
  («Fatal Python error: none_dealloc»). Desde Python 3.12 no pasa.
  `requirements.txt` y `pyproject.toml` ya lo tienen en cuenta. Si esa
  combinación ya está instalada, la aplicación lo avisa al arrancar, antes de
  abrir la ventana, con un mensaje que dice cómo arreglarlo, y sale con el
  código 1; las pruebas que usan Qt fallan al importar `tests/_qt.py` con el
  mismo mensaje. `VIC2STUDIO_ALLOW_BROKEN_PYSIDE=1` desactiva la comprobación
  (para probar una PySide6 posterior que quizá lo corrija).
- Con PySide6 6.5 o 6.6, numpy tiene que ser anterior a la 2: sus ruedas de
  shiboken6 se compilaron con NumPy 1.x y, con numpy 2, cada import de PySide6
  escribe en la consola una traza falsa (la aplicación funciona, pero una
  prueba que vigila la salida de error falla). Pasa sobre todo al combinar la
  PySide6 de la distribución con el numpy de pip (`venv --system-site-packages`):
  `python3 -m pip install "numpy<2"` lo arregla. Desde PySide6 6.7 no pasa.

Sin corpus, la batería entera pasa en tres combinaciones: Python 3.13.17 y
PySide6 6.12.0, Python 3.10.20 y PySide6 6.11.3 (numpy 2, Pillow 12), y
PySide6 6.5.0, el mínimo, con Python 3.10, numpy 1.24 y Pillow 10.

En Linux las dependencias pueden venir del gestor de paquetes (en Fedora:
`python3-pyside6`, `python3-numpy`, `python3-pillow`) o de pip:

```bash
python3 -m pip install -r requirements.txt
```

En un contenedor Debian o Ubuntu sin escritorio, Qt suele necesitar además
estas bibliotecas del sistema para la plataforma `offscreen`:

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 fonts-dejavu
```

## Ejecutar desde el código

Sin instalar nada (desde la raíz del proyecto):

```bash
PYTHONPATH=src python3 -m vic2studio
```

En Windows (PowerShell):

```powershell
$env:PYTHONPATH = "src"; py -m vic2studio
```

Instalado en modo editable, con el comando `vic2studio`:

```bash
python3 -m venv .venv --system-site-packages   # reutiliza PySide6/numpy ya instalados
. .venv/bin/activate                            # Windows: .venv\Scripts\activate
pip install -e .
vic2studio
```

`pip install -e .` descarga `setuptools` en un entorno aislado; sin conexión,
usa `pip install -e . --no-build-isolation` con setuptools ≥ 64 ya instalado.

Las preferencias (idioma, rutas…) se guardan en un archivo INI:
`~/.config/VIIMOD/Victoria II Mod Studio.ini` en Linux y
`%APPDATA%\VIIMOD\Victoria II Mod Studio.ini` en Windows. La variable
`VIC2STUDIO_SETTINGS_DIR` las desvía a otra carpeta.

## Pruebas

Las pruebas usan `unittest` de la biblioteca estándar, no necesitan instalar
el paquete. Desde la raíz del proyecto:

```bash
QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" \
    python3 -m unittest discover -s tests
```

`QT_QPA_PLATFORM=offscreen` permite ejecutar las pruebas de interfaz sin
pantalla, y `VIC2STUDIO_SETTINGS_DIR` evita que la ejecución toque la
configuración real (las pruebas de interfaz, además, usan su propia carpeta
temporal, en `tests/_qt.py`).

Las pruebas de **corpus** recorren mods reales y comprueban, por ejemplo, que
leer y guardar sin cambios produce exactamente los mismos bytes. Las carpetas
se indican en `VIC2_CORPUS`, separadas por `:` en Linux y por `;` en Windows
(`os.pathsep`). Con el juego base, la plantilla y el mod del usuario:

```bash
VIC2_CORPUS="/ruta/vanilla:/ruta/Plantilla Mod:/ruta/ShagoMod" \
    QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" \
    python3 -m unittest discover -s tests
```

Si `VIC2_CORPUS` no está definida (o está vacía) se usa `../Plantilla Mod`
(respecto a la raíz del proyecto) si existe, y siempre la muestra mínima del
mod del usuario que trae el repositorio (`tests/fixtures/shago_mod_min`). Las
pruebas que necesitan archivos que la muestra no tiene (un `text.csv` grande,
una historia de provincia) usan una plantilla sintética generada por código
(`tests/_corpus.py`).

Resultado actual: **1089 pruebas** en 70 archivos, **todas OK con 5 omitidas**
sin `VIC2_CORPUS`, y todas OK sin omitir ninguna con el corpus completo (la
instalación de vanilla, la plantilla y el Shago Mod). Con el corpus, el parser
recorre 12 054 archivos Clausewitz (27,4 MB) con ida y vuelta byte a byte.

Algunas pruebas miden las pausas de la interfaz: en una máquina cargada (por
ejemplo, con dos baterías a la vez) pueden fallar. Repítelas antes de darlas
por rotas.

## Herramientas de línea de comandos

El núcleo no depende de Qt y se puede usar desde la terminal (con
`PYTHONPATH=src` si no está instalado). Los ejemplos se ejecutan desde la raíz
del proyecto sobre la muestra del mod del usuario que trae el repositorio.

### Scripts Clausewitz: `vic2studio.core.clausewitz`

```text
python3 -m vic2studio.core.clausewitz check RUTA... [--lang es|en]
python3 -m vic2studio.core.clausewitz tojson ARCHIVO [--comments] [--lang es|en]
```

`check` recorre archivos y carpetas (en ellas, los `.txt`, `.mod`, `.gfx`,
`.gui`, `.sfx`, `.asset` y `.map`) e imprime cada diagnóstico como
`archivo:línea:columna: gravedad: mensaje`. El resumen sale por la salida de
error. Los mensajes están en español por defecto; `--lang en` los da en
inglés.

```bash
PYTHONPATH=src python3 -m vic2studio.core.clausewitz check tests/fixtures/shago_mod_min
```

```text
tests/fixtures/shago_mod_min/VSM/decisions/somaliland_shago.txt:1:23: error: El bloque 'political_decisions' abierto en la línea 1 no se cierra (falta '}')
tests/fixtures/shago_mod_min/VSM/decisions/zulu_expancionshago.txt:1:23: error: El bloque 'political_decisions' abierto en la línea 1 no se cierra (falta '}')
tests/fixtures/shago_mod_min/VSM/decisions/zulu_expancionshago.txt:155:1: info: Esta '}' cierra 'imperio_zulu' (línea 85) pero tiene menos sangría que esa línea: puede que falte una '}' antes
17 archivo(s), 2 error(es), 0 aviso(s)
```

Sobre el mod completo del usuario (3927 archivos; medido en una sesión con el
corpus, que no está en el repositorio) salen 3 errores y 1 aviso:
los dos bloques sin cerrar de arriba, que pasan fácilmente desapercibidos en el
juego, y dos problemas heredados de vanilla, que el mod copia tal cual:
`history/units/v2dd2.txt` es un diario de desarrollo en prosa que el juego base
trae en una carpeta de scripts (error `missing_key`) y
`history/units/1861/HAI_oob.txt` está en UTF-8 (aviso).

`tojson` escribe el árbol en JSON por la salida estándar y los diagnósticos
por la de error; `--comments` incluye los comentarios (`comments`,
`line_comment`, `open_comment` y `trailing_comments`). El esquema está en la
sección «Motor de parseo» de [ARCHITECTURE.md](ARCHITECTURE.md). Los ejemplos
que escriben archivos usan una carpeta temporal para no ensuciar el
repositorio:

```bash
OUT="$(mktemp -d)"
PYTHONPATH=src python3 -m vic2studio.core.clausewitz tojson tests/fixtures/shago_mod_min/VSM/common/countries/Somalia.txt --comments > "$OUT/Somalia.json"
```

Códigos de salida: `check` da 1 si hay algún error (también un archivo que no
se puede leer) y 0 si no; los avisos y las notas no cuentan. `tojson` da 0 si
el archivo no tiene errores de sintaxis y 1 si los tiene (el JSON se escribe
igual) o no se puede leer.

| Código | Gravedad | Qué detecta |
|---|---|---|
| `unclosed_block` | error | Un bloque que no se cierra (falta `}`). |
| `unexpected_close_brace` | error | Una `}` sobrante, sin bloque abierto. |
| `missing_value` | error | Una clave con operador pero sin valor. |
| `missing_key` | error | Un operador sin clave. |
| `unterminated_string` | error | Una cadena sin la comilla de cierre. |
| `invalid_key` | error | Un bloque usado como clave. |
| `unexpected_operator` | error | Un operador donde se esperaba un valor. |
| `invalid_character` | error | Un `!` suelto, que no forma `!=`. |
| `multiline_string` | aviso | Una cadena que sigue en otra línea (¿falta una comilla?). |
| `control_character` | aviso | Caracteres de control invisibles en el archivo. |
| `invisible_character` | aviso | Una palabra con un carácter invisible (espacio duro, ancho cero…). |
| `non_game_encoding` | aviso | Un archivo en UTF-8: con BOM, o sin él y con caracteres no ASCII. |
| `suspicious_close_brace` | info | La `}` con menos sangría que su apertura: pista de dónde falta una `}`. |

Un archivo en UTF-16, que el juego no puede leer, sale con el error
`unreadable_encoding` (y el código de salida 1), y un BOM UTF-8 delante de un
texto en Windows-1252, con el aviso `stray_bom`. «Validar mod» y el visor dan
los mismos diagnósticos.

### Localización CSV: `vic2studio.core.csvloc`

```text
python3 -m vic2studio.core.csvloc check RUTA... [--lang en|es] [--summary] [--strict]
python3 -m vic2studio.core.csvloc tojson ARCHIVO [-o SALIDA] [--indent N] [--lang en|es]
python3 -m vic2studio.core.csvloc fromjson JSON -o SALIDA [--no-backup] [--lang en|es]
```

`check` analiza los archivos indicados y, en las carpetas, los `.csv` de
localización (los que están en una carpeta `localisation/` y los que están
directamente en la carpeta indicada); el resumen cuenta los `.csv` omitidos,
como `map/definition.csv`. Cada diagnóstico sale como
`archivo[:línea[:columna]]: gravedad: mensaje [código]`, y el resumen, por la
salida estándar. Aquí los mensajes están en inglés por defecto. `--summary`
solo cuenta los diagnósticos por código:

```bash
PYTHONPATH=src python3 -m vic2studio.core.csvloc check tests/fixtures/shago_mod_min/VSM/localisation --summary --lang es
```

```text
    125  missing_end_marker
      6  semicolon_in_quotes
      3  header_row
3 archivo(s): 0 error(es), 6 aviso(s), 128 info
```

Los 6 avisos son textos ingleses entre comillas con un `;` dentro: el juego no
entiende las comillas, así que el `;` parte el texto y desplaza las columnas
siguientes.

`tojson` convierte un `.csv` a JSON (por la salida estándar o en `-o`;
`--indent`, 1 por defecto) y `fromjson` escribe el `.csv` a partir de ese JSON,
en la codificación que este indica, de forma atómica y con copia `SALIDA.bak`
si ya existía (salvo con `--no-backup`). La ida y vuelta da los mismos bytes:

```bash
OUT="$(mktemp -d)"
PYTHONPATH=src python3 -m vic2studio.core.csvloc tojson tests/fixtures/shago_mod_min/VSM/localisation/00_VSM_modifiers.csv -o "$OUT/mods.json"
PYTHONPATH=src python3 -m vic2studio.core.csvloc fromjson "$OUT/mods.json" -o "$OUT/00_VSM_modifiers.csv"
cmp "$OUT/00_VSM_modifiers.csv" tests/fixtures/shago_mod_min/VSM/localisation/00_VSM_modifiers.csv   # sin diferencias
```

Códigos de salida: `check` da 0 sin errores, 1 con errores (o con avisos si se
pasa `--strict`) y 2 si alguna ruta no se pudo leer. `tojson` da 0 o, si no se
pudo leer o escribir un archivo, 2. `fromjson` da 0, 1 si un texto tiene
caracteres que no caben en la codificación (con su línea y columna) y 2 si no
se pudo leer o escribir un archivo o el JSON no es válido.

| Código | Gravedad | Qué detecta |
|---|---|---|
| `missing_end_marker` | aviso o info | Falta la `x` de la columna 14, o está desplazada por columnas de menos o un `;` de más. Es una nota (info) si el juego ve la fila entera: solo faltan la `x` o idiomas que el juego no muestra. |
| `too_few_columns` | aviso | A la fila le falta algún idioma que el juego muestra (inglés, francés, alemán o español). |
| `duplicate_key` | aviso | Una clave repetida en el archivo: el juego usa la primera. |
| `empty_key` | aviso | Una fila sin clave. |
| `key_whitespace` | aviso | Una clave con espacios al principio o al final. |
| `semicolon_in_quotes` | aviso | Un `;` entre comillas, que el juego trata como separador. |
| `unencodable_character` | error | Caracteres que no se pueden guardar en Windows-1252. |
| `non_game_encoding` | aviso o error | Un archivo en UTF-8 (con o sin BOM) o con un BOM UTF-8 perdido delante de Windows-1252; error si está en UTF-16, que el juego no puede leer. |
| `header_row` | info | Una fila de cabecera (`key;English;…`): el juego la carga como una clave más. |

«Validar mod» usa estos diagnósticos y los del parser (también
`unreadable_encoding` y `stray_bom`), y añade los suyos: `no_game_folders` (la
carpeta no parece la raíz de un mod, aviso), `read_error`, `folder_error` y
`check_failed` (errores al leer o analizar) y los `descriptor_*`, que revisan
los campos del `.mod`.

## Capturas de pantalla

```bash
python3 tools/screenshot.py --out capturas --lang all
```

Genera `capturas/<idioma>_<n>_<página>.png` (por ejemplo,
`es_1_project.png`) sin pantalla: usa la plataforma `offscreen` si no se
indica otra y una carpeta de preferencias temporal, así que no toca la
configuración del usuario. Opciones:

| Opción | Uso |
|---|---|
| `--out DIR` | Carpeta de salida (obligatoria). |
| `--lang es\|en\|all` | Idioma; por defecto, los dos. |
| `--page all\|project\|map\|countries\|events\|localisation` | Página; por defecto, todas. |
| `--size ANCHOxALTO` | Tamaño de la ventana; por defecto `1440x900`. |
| `--mod RUTA`, `--game RUTA` | Carpetas del mod y del juego base. |
| `--open-file RUTA` | Abre un archivo (relativo al mod) en su visor, o un CSV en Localización. |
| `--line N`, `--search TEXTO` | Línea a mostrar y texto del buscador del archivo abierto. |
| `--tab structure\|source\|diagnostics\|json` | Pestaña del visor Clausewitz (solo con un script). |
| `--validate` | Ejecuta «Validar mod» y espera a que termine. |
| `--left-tab files\|validation` | Pestaña del panel izquierdo de «Proyecto y Archivos». |
| `--report ESTADO.json` | Guarda en JSON lo que muestran las capturas. |

Sale con 1 si no puede abrir el archivo o la línea pedidos o si no puede
validar (sin un `--mod` válido, o si la validación no termina a tiempo), y con
2 si una opción no tendría efecto (`--tab` sin un script, `--line` sin
`--open-file`…) o un idioma o una página no existen. Ejemplo:

```bash
python3 tools/screenshot.py --out capturas --lang es --page project \
    --mod tests/fixtures/shago_mod_min/VSM --validate --left-tab validation
```

Las capturas de `docs/capturas/` se generaron con esta herramienta sobre la
muestra del repositorio, en español e inglés; su nombre dice la página, el
idioma y el tamaño. Son de dos tandas:

- **01 a 10** (T5, iteración 1, 26-10-2026): a 1100x700, 1440x900 y
  1920x1080.
- **11 a 20** (iteración 2, 27-10-2026): Inicio, Descriptor .mod, Archivos,
  Cambios pendientes y la revisión antes de guardar, en español a 1100x700 y
  en inglés a 1920x1080.

Las de la iteración 2 salen con un juego sintético y dos cambios sin guardar:

```bash
python3 tools/screenshot.py --out capturas --lang all --size 1100x700 \
    --mod tests/fixtures/shago_mod_min/VSM --demo-game --demo-changes --no-game-art \
    --page project:home,project:descriptor,project,project:pending --dialog save_review
```

## Empaquetado

`packaging/` contiene la especificación de PyInstaller (`vic2studio.spec`, modo
*one-folder*), el lanzador de Linux (`linux/vic2studio.desktop`) y los scripts
para generar los ejecutables en cada sistema:

```bash
packaging/build_linux.sh            # dist/Victoria II Mod Studio/ + .tar.gz
packaging/build_linux.sh --install  # además lo instala en ~/.local con lanzador
```

```bat
packaging\build_windows.bat         :: dist\Victoria II Mod Studio\ + .zip
```

Por defecto crean un entorno virtual (`build/venv-linux` o
`build\venv-windows`) e instalan ahí las dependencias y PyInstaller (requiere
conexión); `--system` usa el Python actual. PyInstaller no compila en cruzado:
cada ejecutable se genera en su sistema.

## Estructura

```text
src/vic2studio/
├── core/              núcleo sin Qt
│   ├── clausewitz/    parser .txt sin pérdidas, edición, JSON y CLI
│   ├── csvloc/        CSV de localización: modelo, lint, LocalisationDB y CLI
│   ├── vfs/           sistema de archivos virtual juego + dependencias + mod, WriteGuard
│   ├── project/       Project, Workspace, códecs, deshacer, diario, recuperación y bloqueo
│   ├── index/         índice de símbolos: modelo, caché, construcción y extractores
│   ├── validate/      validación con línea base: reglas, arreglos y explicador
│   ├── rules/         reglas del juego: GameRules, ids, nombres y colores
│   ├── locsync.py     edición sincronizada de la localización
│   ├── lua_defines.py defines.lua sin pérdidas
│   ├── map/, gfx/     piezas del mapa y de imágenes para iteraciones futuras (BMP, definition.csv, DDS, banderas)
│   ├── tablecsv.py    CSV de tablas sin pérdidas (definition.csv y compañía)
│   ├── encoding.py    detección de codificaciones y códecs sin pérdidas
│   ├── fileio.py      lectura con huella y escritura atómica con .bak
│   ├── modfile.py     descriptor .mod
│   ├── modcheck.py    validación de un mod completo (la de la iteración 1)
│   ├── appdirs.py     carpetas de datos y caché del Studio
│   ├── texts.py       textos ES/EN del núcleo
│   └── cancel.py      cancelación cooperativa (cancelled=)
├── i18n/              traductor, catálogos es.json / en.json y fragmentos por sala
├── ui/
│   ├── halls/         las 7 salas y sus secciones (registro por descubrimiento)
│   ├── shell/         armazón: sala, barra de secciones, Cambios pendientes, Historial, Problemas y Ctrl+K
│   ├── dialogs/       revisión del guardado, conflicto, recuperación, nuevo mod, plan de un arreglo y nueva clave
│   ├── pages/         páginas de Archivos, Archivos CSV y la tarjeta «en desarrollo»
│   ├── viewers/       visor Clausewitz, código, diagnósticos, imágenes, localización y validación
│   ├── widgets/       estandarte, tarjetas, iconos, navegación, ornamentos, superficies y diseño en flujo
│   ├── session.py     Session: el único puente entre el proyecto y Qt
│   ├── tasks.py       tareas en segundo plano: grupos de hilos y cancelación
│   ├── theme.py       tema procedural (con style.qss)
│   └── main_window.py ventana principal
├── app.py             punto de entrada de la aplicación
├── compat.py          aviso de PySide6 incompatible con la versión de Python
├── settings.py        preferencias (QSettings en formato INI)
└── __main__.py        python -m vic2studio
tests/                 pruebas unittest, muestra del mod del usuario en fixtures/
tools/screenshot.py    capturas sin pantalla
packaging/             PyInstaller y lanzador de Linux
docs/
├── diseno/            wizard.md (iteraciones 2 a 10) y prototipos del taller de mapas
├── capturas/          20 capturas ES/EN de la muestra (T5 e iteración 2)
├── requisitos/        requisitos originales del usuario
└── handoff/           encargos de los agentes, guiones de workflow y tareas para otros asistentes
```

El árbol detallado y la arquitectura están en [ARCHITECTURE.md](ARCHITECTURE.md).

## Licencias y datos

- **Paradox.** La aplicación, las pruebas de corpus y los prototipos leen los
  archivos del juego de la instalación del usuario en tiempo de ejecución, y la
  estética es 100 % procedural: el código no incluye gráficos ni fuentes del
  juego. Sobre el contenido de vanilla del repositorio:
  - La muestra `tests/fixtures/shago_mod_min` es del mod del usuario. Sus seis
    archivos de `common/countries/` repetían bloques de partidos y listas
    `unit_names` de vanilla, y por decisión del usuario (26-10-2026) son ahora
    versiones sintéticas: las políticas, las fechas de los partidos y los
    `unit_names` son inventados. Conservan los nombres de partido, las
    ideologías, los colores, `graphical_culture`, el `social_policy` de 5 de
    los 6 países, los partidos `MAJ_*` de Warsangali y las rarezas de formato.
  - Las capturas de `docs/capturas/` solo muestran archivos de la muestra
    (desde T5; las anteriores enseñaban dos archivos de vanilla).
- **Código del proyecto.** Todavía sin licencia: no hay archivo `LICENSE` ni
  campo de licencia en `pyproject.toml`, y está pendiente de que el autor la
  elija.
- **Terceros.** [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) recoge la
  licencia MIT de Azgaar's Fantasy Map Generator, cuyos algoritmos portan los
  prototipos del taller de mapas y portará la iteración 9.

---

## English summary

**Victoria II Mod Studio** is a desktop application (Windows and Linux) for
creating and editing Victoria II mods visually; the reference game version is
Heart of Darkness 3.04. Its own engine reads and writes Clausewitz `.txt` and
Victoria II `.csv` files losslessly (comments, whitespace, CRLF and
Windows-1252 are preserved). The UI mimics the Victoria II look with
procedurally generated textures and switches between Spanish and English at
runtime. It is an independent project, not affiliated with Paradox
Interactive: the app works on each user's own copy of the game and ships no
game graphics or fonts (see the licence notes below for the vanilla content
that the repository still holds).

**Status**: version 0.1.0, pre-alpha.

- Iteration 1 (file engine, viewer, validation) is closed.
- Iteration 2 (foundations) is integrated, and two adversarial review rounds
  fixed 55 confirmed findings, each with a regression test.
- Iteration 3 (symbol index, validation with a baseline, synchronised
  localisation editing and Ctrl+K) is integrated and reviewed.

The window has 7 halls (Ctrl+1 … Ctrl+7): Project, Map, Nations, War, Events,
Interface and Texts. Planned sections are cards that say which iteration
brings them. Project has five sections:

- **Home**: the base game and the mods in its `mod/` folder; a new mod is
  created all-or-nothing, with an optional template.
- **.mod descriptor**: a form that keeps comments and converts UTF-16 to
  cp1252.
- **Files**: the paths, an explorer that shows the layer of each file, and the
  Clausewitz, image and CSV previews, plus a background "Validate mod" (F7).
- **Validation** (F7): cross-file validation of the effective view (unsaved
  edits included), in the background. Problems the base game already has are
  marked as inherited and hidden by default. **Fix** shows the planned diff
  before applying an undoable one-click fix. The five fixes are: register a
  TAG before `dynamic_tags`, convert to cp1252, add the missing `}`, restore
  vanilla rows in a degraded `text.csv` copy, and trash files identical to the
  game. **Why?** explains which layer wins and what the player will see. A
  dockable Problems panel shows the same report.
- **Pending changes**: the diff of each file.

Texts › All texts is the effective localisation, editable in place. A key won
by a mod CSV is edited where it is, and a key won by the game goes to
`localisation/00_<prefix>_overrides.csv`; the game's CSV is never copied. It
has filters for keys created by the Studio, untranslated keys, keys that
override vanilla and degraded keys. Texts › CSV files keeps the read-only
per-file table. Ctrl+K finds any indexed symbol by id or by its localised name
("549", "Berlín", "PRU", "north_german") and opens it at its line.

Edits are named, undoable steps. Saving (Ctrl+S) goes through a journal, so a
crash leaves the mod either before or after:

- it keeps `.bak` copies and the originals;
- saves that copy game files or trash files are reviewed first;
- external changes are detected;
- unsaved work is autosaved and offered back after a crash;
- a second instance opens the mod read-only.

The Studio only ever writes to the mod folder and its `.mod`.

The Qt-free core provides
lossless encoding detection (cp1252, UTF-8, UTF-16 with or without BOM,
repeated BOMs), a lossless Clausewitz parser with a format-preserving edit API,
encoding diagnostics (an error for UTF-16, which the game cannot read) and
public end positions for tree nodes, a lossless CSV model with lint and a
localisation database that merges folders the way the game does, `.mod`
descriptor handling, whole-mod validation and cooperative cancellation. Since
iteration 3 it also has the symbol index, which caches per-file facts as
compressed JSON lines and rebuilds incrementally. It also has rule-based
validation with a cached base-game baseline, one-click fixes and a conflict
explainer, game rules, a lossless `defines.lua` editor and `LocSync`.

**Roadmap**: iterations 2 to 10 in
[docs/diseno/wizard.md](docs/diseno/wizard.md) (Spanish), which replaces the
roadmap in ARCHITECTURE.md. On top of the 7 halls and the vanilla + mod
virtual file system with transactional saving and undo, they will cover 15
capabilities: `.mod` generation, countries, provinces, land units, decisions,
an interface (`.gui`/`.gfx`) suite, events, starting wars, casus belli,
bookmarks, governments, naval units, cultures, regions and a new-map workshop
(procedural generation in the style of Azgaar's Fantasy Map Generator, or
bitmap import).

**Requirements**: Python 3.10+, PySide6 ≥ 6.5, numpy ≥ 1.24, Pillow ≥ 10. On
Python 3.10 and 3.11, PySide6 must be older than 6.12: 6.12.0 releases extra
references to `None`, `True` and `False`, which crashes those Python versions
("Fatal Python error: none_dealloc"); `requirements.txt` and `pyproject.toml`
already pin it. If that combination is already installed, the app says so at
startup, before opening the window, and exits with 1, and the tests that use
Qt fail when importing `tests/_qt.py` with the same message;
`VIC2STUDIO_ALLOW_BROKEN_PYSIDE=1` skips the check. With PySide6 6.5 or 6.6,
numpy must be older than 2 (their shiboken6 wheels were built against NumPy 1.x;
with numpy 2 every PySide6 import prints a bogus traceback): `pip install
"numpy<2"`. Without a corpus, the whole
suite passes with Python 3.13.17 + PySide6 6.12.0, with Python 3.10.20 +
PySide6 6.11.3 and with PySide6 6.5.0, the declared minimum.

```bash
PYTHONPATH=src python3 -m vic2studio                    # run from source
pip install -e . && vic2studio                          # or install, then run
QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" \
    python3 -m unittest discover -s tests               # 1089 tests, 5 skipped without a corpus
VIC2_CORPUS="/path/to/vanilla:/path/to/mod" ...         # enable real-corpus tests (last run: 1089 of 1089 OK)
PYTHONPATH=src python3 -m vic2studio.core.clausewitz check /path/to/mod --lang en
PYTHONPATH=src python3 -m vic2studio.core.csvloc check /path/to/mod/localisation
python3 tools/screenshot.py --out capturas --lang all   # offscreen screenshots
```

Some tests measure UI pauses and may fail on a busy machine; rerun them before
treating them as broken. `clausewitz check` exits with 1 when there are
errors; `csvloc check` exits with 1 on errors (or warnings with `--strict`)
and 2 when a path cannot be read.

**Licences and data**: the app and the corpus tests read game files from the
user's installation at runtime. The six `common/countries/` files of the test
sample (`tests/fixtures/shago_mod_min`, from the user's mod) repeated vanilla
party blocks and unit name lists; at the user's request (26 October 2026) they
are now synthetic (invented policies, party dates and unit names). The
screenshots in `docs/capturas/` only show files of that sample. The project's own code has no licence yet. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the MIT licence of
Azgaar's Fantasy Map Generator and [ARCHITECTURE.md](ARCHITECTURE.md)
(Spanish) for the design.
