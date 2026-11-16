# Decisiones (`decision`)

Decisiones de decisions/*.txt: cuándo aparecen, cuándo se pueden tomar y qué efecto tienen.

- **Archivos:** `decisions/*.txt`
- **Disposición:** bloques dentro de «political_decisions» en cada archivo
- **Identificador:** la clave del bloque
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `events:decisions`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `picture` | imagen de gfx/pictures/decisions | — | no | Imagen. gfx/pictures/decisions/<imagen>.dds, de 95×95. Si falta, el juego usa la del id. |
| `alert` | sí o no | yes | no | Avisa cuando se puede tomar |
| `news` | sí o no | — | no | Sale en las noticias |
| `news_desc_long` | clave de texto (localisation) | — | no | Noticia larga |
| `news_desc_medium` | clave de texto (localisation) | — | no | Noticia media |
| `news_desc_short` | clave de texto (localisation) | — | no | Noticia corta |
| `potential` | bloque de guion (constructor de condiciones o de efectos) | — | sí | Cuándo aparece |
| `allow` | bloque de guion (constructor de condiciones o de efectos) | — | sí | Cuándo se puede tomar |
| `effect` | bloque de guion (constructor de condiciones o de efectos) | — | sí | Qué hace |
| `ai_will_do` | bloque ai_will_do | — | no | Interés de la IA |

## Claves de texto

- `{id}_title` en localisation/00_<prefijo>_decisions.csv
- `{id}_desc` en localisation/00_<prefijo>_decisions.csv

## Ejemplo mínimo

```text
my_decision = {
	potential = { }
	allow = { }
	effect = { }
}
```
