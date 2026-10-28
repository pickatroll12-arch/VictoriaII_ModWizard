# Unidades (`unit`)

Unidades terrestres y navales de units/<id>.txt, un tipo por archivo. La variante por «type» decide los campos de combate. Se activan con activate_unit en tecnologías e invenciones.

- **Archivos:** `units/{id}.txt`
- **Disposición:** un archivo por registro
- **Identificador:** el nombre del archivo
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `war:units`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `icon` | entero | — | no | Icono |
| `type` | uno de: land, naval | — | no | Tipo. Terrestre o naval: decide qué campos se muestran. |
| `sprite` | palabra | — | no | Sprite |
| `active` | sí o no | — | no | Activa |
| `unit_type` | uno de: infantry, cavalry, support, special, big_ship, light_ship, transport | — | no | Categoría |
| `floating_flag` | sí o no | — | no | Bandera flotante |
| `priority` | entero | — | no | Prioridad |
| `max_strength` | entero | — | no | Fuerza máxima |
| `default_organisation` | entero | — | no | Organización inicial |
| `maximum_speed` | número decimal | — | no | Velocidad máxima |
| `weighted_value` | número decimal | — | no | Valor ponderado |
| `build_time` | entero | — | no | Tiempo de construcción |
| `build_cost` | bloque build_cost · claves del catálogo «goods»: número decimal | — | no | Coste de construcción |
| `supply_consumption` | número decimal | — | no | Consumo de suministros |
| `supply_cost` | bloque supply_cost · claves del catálogo «goods»: número decimal | — | no | Coste de suministro |

### Campos según «type» = land

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `sprite_override` | palabra | — | no | Sprite alternativo |
| `sprite_mount` | palabra | — | no | Montura del sprite |
| `sprite_mount_attach_node` | palabra | — | no | Nodo de la montura |
| `primary_culture` | sí o no | — | no | Solo cultura principal |
| `reconnaissance` | entero | — | no | Reconocimiento |
| `attack` | número decimal | — | no | Ataque |
| `defence` | entero | — | no | Defensa |
| `discipline` | número decimal | — | no | Disciplina |
| `support` | número decimal | — | no | Apoyo |
| `maneuver` | entero | — | no | Maniobra |
| `siege` | entero | — | no | Asedio |

### Campos según «type» = naval

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `naval_icon` | entero | — | no | Icono naval |
| `sail` | sí o no | — | no | A vela |
| `capital` | sí o no | — | no | Buque capital |
| `colonial_points` | entero | — | no | Puntos coloniales |
| `can_build_overseas` | sí o no | — | no | Construible en ultramar |
| `min_port_level` | entero | — | no | Nivel de puerto mínimo |
| `limit_per_port` | entero | — | no | Límite por puerto |
| `supply_consumption_score` | entero | — | no | Puntuación de suministro |
| `hull` | entero | — | no | Casco |
| `gun_power` | entero | — | no | Potencia de fuego |
| `fire_range` | número decimal | — | no | Alcance |
| `evasion` | número decimal | — | no | Evasión |
| `torpedo_attack` | entero | — | no | Ataque de torpedos |
| `transport` | sí o no | — | no | Transporte |
| `move_sound` | palabra | — | no | Sonido al mover |
| `select_sound` | palabra | — | no | Sonido al seleccionar |

## Vistas

- `war:land`: Unidades terrestres
- `war:naval`: Unidades navales

## Claves de texto

- `{id}` en localisation/00_<prefijo>_units.csv
- `{id}_short` en localisation/00_<prefijo>_units.csv

## Compañeros

- Muestra qué tecnología o invención la activa (activate_unit).
- Al crear una naval, ofrece su lista de nombres en los países (unit_names).

## Ejemplo mínimo

```text
my_unit = {
	type = land
	active = yes
	unit_type = infantry
	priority = 1
	max_strength = 3
	default_organisation = 30
	maximum_speed = 4
	build_time = 90
	attack = 2
	defence = 2
}
```
