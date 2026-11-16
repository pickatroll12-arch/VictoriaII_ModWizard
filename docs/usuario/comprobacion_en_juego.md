# Comprobación en el juego

Hay reglas del motor de Victoria II que los archivos no demuestran: solo se ven arrancando el juego. El Studio no
las da por supuestas. Cada una está modelada como una **opción explícita** o como un **aviso**, y las pruebas
automáticas cubren sus variantes. Esta lista las reúne todas, junto con las pruebas de flujo («el país nuevo es
jugable en 1836»), para hacerlas una sola vez.

**Cómo usarla:**

- Hazla en un **mod de prueba** sobre una instalación limpia (Heart of Darkness 3.04), nunca en tu mod real.
- Antes de cada arranque, borra `map/cache` del mod y de tu carpeta de usuario del juego.
- Marca cada casilla con ✅ (funciona), ❌ (falla; anota qué ves) o ➖ (no aplica).
- **Tus respuestas fijan los valores por defecto.** Donde una regla tiene dos variantes, la que confirmes pasa a ser
  la opción por defecto del Studio, y la otra se queda como alternativa o desaparece.

## A. Carga de archivos (iteraciones 1–4)

| # | Qué comprobar | Cómo | Si falla | ✅/❌ |
|---|---|---|---|---|
| A1 | `replace_path` también oculta las **subcarpetas** de la ruta (por ejemplo `history/provinces/europe/`) | Pon `replace_path = "history/provinces"` y deja en el mod solo una subcarpeta: las provincias de las otras subcarpetas no deben tener historia | El Studio pasa `replace_recursive` a falso y avisa por subcarpeta | |
| A2 | Si un archivo de `history/pops/<fecha>/` del mod tiene un bloque repetido para la misma provincia, **se suman** las POPs | Dos bloques de la misma provincia con 1 000 POPs cada uno: ¿2 000 o 1 000? | Cambia el aviso de bloques repetidos | |
| A3 | Qué carpeta de `history/pops/` usa cada fecha de inicio (bookmark): la de su fecha o la más reciente anterior | Un bookmark de 1861 sin carpeta `1861.1.1`: ¿hay POPs? | Cambia `bookmark_without_pops` | |
| A4 | El juego carga **todos** los `.gfx` de `interface/`, también uno con nombre nuevo (`interface/<prefijo>_studio.gfx`) | Crea un sprite con «Nuevo sprite…» (Interfaz › Sprites) y úsalo en una ventana: ¿se dibuja? | Los sprites nuevos irían a un `.gfx` existente | |
| A5 | `technologies/` e `inventions/` se cargan desde la lista de carpetas de `technology.txt` | Activa una unidad nueva que copie un archivo de tecnología: ¿aparece la técnica? | Cambia la regla de carga de esas carpetas | |
| A6 | Si una provincia tiene **dos** archivos de historia, gana el primero en orden de carpeta (el Studio avisa de los duplicados) | Copia la historia de una provincia en otra subcarpeta con otro dueño | Cambia qué copia edita el Studio | |
| A7 | El juego **ignora** `.vic2studio/` y los `*.bak` dentro del mod | Arranca con un mod que los tenga: sin errores en los registros | El Studio movería su carpeta fuera del mod | |
| A8 | Los archivos de `history/wars` e `history/diplomacy` con **solo un comentario** no molestan | Exporta un mapa con el taller (las deja así) y empieza una partida | Se escribirían de otra forma | |

## B. Mapa e historia (iteración 5)

| # | Qué comprobar | Cómo | ✅/❌ |
|---|---|---|---|
| B1 | Pintar el dueño de una provincia en 1836.1.1 cambia su dueño en la partida | Mapa › Mundo, brocha «Dueño» sobre una provincia, guarda y arranca | |
| B2 | Un estado nuevo pintado en Mapa › Regiones aparece como estado (nombre y fronteras) | Crea uno con «Nuevo» y «Pintar» | |
| B3 | Un estrecho añadido en Mapa › Estrechos y canales deja cruzar ejércitos | Añade uno y mueve un ejército | |

## C. Países, guerras y diplomacia (iteración 6)

| # | Qué comprobar | Cómo | ✅/❌ |
|---|---|---|---|
| C1 | Un país creado con «Nuevo país…» es **jugable en 1836**, con su bandera y sus provincias | Créalo con territorio, guarda y búscalo en el selector | |
| C2 | Su partido gobernante es válido y, si su gobierno las tiene, **celebra elecciones** | Juega hasta unas elecciones | |
| C3 | Una guerra creada con «Nueva guerra…» que empieza en 1836.1.1 **está activa** al cargar | Diplomacia del juego | |
| C4 | Una alianza añadida en Diplomacia inicial aparece en la ventana de diplomacia | | |

## D. Eventos, decisiones e interfaz (iteraciones 7 y 8)

| # | Qué comprobar | Cómo | ✅/❌ |
|---|---|---|---|
| D1 | Una decisión nueva aparece cuando se cumple su `potential` y se puede tomar con su `allow` | Decisión con «el país es <tu país>» en las dos | |
| D2 | Un evento nuevo se dispara (por MTTH o desde la decisión) con su título, texto, opciones e imagen | | |
| D3 | Una imagen importada para un evento y otra para una decisión se ven bien | | |
| D4 | Un botón movido en una ventana (por ejemplo, la de eventos) aparece en su sitio nuevo y la ventana funciona | Interfaz › Ventanas | |
| D5 | Un sprite nuevo usado en un `iconType` se dibuja | Interfaz › Sprites | |

