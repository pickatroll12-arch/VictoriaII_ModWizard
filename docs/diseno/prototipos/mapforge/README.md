# Prototipos del taller de mapas

Scripts de estudio con los que se midió el diseño del taller de mapas (`docs/diseno/wizard.md`, §18). No forman parte de la aplicación ni de las pruebas: no se instalan y `unittest discover -s tests` no los recorre. Se guardan para que cada cifra de §18 se pueda repetir y para que la iteración 9a parta de código que ya funciona.

## Qué hay en cada carpeta

| Carpeta | Qué mide o prueba | Citado en §18 como |
|---|---|---|
| `r1-format/scripts/` | Formato real del mapa de Heart of Darkness 3.04 sobre la instalación: cabeceras BMP/DDS/TGA, orientación, envoltura, terreno y ríos, `positions.txt`, regiones y adyacencias, referencias a ids fuera de `map/`, colormaps, historias, países y localización. `m01`–`m15`, con `common.py` | R1 |
| `r2-azgaar/proto/` | Estudio de Azgaar's Fantasy Map Generator (FMG) portado a numpy: rejilla, relieve con plantillas, clima, hidrología, biomas, partición, nombres con cadenas de Markov y rasterización | R2 |
| `r2-azgaar/scripts/` | Medidas del corpus para la correspondencia FMG → Victoria II y `crawl.py`, que descargó el código de FMG para estudiarlo (el código descargado no está en el repositorio) | R2 |
| `design/proto/` | Prototipos del diseño. `p0`–`p6` son la versión 1; `p7`–`p10` y `mf_lib.py` son la versión 2, rehecha tras la verificación adversarial. Cuando p1 y p7 discrepan, manda p7 | [p0]–[p10] |
| `verify/scripts/` | Comprobaciones independientes del verificador adversarial (`v01`–`v18`) sobre vanilla y sobre la salida de los prototipos | revisión de §18 |

Los más útiles para empezar la 9a:

- `design/proto/p7_pipeline_v2.py`: el pipeline completo (celdas → ráster → `reconcile` → texturas y textos). Por ejemplo, `python3 -I p7_pipeline_v2.py 5616 2160 60000 11 <salida> --install <vanilla> --scale 4` hace la vista previa en unos 2 s.
- `design/proto/mf_lib.py`: posiciones, estrechos, perfil de la instalación, terreno por (estado, categoría), ríos con 0/1, DDS con la cabecera de vanilla y codificador DXT3.
- `design/proto/p8_import_e2e.py`: importación de extremo a extremo desde los bitmaps de una instalación.
- `design/proto/p9_worker_ui.py`: por qué el cálculo va en un proceso trabajador y no en un hilo.

## Cómo se ejecutan

- Python 3.10 o posterior, numpy y Pillow (las mismas dependencias que la aplicación). Las cifras de §18 se tomaron con Python 3.13, numpy 2.5 y Pillow 12.3 en 4 CPU compartidas.
- Casi todos reciben por argumento la carpeta de la instalación y la de salida; la cabecera de cada script dice su uso. Algunos de `verify/scripts/` y `p9_worker_ui.py` tienen la ruta de la instalación escrita como `/home/user/corpus/vanilla`: cámbiala por la tuya. `r1-format/scripts/common.py` lee `VIC2_VANILLA` e importa el parser desde el `src/` del repositorio.
- Escribe la salida fuera del repositorio. Los scripts solo leen la instalación; nunca la modifican.

## Datos y licencias

- **Paradox.** No hay ningún dato del juego en esta carpeta: los scripts leen la instalación del usuario en tiempo de ejecución. Se comprobó que ninguna línea de 40 caracteres o más de los archivos de texto de vanilla aparece en estos scripts.
- **FMG.** Varios scripts portan algoritmos de Azgaar's Fantasy Map Generator, que es MIT (© 2017-2024 Max Haniyeu). El texto de la licencia está en `THIRD_PARTY_NOTICES.md`, en la raíz del repositorio. De FMG solo se incluye texto de la plantilla de relieve «continents» (en `p1`, `p7` y `bench.py`); no hay cargas heráldicas SVG, imágenes ni bases de nombres.
