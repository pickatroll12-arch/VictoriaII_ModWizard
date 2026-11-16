# Crear un mapa nuevo

**Dónde:** Mapa › Taller de mapas.

El taller hace un mapa entero para Victoria II: provincias, terreno, ríos, estados, continentes, climas, dueños,
población, recursos, nombres y las texturas del mapa. Lo genera o lo importa, y lo exporta al mod **en una sola
operación**, que se deshace con un solo Ctrl+Z.

> **Hazlo en un mod de prueba o en un mod nuevo.** El taller reemplaza el mapa y la historia de provincias del mod.
> Lo que el mod tenía en esas carpetas va a la papelera del proyecto, no se borra, pero conviene no mezclarlo con
> un mod que ya juegas.

## 1. ¿Qué quieres hacer?

**Nivel:**

- **Solo mapa:** un mapa nuevo para los países que ya existen. Sus TAG se reparten la tierra (o la dejas sin
  dueños, con «Mapa base»).
- **Mundo:** además del mapa, **países, culturas y grupos culturales nuevos**, cada país con sus cinco banderas,
  sus partidos, su gobierno y su religión.
- «Sobre vanilla» (añadir tierra al mapa existente) todavía no está disponible.

**Origen:**

- **Generarlo** desde una plantilla de relieve (continentes, archipiélago, pangea…) y una semilla.
- **De un mapa de alturas** (PNG en escala de grises).
- **Importar bitmaps:** tus `provinces.bmp`, `definition.csv`, `terrain.bmp`, `rivers.bmp`… Lo que no traigas se
  reconstruye, y la tabla «Lo que falta se reconstruye» dice de dónde sale cada cosa.
- **Importar un JSON de Azgaar's Fantasy Map Generator** (en FMG: «Export to JSON → Full»). Sus provincias pasan a
  ser estados y, en «Mundo», sus estados pasan a ser países con su nombre y su capital.

## 2. Ajustar o ir directo

**«Generación rápida»** lo hace todo con los valores por defecto y salta a la revisión. Si prefieres ajustar, cada
pantalla tiene su vista previa:

Lienzo (tamaño y semilla) › Relieve › Clima y agua › Terreno › Provincias › Estados, continentes y climas ›
Dueños › Población y economía › Nombres › Estrechos y detalles › Revisión y exportación.

- El tamaño por defecto es el de vanilla, **5616×2160**. Otros tamaños se admiten en múltiplos de 24, con aviso.
- En **Dueños**, con «Mundo», eliges cuántos países y grupos culturales nuevos quieres; la galería enseña la
  bandera principal de cada país.
- Cambiar una pantalla regenera solo desde ella: cambiar los países no toca los archivos del mapa.
- Cada edición en la vista previa (subir una isla, mover una frontera) se deshace con Ctrl+Z dentro del taller.

## 3. Revisión y exportación

- **Problemas:** cada uno con «¿Por qué?» y, si se puede, «Arreglar». Los errores impiden exportar.
- **Plan:** cada archivo que se crea, se modifica, se reemplaza o va a la papelera.
- **«Exportar al mod»** lo aplica todo en una transacción. Después, **guarda** (Ctrl+S).

## 4. Después de exportar

- Borra la carpeta `map/cache` del mod (y la de tu carpeta de usuario del juego, si existe), para que el juego no
  use el mapa anterior.
- **Valida (F7).** La exportación no debe dejar errores nuevos.
- Repasa el mapa en **Mapa › Mundo (provincias)**: los modos de mapa ya ven el mapa nuevo.

## Comprueba en el juego

- El mapa carga, eliges un país con tierra y juegas un mes sin errores.
- Con «Mundo», los países nuevos salen en el selector con sus banderas, y uno no civilizado puede
  occidentalizarse.
- La lista completa de lo que conviene mirar está en [comprobacion_en_juego.md](comprobacion_en_juego.md).
