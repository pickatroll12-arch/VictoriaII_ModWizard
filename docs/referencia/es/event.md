# Eventos (`event`)

Eventos de país y de provincia de events/*.txt: cuándo se disparan, qué texto enseñan y qué hace cada opción.

- **Archivos:** `events/*.txt`
- **Disposición:** entradas de la raíz de cada archivo con la clave country_event / province_event
- **Identificador:** el campo «id»
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `events:events`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `id` | entero | — | sí | Id. Número único del evento. Los nuevos toman el primer libre del rango del proyecto. |
| `title` | clave de texto (localisation) | — | sí | Título. Clave de texto del título (EVTNAME<id>). Un título en prosa también vale. |
| `desc` | clave de texto (localisation) | — | sí | Descripción. Clave de texto de la descripción (EVTDESC<id>). |
| `picture` | imagen de gfx/pictures/events | — | no | Imagen. gfx/pictures/events/<imagen>.tga, de 521×203. |
| `is_triggered_only` | sí o no | — | no | Solo lo lanza otro evento o decisión. Sin MTTH propio: un evento nuevo nace así para no dispararse en todos los países. |
| `fire_only_once` | sí o no | — | no | Solo una vez por partida |
| `major` | sí o no | — | no | Evento mayor (lo ven todos) |
| `allow_multiple_instances` | sí o no | — | no | Permite varias a la vez |
| `election` | sí o no | — | no | Evento de elecciones |
| `issue_group` | referencia a issue_group | — | no | Grupo de asuntos de la elección |
| `news` | sí o no | — | no | Sale en las noticias |
| `news_title` | clave de texto (localisation) | — | no | Titular |
| `news_desc_long` | clave de texto (localisation) | — | no | Noticia larga |
| `news_desc_medium` | clave de texto (localisation) | — | no | Noticia media |
| `news_desc_short` | clave de texto (localisation) | — | no | Noticia corta |
| `trigger` | bloque de guion (constructor de condiciones o de efectos) | — | no | Condiciones |
| `mean_time_to_happen` | bloque mean_time_to_happen | — | no | Tiempo medio hasta dispararse |
| `immediate` | bloque de guion (constructor de condiciones o de efectos) | — | no | Efectos inmediatos |
| `option` | bloque option | — | sí | Opción |

## Vistas

- `events:events`: Eventos de país
- `events:events`: Eventos de provincia

## Claves de texto

- `EVTNAME{id}` en localisation/00_<prefijo>_events.csv
- `EVTDESC{id}` en localisation/00_<prefijo>_events.csv
- `EVTOPT{letter}{id}` en localisation/00_<prefijo>_events.csv

## Ejemplo mínimo

```text
country_event = {
	id = 200000000
	title = "EVTNAME200000000"
	desc = "EVTDESC200000000"
	is_triggered_only = yes
	option = {
		name = "EVTOPTA200000000"
	}
	option = {
		name = "EVTOPTB200000000"
	}
}
```
