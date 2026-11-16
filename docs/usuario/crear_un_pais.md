# Crear un país

**Dónde:** Naciones › Países › «Nuevo país…».

El asistente «Nuevo país» crea todo lo que un país necesita para ser jugable, en un solo paso de deshacer:

- su línea en `common/countries.txt`, antes de `dynamic_tags`;
- su archivo de país en `common/countries/`, con color, cultura gráfica y partidos;
- su historia en `history/countries/`, con capital, cultura, religión, gobierno, partido gobernante, técnicas y
  alfabetización;
- sus cinco banderas TGA (normal, comunista, fascista, monárquica y republicana);
- sus textos en español e inglés (nombre, adjetivo y partidos).

## Pasos

1. **Identidad.** Escribe el nombre y el adjetivo. El Studio propone un TAG de tres letras libre en tu instalación
   y en tu mod (puedes escribir otro).
2. **Color y banderas.** Elige el color del mapa y las banderas. Con «Colores de uniforme propios» puedes cambiar
   los del uniforme. Más tarde, la ficha del país tiene «Sustituir las 5 banderas».
3. **Gobierno y sociedad.** Gobierno, si es civilizado, alfabetización, pluralidad y valor nacional. Los valores
   iniciales salen del país en el que te basas.
4. **Pueblo.** Cultura principal, culturas aceptadas y religión.
5. **Partidos.** «Un partido por ideología (plantilla)» crea un partido de cada ideología; «Copiar los partidos
   de» los copia de otro país. El partido gobernante tiene que tener una ideología que el gobierno admite: el
   asistente solo ofrece esos.
6. **Tecnologías.** Las técnicas iniciales. Por defecto, las del país modelo.
7. **Territorio y ejército** (opcional). Añade provincias con «Añadir» o con «Elegir en el mapa…»: pasan a ser del
   país nuevo (dueño y controlador, y núcleo si lo marcas). Elige la capital y, si quieres, un ejército inicial.
8. **Revisión.** Enseña cada archivo que se crea o cambia, con su diff. «Crear país» lo aplica. Si marcas «Guardar
   al terminar», además guarda.

## Después

- El país aparece en **Naciones › Países** con su ficha: allí puedes cambiar cualquier campo, sus partidos o sus
  banderas.
- **Valida (F7).** Un país sin provincias no aparece al empezar la partida, pero no es un error: el juego lo trata
  como un país que no existe hasta que se libera o se forma.

## Comprueba en el juego

- El país sale **jugable en 1836** en la pantalla de selección, con su bandera y sus provincias.
- Al cambiar de gobierno, la bandera cambia a la variante correspondiente.
- Si tiene un gobierno con elecciones, las celebra.
