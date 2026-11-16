**Victoria II Mod Studio 0.1.0, alfa (iteración 10).** Editor visual de mods de Victoria II con todo lo hecho
hasta la iteración 10. No es una versión estable: **prueba primero con una copia de tu mod.**

## Descargas

| Archivo | Para |
|---|---|
| `VictoriaIIModStudio-0.1.0-setup.exe` | **Windows 10/11, 64 bits.** Instalador para tu usuario, sin permisos de administrador |
| `Victoria_II_Mod_Studio-0.1.0-x86_64.AppImage` | **Linux x86_64** con glibc 2.35 o posterior (Ubuntu 22.04, Debian 12, Fedora 36 o más nuevos) |
| `SHA256SUMS.txt` | Sumas para comprobar las descargas |

- **Windows:**
  1. Ejecuta el instalador. No está firmado, así que si SmartScreen avisa, pulsa «Más información» y después
     «Ejecutar de todas formas».
  2. Se instala en `%LOCALAPPDATA%\Programs\Victoria II Mod Studio`, con un acceso en el menú Inicio.
  3. Se desinstala desde «Aplicaciones instaladas». Desinstalar no toca ni tus mods ni tus preferencias.
- **Linux:**
  1. `chmod +x Victoria_II_Mod_Studio-0.1.0-x86_64.AppImage`, y después ábrelo.
  2. Si no arranca por falta de FUSE, instala `libfuse2` o ejecútalo con `--appimage-extract-and-run`.
  3. Si no abre la ventana, instala las bibliotecas X11 de Qt: `sudo apt install libxcb-cursor0
     libxkbcommon-x11-0` en Debian y Ubuntu.

Cada paquete se prueba al construirse: se abre la ventana, se comprueba que tiene todos sus textos en los dos
idiomas y que el trabajador del taller de mapas responde, y se cierra. En Windows también se instala, se abre y se
desinstala.

## Qué trae

- **Proyecto:**
  - Inicio, con «¿Qué quieres hacer?»;
  - descriptor `.mod` y explorador de archivos;
  - **Validación** (F7), con línea base, arreglos de un clic y «¿Por qué?»;
  - cambios pendientes;
  - **Exportar a zip** (Ctrl+E): un zip limpio, sin la carpeta del Studio, sin `.bak` y sin temporales.
- **Textos:** los del juego y los del mod, editables y sincronizados, con los pendientes de traducir.
- **Mapa:**
  - modos de mapa y brocha de provincias;
  - regiones, continentes, climas y estrechos;
  - el **taller de mapas**: «Solo mapa» y «Mundo» (países, culturas y banderas nuevas), generado o importado de
    bitmaps, de un mapa de alturas o de un JSON de Azgaar's Fantasy Map Generator.
- **Naciones:** «Nuevo país…», la ficha del país con sus banderas, y el editor de gobiernos, culturas, unidades y
  más.
- **Guerra:** «Nueva guerra…», diplomacia inicial y casus belli.
- **Eventos:** el Event Studio, con eventos y decisiones y un constructor de condiciones y efectos.
- **Interfaz:** ventanas `.gui` y sprites `.gfx`.
- **En todas las salas:**
  - Ctrl+K para buscarlo todo;
  - guardado todo o nada con diario;
  - deshacer y rehacer;
  - recuperación tras un corte;
  - español e inglés.

La guía de uso está en `docs/usuario/README.md`, dentro del código fuente. La lista de lo que hay que comprobar
dentro del juego está en `docs/usuario/comprobacion_en_juego.md`.

## Seguridad de tus archivos

El Studio solo escribe en la carpeta del mod y en su `.mod`, nunca en el juego base. Antes de sobrescribir un archivo
guarda su `.bak` y, la primera vez, el original en `<mod>/.vic2studio/originals/`.

## Limitaciones conocidas

- **El arranque** tarda unos 4 s con el índice en caché. El objetivo es 3 s.
- **«Sobre vanilla»**, que añadiría tierra a un mapa existente, todavía no está.
- **Sin probar todavía en una partida real:** que el juego cargue lo que genera el Studio. Lo valida la lista de
  comprobación.

---

**English.** Alpha build of Victoria II Mod Studio 0.1.0, with everything up to iteration 10. It covers the
project, text, map (including the map forge, with FMG import), nations, war, events and interface halls, adds
export-to-zip, and comes with journaled saving, undo, crash recovery, and Spanish and English.

- **Windows:** run the setup `.exe`. It is a per-user install and needs no admin rights. It is unsigned, so
  SmartScreen may ask before it runs.
- **Linux:** `chmod +x` the AppImage and run it. If FUSE is missing, use `--appimage-extract-and-run`.

The Studio only ever writes to the mod folder and its `.mod`. Back up your mod before using an alpha.
