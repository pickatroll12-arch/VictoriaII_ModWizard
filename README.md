# Victoria II Mod Studio

Aplicación de escritorio para **Windows y Linux** que permite crear, editar y
gestionar mods de **Victoria II** (incluidas *A House Divided* y *Heart of
Darkness*) de forma visual, sin editores de texto externos.

Incluye su propio motor de lectura y escritura de los archivos del juego
(sintaxis de llaves `{}` de Clausewitz y los `.csv` de localización), que
conserva cada byte de lo que no se edita: comentarios, tabulaciones, CRLF y la
codificación Windows-1252 que exige el juego.

La interfaz imita la estética de Victoria II (bronce envejecido, pergamino,
terciopelo, madera, serifas clásicas) con texturas generadas por código, y se
puede usar en **español o inglés**, cambiando de idioma en tiempo real.

> Proyecto independiente, sin relación con Paradox Interactive. No incluye ni
> redistribuye gráficos, fuentes ni textos del juego: la aplicación trabaja
> sobre la copia de Victoria II que tenga instalada cada usuario.

## Módulos

1. **Proyecto y Archivos**: rutas del juego base y del mod, explorador y
   descriptor `.mod`. Lo de vanilla solo se lee; todo se guarda en el mod.
2. **Editor de Mapa**: `provinces.bmp` interactivo con modos de mapa y edición
   de provincias por clic.
3. **Creador de Países**: asistente paso a paso (TAG, colores, banderas `.tga`,
   partidos, historial).
4. **Estudio de Eventos**: eventos y decisiones con triggers, MTTH y opciones.
5. **Localización (CSV)**: editor tabular del formato `;` de Paradox.

## Estado del proyecto

**Iteración 1** (versión 0.1.0, pre-alfa):

- [x] Arquitectura y documentación ([ARCHITECTURE.md](ARCHITECTURE.md)).
- [x] Detección de codificación sin pérdidas y escritura atómica con copia `.bak`.
- [x] Parser Clausewitz `.txt` ⇄ JSON con diagnósticos en ES/EN y CLI `check`/`tojson`.
- [x] Localización CSV ⇄ JSON con linter y CLI `check`/`tojson`/`fromjson`.
- [x] Ventana principal con estética Victoria II, selector ES/EN y navegación
      entre los 5 módulos (Mapa, Países y Eventos muestran de momento lo
      planificado).
- [ ] VFS vanilla + mod, generador `.mod`, editor de localización (iteración 2).
- [ ] Editor de mapa (3), creador de países (4), eventos y decisiones (5),
      ejecutables (6).

