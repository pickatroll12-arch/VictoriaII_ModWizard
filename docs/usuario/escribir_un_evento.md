# Escribir un evento

**Dónde:** Eventos › Eventos, pestaña «Studio».

El Event Studio enseña cada evento como el juego lo pintaría (la vista previa, en español o en inglés) y lo edita
por tarjetas. El script se escribe solo; si prefieres, «Ver el código» abre el archivo en su línea.

## Crear el evento

1. Pulsa **«Nuevo»** y elige «Desde la plantilla» (un evento de país vacío) o «Basado en» otro evento.
2. El Studio le da un id libre del rango del proyecto y un archivo en `events/`.

## Rellenarlo

- **Cabecera e imagen.** Título y descripción en español y en inglés. La imagen se elige de las del juego o se
  importa (PNG o JPG): el Studio la convierte al formato del juego.
- **Condiciones** (`trigger`). Se construyen con frases («el país es…», «tiene la tecnología…») y se combinan con
  Y, O y NO.
- **Tiempo medio hasta dispararse (MTTH).** En meses o días, con modificadores que lo alargan o lo acortan.
  Un evento que solo lanza otro evento o una decisión (`is_triggered_only`) no necesita MTTH.
- **Nada más dispararse** (`immediate`). Efectos que ocurren antes de elegir opción.
- **Opciones.** «Añadir opción» crea A, B, C…; cada una lleva su texto en los dos idiomas, sus efectos y la
  probabilidad de que la IA la elija. Se reordenan con Subir y Bajar.

## Decisiones

**Eventos › Decisiones** funciona igual: «Cuándo aparece» (`potential`), «Cuándo se puede tomar» (`allow`), «Qué
hace» (`effect`) e «Interés de la IA». Una decisión puede lanzar tu evento con el efecto `country_event`.

## Si el archivo tiene errores

Un archivo de eventos con una llave sin cerrar se abre solo como texto, con el error señalado. Si lo que falta es
la llave del final, el botón «Añadir } al final» lo arregla.

## Comprueba en el juego

- La decisión aparece en la pestaña de decisiones cuando se cumple «Cuándo aparece».
- Al tomarla, o al cumplirse el MTTH, el evento se dispara con su título, su texto, sus opciones y su imagen.
