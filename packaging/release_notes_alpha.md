**Victoria II Mod Studio 0.1.0, alfa.** Versión de prueba con lo hecho hasta la iteración 3. No es una versión
estable: haz una copia de tu mod antes de usarla.

## Qué funciona

- **Proyecto**: Inicio (juego base y mods de `<juego>/mod`), Descriptor `.mod`, Archivos (explorador y vista
  previa de scripts, imágenes y CSV), **Validación** (F7, con línea base, arreglos de un clic y «¿Por qué?») y
  Cambios pendientes.
- **Textos**: todos los textos del juego y del mod, editables y sincronizados (si gana el juego, se escribe en
  `00_<prefijo>_overrides.csv`; `text.csv` no se copia nunca), pendientes de traducir y los CSV del mod.
- **Ctrl+K**: busca países, provincias, partidos, culturas, eventos, decisiones y textos por id o por nombre.
- Guardar todo o nada con diario, deshacer y rehacer, autoguardado y recuperación tras un corte.
- Español e inglés, con cambio de idioma en vivo.

Las salas Mapa, Naciones, Guerra, Eventos e Interfaz enseñan qué harán y en qué iteración llegan (4 a 9).

## Seguridad de tus archivos

El Studio solo escribe en la carpeta del mod y en su `.mod`, nunca en el juego base. Antes de sobrescribir un
archivo guarda su `.bak` y, la primera vez, el original en `<mod>/.vic2studio/originals/`. Lo que manda a la papelera
va a `<mod>/.vic2studio/trash/`.

## Instalación

- **Windows 10/11 (64 bits)**: descomprime `vic2studio-0.1.0-windows-amd64.zip` y abre
  `Victoria II Mod Studio.exe`. El ejecutable no está firmado: si Windows SmartScreen avisa, pulsa «Más
  información» y «Ejecutar de todas formas».
- **Linux (x86_64, glibc 2.35 o posterior: Ubuntu 22.04, Debian 12, Fedora 36 o más nuevos)**: descomprime
  `vic2studio-0.1.0-linux-x86_64.tar.gz` y ejecuta `Victoria II Mod Studio/Victoria II Mod Studio`. Si no abre la
  ventana, instala las bibliotecas de X11 de Qt: `sudo apt install libxcb-cursor0 libxkbcommon-x11-0` (Debian y
  Ubuntu). El lanzador `vic2studio.desktop` va dentro de la carpeta.

Cada paquete se prueba al construirse: arranca la ventana y comprueba que tiene todos sus textos en los dos idiomas.

---

**English.** Alpha build of Victoria II Mod Studio 0.1.0 with everything up to iteration 3: project hall
(home, `.mod` descriptor, files, validation with a baseline, one-click fixes and a conflict explainer, pending
changes), editable and synchronised localisation, Ctrl+K search, all-or-nothing journaled saving, undo and crash
recovery, in Spanish and English. It only ever writes to the mod folder and its `.mod`, keeping `.bak` copies and
the originals. Windows: unzip and run the `.exe` (unsigned: SmartScreen may ask). Linux: untar and run the binary;
if no window appears, install `libxcb-cursor0` and `libxkbcommon-x11-0`. Back up your mod before using an alpha.
