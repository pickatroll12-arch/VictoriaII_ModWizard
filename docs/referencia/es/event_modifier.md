# Modificadores (`event_modifier`)

Modificadores de common/event_modifiers.txt que los eventos y decisiones aplican a países y provincias: un icono y sus efectos.

- **Archivos:** `common/event_modifiers.txt`
- **Disposición:** un archivo con un bloque por registro
- **Identificador:** la clave del bloque
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `events:modifiers`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `icon` | entero | — | no | Icono |
| *effects* | cualquier clave: número decimal | — | no | Efectos del modificador |

## Claves de texto

- `{id}` en localisation/00_<prefijo>_modifiers.csv
- `{id}_desc` en localisation/00_<prefijo>_modifiers.csv (opcional)

## Ejemplo mínimo

```text
my_event_modifier = {
	icon = 1
	prestige = 1
}
```