## E. Taller de mapas (iteraciones 9a y 9b)

Las 28 comprobaciones del diseño (§19.7). Para casi todas basta **un** mapa exportado con «Generación rápida»; las
que piden otra cosa lo dicen.

| # | Qué comprobar | ✅/❌ |
|---|---|---|
| E1 | Un mapa de 5616×2160 con «Solo mapa → Repartir entre los TAG existentes» carga, deja elegir un país con tierra y se juega un mes sin errores; con «Dueños: Mapa base» (sin dueños) carga hasta el selector | |
| E2 | Tras exportar, borrar `map/cache` del mod y de la carpeta de usuario basta para que el juego use el mapa nuevo | |
| E3 | Un TAG existente sin tierra, con la capital en una provincia de otro país, no da error y se puede liberar | |
| E4 | Los archivos OOB vacíos escritos en las rutas que citan las historias (con `history/units` reemplazada) se aceptan sin errores ni unidades fantasma | |
| E5 | Con `history/wars` e `history/diplomacy` reemplazadas y vacías, el juego empieza sin guerras ni relaciones y no se cierra | |
| E6 | Un mapa de **2808×1080** (Lienzo › tamaño) carga y sus texturas (`colormap`, `colormap_water` y el minimapa) se ven alineadas | |
| E7 | `colormap_no_shadow.dds` (DXT3 propio) y `colormap_political.dds` regenerado se cargan sin artefactos | |
| E8 | El terreno que enseña el juego coincide con la categoría mayoritaria de la provincia; un `terrain =` en la historia gana sobre `terrain.bmp` | |
| E9 | Los índices de `terrain.bmp` aprendidos de tu instalación se dibujan con texturas normales, sin teselas moradas | |
| E10 | Los ríos se dibujan continuos, más anchos río abajo, y desembocan bien en la costa | |
| E11 | Ninguna provincia cruza el borde este-oeste, y los ejércitos y flotas pasan de un borde al otro (el mapa da la vuelta) | |
| E12 | Los lagos generados se dibujan bien y no son navegables desde el océano | |
| E13 | Los estrechos generados dejan cruzar ejércitos; un `adjacencies.csv` sin filas es válido | |
| E14 | El puerto aparece en las provincias costeras y se puede construir base naval | |
| E15 | Los puntos de `positions.txt` (fuerte, fábrica, construcción) salen separados de la unidad y dentro de la provincia | |
| E16 | Los nombres de las provincias se leen sin solaparse en el zoom por defecto | |
| E17 | `definition.csv` y los CSV de localización generados no crean provincias fantasma ni claves vacías | |
| E18 | Los nombres de provincia y estado del taller (`00_<prefijo>_map.csv`) ganan sobre las mismas claves en otros CSV del mod; si no, hace falta el arreglo de `forge_loc_shadowed` | |
| E19 | Las historias con nombre de archivo ASCII se cargan por su id y el nombre con acentos sale de la localización | |
| E20 | Con «Mundo», un país generado (partidos, partido gobernante, reformas y técnicas de plantilla) es jugable en 1836 y celebra elecciones si su gobierno las tiene | |
| E21 | Las 5 banderas procedurales (TAG, `_communist`, `_fascist`, `_monarchy`, `_republic`) se ven al cambiar de gobierno | |
| E22 | Un grupo cultural nuevo usa los gráficos de unidades y retratos del grupo del que toma `unit` y `leader` | |
| E23 | Un continente con nombre nuevo carga y se localiza; los continentes con nombres de tu instalación conservan sus efectos sobre los tipos de POP | |
| E24 | *(Pendiente: «Sobre vanilla» aún no existe.)* Las provincias nuevas creadas desde `max_provinces` se pueden colonizar u ocupar | ➖ |
| E25 | Un mapa con muchas más provincias que vanilla (por ejemplo 6 000) carga | |
| E26 | `common/countries.txt` de «Mundo» conserva los TAG existentes, `REB` y `dynamic_tags`: los dominios dinámicos siguen funcionando | |
| E27 | Las POPs generadas (sin artesanos, oficinistas ni capitalistas fuera de las capitales civilizadas) no dan paro ni militancia anómalos el primer año | |
| E28 | La cámara de la fecha de inicio (`bookmarks.txt`) centra la vista en el país elegido | |
| E29 | Un país «Mundo» no civilizado puede occidentalizarse | |
| E30 | Un mapa importado de Azgaar's Fantasy Map Generator carga, y sus países tienen los nombres de los estados de FMG | |

## F. Exportación (iteración 10)

| # | Qué comprobar | ✅/❌ |
|---|---|---|
| F1 | El zip de «Exportar a zip…», descomprimido en la carpeta `mod` de una instalación limpia, aparece en el lanzador y la partida carga | |
| F2 | Con «Dejar fuera las copias idénticas al juego», el mod se comporta igual que sin limpiar | |
| F3 | Un mapa de tamaño distinto de 5616×2160 (por ejemplo 2808×1080) carga sin errores (ver E6) | |

## Cuando la tengas

Pásame la lista con las marcas y lo que viste en las que fallen. Con eso:

- las opciones confirmadas pasan a ser el valor por defecto;
- los avisos de lo que funciona se quitan o bajan a información;
- lo que falle se arregla, con una prueba que lo cubra.
