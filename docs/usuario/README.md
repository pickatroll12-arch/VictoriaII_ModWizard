# Guía de usuario de Victoria II Mod Studio

Esta guía cuenta cómo hacer con el Studio las cosas que más se hacen en un mod de Victoria II (Heart of Darkness
3.04). Cada flujo tiene su página, con los pasos en orden y lo que conviene comprobar.

| Flujo | Dónde se hace | Página |
|---|---|---|
| Crear un país | Naciones › Países › «Nuevo país…» | [crear_un_pais.md](crear_un_pais.md) |
| Repartir provincias | Mapa › Mundo (provincias), con la brocha | [repartir_provincias.md](repartir_provincias.md) |
| Montar una guerra de inicio | Guerra › Guerras de inicio › «Nueva guerra…» | [guerra_de_inicio.md](guerra_de_inicio.md) |
| Escribir un evento | Eventos › Eventos › «Nuevo» | [escribir_un_evento.md](escribir_un_evento.md) |
| Crear un mapa nuevo | Mapa › Taller de mapas | [crear_un_mapa.md](crear_un_mapa.md) |
| Exportar y compartir el mod | Proyecto › Validación › «Exportar a zip…» (Ctrl+E) | [exportar_y_compartir.md](exportar_y_compartir.md) |

Y una lista aparte para cuando pruebes el mod en el juego:
[comprobacion_en_juego.md](comprobacion_en_juego.md).

## Antes de empezar

### Elegir el juego y el mod

En **Proyecto › Inicio**:

1. Pulsa «Elegir carpeta…» en **Juego base** y elige la carpeta de Victoria II. El Studio **nunca escribe en
   ella**: es de solo lectura.
2. En **Tu mod** salen los mods de la carpeta `mod` del juego. Elige uno, o pulsa «Crear mod nuevo» (carpeta,
   descriptor y carpetas básicas, sin copiar el juego base).

> **Prueba primero en una copia.** Mientras aprendes, trabaja sobre un mod de prueba, no sobre el que juegas.

### Lo que hay que saber del Studio

- **Siete salas.** Proyecto, Textos, Naciones, Mapa, Guerra, Eventos e Interfaz, en la barra de arriba
  (Ctrl+1 … Ctrl+7). Cada sala tiene sus secciones a la izquierda.
- **Buscar (Ctrl+K).** Escribe un TAG, un id de provincia, un nombre o el nombre de una sección.
- **Nada se escribe hasta que guardas (Ctrl+S).** Los cambios se ven al momento, pero el disco no cambia hasta
  guardar. El botón «Guardar» dice cuántos archivos tienen cambios, y **Proyecto › Cambios pendientes** los enseña
  uno a uno, con su diff.
- **Deshacer (Ctrl+Z) y rehacer (Ctrl+Y).** Cada acción, por grande que sea (un país entero, un mapa nuevo), es un
  solo paso. El botón del reloj abre el historial.
- **Del juego al mod, solo lo que cambias.** Si editas algo que está en el juego base, el Studio copia ese archivo
  al mod en el sitio que el juego espera. Lo que no tocas se queda igual, byte a byte.
- **Validar (F7).** **Proyecto › Validación** revisa el mod entero. Los problemas que ya trae el juego base se
  marcan como heredados y se ocultan por defecto. Muchos problemas tienen un botón «Arreglar» y un «¿Por qué?» que
  explica qué pasaría en el juego.
- **Idioma.** El desplegable de arriba a la derecha cambia entre español e inglés sin reiniciar. Los textos del mod
  se escriben en los dos idiomas cuando el formulario lo pide.

### Si algo sale mal

- **El Studio se cerró a mitad de guardar.** Al volver a abrir el mod, ofrece terminar o deshacer el guardado. El
  mod nunca queda a medias.
- **Cambiaste un archivo con otro programa.** Al volver al Studio te lo dice y te deja quedarte con tu versión o
  recargar la del disco.
- **Dos ventanas del Studio con el mismo mod.** La segunda lo abre en solo lectura.
- **Un archivo tiene un error de sintaxis.** El Studio lo abre como texto, señala la línea y, si falta una llave al
  final, ofrece añadirla.