La hoja de ruta completa está en [ARCHITECTURE.md](ARCHITECTURE.md#6-hoja-de-ruta-y-riesgos).

## Requisitos

- Python **3.10** o superior.
- [PySide6](https://pypi.org/project/PySide6/) ≥ 6.5 (Qt 6), numpy ≥ 1.24 y
  Pillow ≥ 10 (ver `requirements.txt`).

En Linux pueden venir del gestor de paquetes (en Fedora: `python3-pyside6`,
`python3-numpy`, `python3-pillow`) o de pip:

```bash
python3 -m pip install -r requirements.txt
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

## Pruebas

Las pruebas usan `unittest` de la biblioteca estándar y no necesitan instalar
el paquete:

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
```

`QT_QPA_PLATFORM=offscreen` permite ejecutar las pruebas de interfaz sin
pantalla. Las pruebas de **corpus** recorren mods reales y comprueban, por
ejemplo, que leer y guardar sin cambios produce exactamente los mismos bytes.
Las carpetas se indican en la variable `VIC2_CORPUS`, separadas por `:` en Linux
y por `;` en Windows (`os.pathsep`):

```bash
VIC2_CORPUS="/ruta/Plantilla Mod:/ruta/a/otro/mod" QT_QPA_PLATFORM=offscreen \
    python3 -m unittest discover -s tests -v
```

Sin `VIC2_CORPUS` se usa `../Plantilla Mod` (respecto a la raíz del proyecto)
si existe; si no hay ningún corpus, esas pruebas se omiten.

## Herramientas de línea de comandos

El núcleo no depende de Qt y se puede usar desde la terminal (con
`PYTHONPATH=src` si no está instalado).

### Detectar errores de sintaxis en un mod

```bash
PYTHONPATH=src python3 -m vic2studio.core.clausewitz check "/ruta/a/mi_mod" --lang es
```

Recorre carpetas y archivos e imprime cada problema como
`archivo:línea:columna: severidad: mensaje`: llaves sin cerrar o sobrantes,
claves sin valor, comillas sin cerrar, archivos que no están en Windows-1252…
El resumen sale por la salida de error y el código de salida es 1 si hay
errores, así que sirve en scripts. `--lang en` da los mensajes en inglés.

Salida real sobre un mod del corpus de pruebas:

```text
VSM/decisions/somaliland_shago.txt:1:23: error: El bloque 'political_decisions' abierto en la línea 1 no se cierra (falta '}')
VSM/decisions/zulu_expancionshago.txt:1:23: error: El bloque 'political_decisions' abierto en la línea 1 no se cierra (falta '}')
VSM/decisions/zulu_expancionshago.txt:155:1: info: Esta '}' cierra 'imperio_zulu' (línea 85) pero tiene menos sangría que esa línea: puede que falte una '}' antes
VSM/history/units/1861/HAI_oob.txt:11:14: aviso: El archivo está en UTF-8; Victoria II lo lee como Windows-1252 y mostrará mal los caracteres no ASCII
VSM/history/units/v2dd2.txt:4:5: error: El operador '>' no tiene clave
3927 archivo(s), 3 error(es), 1 aviso(s)
```

Estos errores pasan fácilmente desapercibidos: aquí, dos archivos de
decisiones no cierran el bloque abierto en su primera línea, y
`history/units/v2dd2.txt` resulta ser el texto de un diario de desarrollo
copiado por error en una carpeta de scripts.

### Convertir a JSON

```bash
PYTHONPATH=src python3 -m vic2studio.core.clausewitz tojson "history/countries/GER - Germany.txt" --comments
```

Escribe el árbol en JSON (esquema en
[ARCHITECTURE.md](ARCHITECTURE.md#41-clausewitz-txt-vic2studiocoreclausewitz));
`--comments` incluye los comentarios.

### Localización CSV

```bash
PYTHONPATH=src python3 -m vic2studio.core.csvloc check "/ruta/a/mi_mod/localisation" --lang es
PYTHONPATH=src python3 -m vic2studio.core.csvloc tojson "/ruta/a/mi_mod/localisation/00_mi_mod.csv" > mi_mod.json
PYTHONPATH=src python3 -m vic2studio.core.csvloc fromjson mi_mod.json -o 00_mi_mod.csv
```

`check` (recursivo en carpetas) avisa de filas sin la `x` en la columna 14,
columnas que faltan, claves repetidas, vacías o con espacios, `;` dentro de
comillas (el juego no entiende comillas, así que desplaza columnas), archivos
que no están en Windows-1252 y caracteres que Windows-1252 no puede
representar (este último es el único error; lo demás son avisos).

## Capturas de pantalla

```bash
QT_QPA_PLATFORM=offscreen python3 tools/screenshot.py --out capturas --lang all
```

Genera `capturas/<idioma>_<n>_<página>.png` sin pantalla y con preferencias
temporales (no toca la configuración del usuario). Opciones: `--page`,
`--size 1440x900`, `--mod RUTA`, `--game RUTA`, `--open-file RUTA`.

## Empaquetado

`packaging/` contiene la especificación de PyInstaller (modo *one-folder*) y
los scripts para generar los ejecutables en cada sistema:

```bash
packaging/build_linux.sh            # dist/Victoria II Mod Studio/ + .tar.gz
packaging/build_linux.sh --install  # además lo instala en ~/.local con lanzador
```

```bat
packaging\build_windows.bat         :: dist\Victoria II Mod Studio\ + .zip
```

Por defecto crean un entorno virtual en `build/` e instalan ahí las
dependencias y PyInstaller (requiere conexión); `--system` usa el Python
actual. PyInstaller no compila en cruzado: cada ejecutable se genera en su
sistema.

## Estructura

```text
src/vic2studio/
├── core/        núcleo sin Qt: codificación, E/S, parser Clausewitz, CSV
├── i18n/        traductor y textos es.json / en.json
├── ui/          ventana principal, tema, widgets y páginas de los 5 módulos
├── app.py       punto de entrada de la aplicación
├── settings.py  preferencias (QSettings en formato INI)
└── __main__.py  python -m vic2studio
tests/           pruebas unittest (incluidas las de corpus real)
tools/           utilidades de desarrollo (capturas)
packaging/       PyInstaller y lanzador de Linux
```

El árbol completo, con lo planificado, está en
[ARCHITECTURE.md](ARCHITECTURE.md#5-árbol-de-directorios).

---

## English summary

**Victoria II Mod Studio** is a desktop application (Windows and Linux) for
creating and editing Victoria II mods visually: project and file management
with vanilla + mod inheritance, an interactive province map, a country creation
wizard, an event and decision studio, and a localisation (CSV) editor. Its own
parser reads and writes Clausewitz `.txt` and Victoria II `.csv` files
losslessly (comments, whitespace, CRLF and Windows-1252 are preserved). The UI
mimics the Victoria II look with procedurally generated textures and can switch
between Spanish and English at runtime. It is an independent project, not
affiliated with Paradox Interactive, and ships no game assets.

**Status**: iteration 1 (0.1.0, pre-alpha): architecture, encoding layer,
Clausewitz and CSV parsers with JSON conversion and CLIs, and the main window
prototype with language switching and navigation between the five modules.

**Requirements**: Python 3.10+, PySide6 ≥ 6.5, numpy ≥ 1.24, Pillow ≥ 10.

```bash
PYTHONPATH=src python3 -m vic2studio                    # run from source
pip install -e . && vic2studio                          # or install, then run
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
VIC2_CORPUS="/path/to/mod" ...                          # enable real-corpus tests
PYTHONPATH=src python3 -m vic2studio.core.clausewitz check /path/to/mod --lang en
PYTHONPATH=src python3 -m vic2studio.core.csvloc check /path/to/mod/localisation
```

See [ARCHITECTURE.md](ARCHITECTURE.md) (Spanish) for the design.
