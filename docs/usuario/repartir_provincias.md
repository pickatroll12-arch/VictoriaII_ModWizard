# Repartir provincias

**Dónde:** Mapa › Mundo (provincias).

El mapa enseña el mundo **en la fecha de trabajo**: lo que ves y lo que escribes en la historia de las provincias
corresponde a esa fecha. Arriba eliges la fecha (una fecha de inicio de las que define el mod, o cualquier otra
dentro de `start_date`–`end_date` de `defines.lua`) y el modo de mapa (político, cultura, religión, población,
recursos, terreno, estados, continentes, climas, infraestructura, núcleos o ids de provincia).

## Pasar provincias a otro país con la brocha

1. Elige la fecha, por ejemplo `1836.1.1`.
2. Activa la **Brocha** y elige el campo **Dueño**.
3. Escribe el valor a pintar: el TAG del país que recibe las provincias.
4. **Arrastra sobre el mapa.** Cada provincia por la que pasas cambia de dueño. Al soltar se escribe, y el trazo
   entero es un solo paso de deshacer (Ctrl+Z).

Con la misma brocha se pintan el **controlador**, los **núcleos**, el **recurso (RGO)**, la **calidad de vida**, el
**fuerte**, la **base naval**, el **ferrocarril** y el **terreno**.

> Cambiar el dueño no cambia el controlador ni los núcleos. Si quieres que el país nuevo controle y reclame la
> provincia, pinta también «Controlador» y «Núcleos».

## Una provincia concreta

Haz clic en una provincia para ver su ficha: id y nombre, si es de tierra o de mar, su estado, continente, clima y
terreno, su archivo de historia y sus campos en la fecha de trabajo. Si la provincia no tiene archivo de historia,
se crea al editar el primer campo.

## Estados, continentes y climas

- **Mapa › Regiones:** los estados (`region.txt`) y las regiones de mar. «Nuevo» crea un estado y «Pintar» añade
  provincias arrastrando.
- **Mapa › Continentes y climas:** igual, para `continent.txt` y `climate.txt`.
- **Mapa › Estrechos y canales:** los pasos de `adjacencies.csv`. Con tres clics (salida, llegada y la provincia de
  mar que se cruza) se añade uno.

## Comprueba en el juego

- En 1836, las provincias pintadas aparecen con su dueño nuevo.
- Un país que se queda sin provincias no aparece en el selector, y su capital sigue apuntando a una provincia que
  existe.
