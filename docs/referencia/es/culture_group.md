# Grupos de culturas (`culture_group`)

Grupos de common/cultures.txt: líder gráfico, unidades, unión y si es de ultramar. Contienen las culturas.

- **Archivos:** `common/cultures.txt`
- **Disposición:** grupos de la raíz del archivo
- **Identificador:** la clave del bloque
- **Edición:** se crea, se duplica y se borra desde el Studio

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `leader` | uno de: european, southamerican, russian, arab, asian, indian, nativeamerican, african, polar_bear | — | sí | Retratos de líderes |
| `unit` | referencia a graphical_culture | — | no | Gráficos de unidades |
| `union` | referencia a tag | — | no | País de la unión |
| `is_overseas` | sí o no | — | no | De ultramar |
| *culture* | bloques hijos: culture | — | no | Culturas |

## Claves de texto

- `{id}` en localisation/00_<prefijo>_cultures.csv

## Ejemplo mínimo

```text
my_culture_group = {
	leader = european
}
```
