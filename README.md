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
> incluye gráficos ni fuentes del juego. El repositorio sí contiene algo de
> contenido de vanilla en la muestra de las pruebas y en dos capturas antiguas
> (ver [Licencias y datos](#licencias-y-datos)).

## Estado del proyecto

Versión **0.1.0**, pre-alfa. La **iteración 1 está en su recta final**. Además
del núcleo y la ventana principal, se revisó la integración del parser y la
localización con la interfaz, las pruebas dejaron de depender del corpus
completo, cada componente pasó una verificación adversarial y los hallazgos se
corrigieron con pruebas de regresión y una segunda ronda de verificación
(tareas T1–T4 del [documento de traspaso](CONTINUAR_EN_CLAUDE_CODE.md)). Falta
integrar la última ronda de T4 (ver más abajo) y queda T5, el informe final al
usuario con capturas nuevas.

### Qué funciona hoy

La aplicación tiene cinco módulos en la barra de navegación (Ctrl+1 … Ctrl+5):

- **Proyecto y Archivos**: rutas del juego base (solo lectura) y del mod, con
  comprobación de ambas carpetas y del descriptor `.mod`, y un explorador con
  filtro. La vista previa elige visor según el archivo:
  - scripts Clausewitz (`.txt`, `.mod`, `.gfx`, `.gui`, `.sfx`, `.asset`,
    `.map`): pestañas Estructura, Código fuente, Diagnósticos y JSON, con
    buscador; doble clic en un diagnóstico salta a su línea y a su nodo;
  - imágenes (`.tga`, `.dds`, `.bmp`, `.png`, `.jpg`, `.jpeg`, `.gif`),
    decodificadas con Pillow;
  - los `.csv` de `localisation/` se abren en Localización.
- **Validar mod** (en Proyecto y Archivos): analiza todos los scripts y CSV
  del mod y su descriptor, con progreso y cancelación, y lista los
  diagnósticos en una tabla filtrable; doble clic abre el archivo en esa línea.
- **Localización (CSV)**: tabla de solo lectura con una columna por idioma,
  buscador, conmutadores para mostrar comentarios y todas las columnas, y los
  diagnósticos del lint traducidos.
- **Mapa, Países y Eventos**: tarjetas con lo planificado. Estas tarjetas y el
  aviso de solo lectura de Localización usan la numeración de la hoja de ruta
  antigua (mapa en la iteración 3, países en la 4, eventos en la 5 y edición
  de la localización en la 2); el plan vigente es el de
  [wizard.md](docs/diseno/wizard.md), que las pone en la 5, la 6, la 7 y la 3.

El análisis, las imágenes y la validación corren en segundo plano, en grupos
de hilos propios (`ui/tasks.py`): la interfaz sigue respondiendo con archivos de
varios MB, abrir otro archivo cancela el análisis anterior y la validación
tiene un botón «Cancelar». La aplicación todavía no modifica archivos del juego
ni del mod: la escritura existe en el núcleo y en la CLI `fromjson`, y la
edición desde la interfaz empieza en la iteración 2.

El núcleo (`vic2studio.core`, sin Qt) se puede usar desde Python o desde la
terminal:

- `encoding` y `fileio`: detección sin pérdidas de Windows-1252 (con sus cinco
  bytes indefinidos), UTF-8 con y sin BOM, UTF-16 LE y BE con BOM (`utf-16` y el
  codec propio `utf-16-be-bom`) o sin él, y BOM repetidos; escritura atómica con
  copia `.bak` y `FileChangedError` si el archivo cambió fuera de la aplicación.
- `clausewitz`: parser tolerante a errores con árbol sintáctico concreto
  (`to_source` devuelve el texto exacto), diagnósticos en ES/EN, API de edición
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

**Última ronda de T4** (ya integrada; este README aún no la detalla, ver
`CONTINUAR_EN_CLAUDE_CODE.md`): los avisos de UTF-16 en `clausewitz check`, el
BOM repetido en `parse_file`, una API pública para que el visor sepa dónde
termina cada nodo del árbol, liberar la memoria del árbol de un archivo grande
fuera del hilo de la interfaz y las etiquetas de las codificaciones UTF-16 en
la interfaz.

### Qué viene

El diseño del objetivo ampliado está en
[docs/diseno/wizard.md](docs/diseno/wizard.md) y sustituye a la hoja de ruta y
a las partes planificadas de ARCHITECTURE.md. Cubre las iteraciones 2 a 10 (la
9 dividida en 9a y 9b), con el plan en
[§22](docs/diseno/wizard.md#22-plan-de-iteraciones) y las decisiones del
usuario en [§24](docs/diseno/wizard.md#24-decisiones-del-usuario-26-10-2026).
La interfaz pasará a 7 salas (Proyecto, Mapa, Naciones, Guerra, Eventos,
Interfaz y Textos) sobre una VFS vanilla + mod con guardado transaccional y
deshacer. Estas son las
[15 capacidades](docs/diseno/wizard.md#14-las-15-capacidades), con la
iteración en que llegan:

1. Generar el archivo `.mod` (2).
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

La iteración 3 añade el índice de símbolos, la validación con línea base y la
localización editable sincronizada; la 10, el pulido, la exportación a zip y
el empaquetado final. Los prototipos del taller de mapas están en
[docs/diseno/prototipos/mapforge/](docs/diseno/prototipos/mapforge/README.md).

## Requisitos

- Python **3.10** o superior.
- [PySide6](https://pypi.org/project/PySide6/) ≥ 6.5 (Qt 6), numpy ≥ 1.24 y
  Pillow ≥ 10 (ver `requirements.txt`). Con Python 3.10 y 3.11, PySide6 tiene
  que ser anterior a la 6.12: la 6.12.0 suelta referencias de más a `None`,
  `True` y `False`, y en esas versiones de Python el programa aborta al rato
  («Fatal Python error: none_dealloc»). Desde Python 3.12 no pasa.
  `requirements.txt` y `pyproject.toml` ya lo tienen en cuenta.

Las pruebas de esta versión se pasaron con Python 3.13 y PySide6 6.12, y con
Python 3.10 y PySide6 6.11.3 (numpy 2, Pillow 12).

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

Resultado actual: **561 pruebas OK** con el corpus completo, y **561 OK con 3
omitidas** sin `VIC2_CORPUS`. Con el corpus, el parser recorre 12 054 archivos
Clausewitz (27,4 MB) con ida y vuelta byte a byte.

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

Sobre el mod completo del usuario (3927 archivos) salen 3 errores y 1 aviso:
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
| `non_game_encoding` | aviso | Un archivo con BOM UTF-8, o en UTF-8 o UTF-16 con caracteres no ASCII. |
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

«Validar mod» usa estos diagnósticos y los del parser, y añade los suyos:
`unreadable_encoding` (script en UTF-16, error), `stray_bom` (BOM UTF-8 perdido
en un script, aviso), `no_game_folders` (la carpeta no parece la raíz de un
mod, aviso), `read_error`, `folder_error` y `check_failed` (errores al leer o
analizar) y los `descriptor_*`, que revisan los campos del `.mod`.

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

Las capturas de `docs/capturas/` son anteriores a T4 y no siguen estos
nombres; en T5 se sustituirán por otras generadas con esta herramienta sobre la
muestra del repositorio.

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
│   ├── encoding.py    detección de codificaciones y códecs sin pérdidas
│   ├── fileio.py      lectura con huella y escritura atómica con .bak
│   ├── modfile.py     descriptor .mod
│   ├── modcheck.py    validación de un mod completo
│   └── cancel.py      cancelación cooperativa (cancelled=)
├── i18n/              traductor y textos es.json / en.json
├── ui/
│   ├── pages/         páginas de los 5 módulos
│   ├── viewers/       visor Clausewitz, código, diagnósticos, imágenes, localización y validación
│   ├── widgets/       estandarte, tarjetas, iconos, navegación, ornamentos, superficies y diseño en flujo
│   ├── tasks.py       tareas en segundo plano: grupos de hilos y cancelación
│   ├── theme.py       tema procedural (con style.qss)
│   └── main_window.py ventana principal
├── app.py             punto de entrada de la aplicación
├── settings.py        preferencias (QSettings en formato INI)
└── __main__.py        python -m vic2studio
tests/                 pruebas unittest, muestra del mod del usuario en fixtures/
tools/screenshot.py    capturas sin pantalla
packaging/             PyInstaller y lanzador de Linux
docs/
├── diseno/            wizard.md (iteraciones 2 a 10) y prototipos del taller de mapas
├── capturas/          capturas de muestra (anteriores a T4)
├── requisitos/        requisitos originales del usuario
└── handoff/           workflow de la iteración 1 (contratos de API)
```

El árbol detallado y la arquitectura están en [ARCHITECTURE.md](ARCHITECTURE.md).

## Licencias y datos

- **Paradox.** La aplicación, las pruebas de corpus y los prototipos leen los
  archivos del juego de la instalación del usuario en tiempo de ejecución, y la
  estética es 100 % procedural: el código no incluye gráficos ni fuentes del
  juego. El repositorio sí contiene algo de contenido de vanilla en dos sitios:
  - La muestra `tests/fixtures/shago_mod_min` es del mod del usuario, y sus
    seis archivos de `common/countries/` parten de archivos de países de
    vanilla: de ahí vienen sus definiciones de partidos y sus listas de nombres
    de unidades. Falta decidir si esas listas se sustituyen por nombres
    sintéticos.
  - Dos de las capturas antiguas de `docs/capturas/`
    (`03_estructura_provincia.png` y `04_localizacion_text_csv.png`) muestran
    archivos de vanilla. Se sustituirán en T5 (ver
    [Capturas de pantalla](#capturas-de-pantalla)).
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

**Status**: version 0.1.0, pre-alpha. Iteration 1 is nearly done: tasks T1–T4
are done (integration review, corpus-independent tests, adversarial
verification and fixes with a second verification round); the last T4 round
(below) and T5, the final report with new screenshots, are pending. Today the
app has a project page (paths, file explorer, Clausewitz viewer with
structure, source, diagnostics and JSON tabs, image preview, `.mod`
descriptor check and a background "Validate mod" with progress and
cancellation), a read-only localisation table with search and lint, and
placeholder pages for the map, countries and events; these pages and the
localisation read-only notice still use the old roadmap's iteration numbers.
Long tasks run in background thread pools. The app does not modify game or
mod files yet; writing exists in the core and in the `csvloc fromjson` CLI,
and editing from the UI starts in iteration 2. The Qt-free core provides
lossless encoding detection (cp1252, UTF-8, UTF-16 with or without BOM,
repeated BOMs), a lossless Clausewitz parser with a format-preserving edit API,
a lossless CSV model with lint and a localisation database that merges folders
the way the game does, `.mod` descriptor handling, whole-mod validation and
cooperative cancellation. Still to come in the last T4 round: UTF-16 warnings
in `clausewitz check`, repeated BOMs in `parse_file`, a public API that tells
the viewer where each tree node ends, freeing a large file's tree off the UI
thread and UTF-16 labels in the UI.

**Roadmap**: iterations 2 to 10 in
[docs/diseno/wizard.md](docs/diseno/wizard.md) (Spanish), which replaces the
roadmap in ARCHITECTURE.md. The UI will move to 7 rooms on top of a vanilla +
mod virtual file system with transactional saving and undo, and will cover 15
capabilities: `.mod` generation, countries, provinces, land units, decisions,
an interface (`.gui`/`.gfx`) suite, events, starting wars, casus belli,
bookmarks, governments, naval units, cultures, regions and a new-map workshop
(procedural generation in the style of Azgaar's Fantasy Map Generator, or
bitmap import).

**Requirements**: Python 3.10+, PySide6 ≥ 6.5, numpy ≥ 1.24, Pillow ≥ 10. On
Python 3.10 and 3.11, PySide6 must be older than 6.12: 6.12.0 releases extra
references to `None`, `True` and `False`, which crashes those Python versions
("Fatal Python error: none_dealloc"); `requirements.txt` and `pyproject.toml`
already pin it. Tested with Python 3.13 + PySide6 6.12 and Python 3.10 +
PySide6 6.11.3.

```bash
PYTHONPATH=src python3 -m vic2studio                    # run from source
pip install -e . && vic2studio                          # or install, then run
QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" \
    python3 -m unittest discover -s tests               # 561 tests, 3 skipped without a corpus
VIC2_CORPUS="/path/to/vanilla:/path/to/mod" ...         # enable real-corpus tests (561 OK)
PYTHONPATH=src python3 -m vic2studio.core.clausewitz check /path/to/mod --lang en
PYTHONPATH=src python3 -m vic2studio.core.csvloc check /path/to/mod/localisation
python3 tools/screenshot.py --out capturas --lang all   # offscreen screenshots
```

Some tests measure UI pauses and may fail on a busy machine; rerun them before
treating them as broken. `clausewitz check` exits with 1 when there are
errors; `csvloc check` exits with 1 on errors (or warnings with `--strict`)
and 2 when a path cannot be read.

**Licences and data**: the app and the corpus tests read game files from the
user's installation at runtime. The repository still holds some vanilla
content: the six `common/countries/` files of the test sample
(`tests/fixtures/shago_mod_min`, from the user's mod) are based on vanilla
country files (party definitions and unit name lists), and two of the old
screenshots in `docs/capturas/` show vanilla files; the screenshots will be
replaced in T5. The project's own code has no licence yet. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the MIT licence of
Azgaar's Fantasy Map Generator and [ARCHITECTURE.md](ARCHITECTURE.md)
(Spanish) for the design.
