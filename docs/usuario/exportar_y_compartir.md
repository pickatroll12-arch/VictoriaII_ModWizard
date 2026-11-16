# Exportar y compartir el mod

**Dónde:** Proyecto › Validación › «Exportar a zip…», o **Ctrl+E** desde cualquier sala.

El zip lleva el mod tal como está **guardado**, listo para descomprimir dentro de la carpeta `mod` del juego:

- en la raíz, el descriptor `<nombre>.mod`;
- la carpeta del mod con sus archivos.

Y deja fuera lo que no es del mod:

- la carpeta del Studio, `.vic2studio/` (ajustes del proyecto, diario, papelera, originales y recuperación);
- las copias `*.bak`;
- los temporales (los de un guardado cortado, `~$…`, `*.swp`, `*~`);
- los archivos del sistema (`Thumbs.db`, `desktop.ini`, `.DS_Store`);
- carpetas de control de versiones (`.git`…) y enlaces simbólicos.

El diálogo dice cuántos archivos entran, cuánto ocupan y cuántos se quedan fuera por cada motivo.

## Qué pide antes de exportar

1. **Nada sin guardar.** El zip se hace con lo que hay en disco; si hay cambios sin guardar, guarda primero.
2. **Una validación al día.** Si no has validado o has cambiado algo desde entonces, el botón «Validar» lo hace ahí
   mismo.
3. **Ningún error del mod.** Los errores bloquean la exportación (nunca el guardado). Los problemas heredados del
   juego base no cuentan.
4. **Un destino fuera del mod y del juego.** El zip no puede ir dentro de la carpeta del mod (se metería en sí
   mismo) ni de la del juego (el Studio nunca escribe allí).

## Copias idénticas al juego

«Dejar fuera las copias idénticas al juego» quita del zip los archivos del mod que son iguales byte a byte al del
juego en la misma ruta: no cambian nada y solo ocupan sitio. Las carpetas de `replace_path` se respetan siempre,
porque allí la copia del mod es la única que el juego ve.

Esta limpieza solo afecta al zip: los archivos de tu mod no se tocan.

## Cancelar

La exportación se puede cancelar. Si ya había un zip con ese nombre, se queda como estaba: el zip nuevo se escribe
aparte y solo sustituye al anterior al terminar.

## Comprueba en el juego

Descomprime el zip en la carpeta `mod` de una instalación limpia del juego y comprueba que el lanzador ve el mod y
que la partida carga.
