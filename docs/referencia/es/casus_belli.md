# Casus belli (`casus_belli`)

Motivos de guerra de common/cb_types.txt. Crear uno lo añade al final de peace_order; borrarlo lo quita. Los bloques de guion se editan con el constructor de condiciones o de efectos.

- **Archivos:** `common/cb_types.txt`
- **Disposición:** un archivo con un bloque por registro
- **Identificador:** la clave del bloque
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `war:cb`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `sprite_index` | fotograma de GFX_diplo_wargoal_icons | — | sí | Icono. Fotograma de GFX_diplo_wargoal_icons. |
| `is_triggered_only` | sí o no | — | no | Solo por evento o decisión. Si solo se obtiene por un efecto, no fabricándolo. |
| `months` | entero (meses) | — | no | Meses de validez. Cuánto dura el CB una vez obtenido. |
| `truce_months` | entero (meses) | — | no | Meses de tregua |
| `war_name` | clave de texto (localisation) | — | no | Nombre de la guerra. Base de las claves NORMAL_ y AGRESSION_, que comparten varios CB. |
| `constructing_cb` | sí o no | — | no | Se puede fabricar |
| `construction_speed` | número decimal | — | no | Velocidad de fabricación |
| `crisis` | sí o no | — | no | Vale en crisis |
| `mutual` | sí o no | — | no | Mutuo |
| `great_war_obligatory` | sí o no | — | no | Obligatorio en la Gran Guerra |
| `all_allowed_states` | sí o no | — | no | Todos los estados permitidos |
| `always` | sí o no | — | no | Siempre disponible |
| `is_civil_war` | sí o no | — | no | Guerra civil |
| `badboy_factor` | número decimal | — | no | Factor de infamia |
| `prestige_factor` | número decimal | — | no | Factor de prestigio |
| `peace_cost_factor` | número decimal | — | no | Factor de coste de la paz |
| `penalty_factor` | número decimal | — | no | Factor de penalización |
| `break_truce_prestige_factor` | número decimal | — | no | Romper tregua: prestigio |
| `break_truce_infamy_factor` | número decimal | — | no | Romper tregua: infamia |
| `break_truce_militancy_factor` | número decimal | — | no | Romper tregua: militancia |
| `good_relation_prestige_factor` | número decimal | — | no | Buenas relaciones: prestigio |
| `good_relation_infamy_factor` | número decimal | — | no | Buenas relaciones: infamia |
| `good_relation_militancy_factor` | número decimal | — | no | Buenas relaciones: militancia |
| `tws_battle_factor` | número decimal | — | no | Factor de batallas (puntuación de guerra) |
| `po_add_to_sphere` | sí o no | — | no | Añadir a la esfera |
| `po_annex` | sí o no | — | no | Anexionar |
| `po_clear_union_sphere` | sí o no | — | no | Vaciar la esfera de la unión |
| `po_colony` | sí o no | — | no | Colonia |
| `po_demand_state` | sí o no | — | no | Exigir un estado |
| `po_destroy_forts` | sí o no | — | no | Destruir fuertes |
| `po_destroy_naval_bases` | sí o no | — | no | Destruir bases navales |
| `po_disarmament` | sí o no | — | no | Desarme |
| `po_gunboat` | sí o no | — | no | Diplomacia de cañonero |
| `po_install_communist_gov_type` | sí o no | — | no | Instaurar gobierno comunista |
| `po_make_puppet` | sí o no | — | no | Convertir en títere |
| `po_release_puppet` | sí o no | — | no | Liberar un títere |
| `po_remove_cores` | sí o no | — | no | Quitar núcleos |
| `po_remove_prestige` | sí o no | — | no | Quitar prestigio |
| `po_reparations` | sí o no | — | no | Reparaciones |
| `po_status_quo` | sí o no | — | no | Statu quo |
| `po_transfer_provinces` | sí o no | — | no | Transferir provincias |
| `po_uninstall_communist_gov_type` | sí o no | — | no | Derrocar gobierno comunista |
| `can_use` | bloque de guion (constructor de condiciones o de efectos) | — | no | Puede usarse si |
| `is_valid` | bloque de guion (constructor de condiciones o de efectos) | — | no | Es válido si |
| `allowed_states` | bloque de guion (constructor de condiciones o de efectos) | — | no | Estados permitidos |
| `allowed_states_in_crisis` | bloque de guion (constructor de condiciones o de efectos) | — | no | Estados permitidos en crisis |
| `allowed_substate_regions` | bloque de guion (constructor de condiciones o de efectos) | — | no | Regiones de subestados permitidas |
| `allowed_countries` | bloque de guion (constructor de condiciones o de efectos) | — | no | Países permitidos |
| `on_add` | bloque de guion (constructor de condiciones o de efectos) | — | no | Al obtenerlo |
| `on_po_accepted` | bloque de guion (constructor de condiciones o de efectos) | — | no | Al aceptar la paz |

## Claves de texto

- `{id}` en localisation/00_<prefijo>_cb.csv
- `{id}_desc` en localisation/00_<prefijo>_cb.csv
- `{id}_setup` en localisation/00_<prefijo>_cb.csv
- `{id}_short` en localisation/00_<prefijo>_cb.csv

## Compañeros

- Se mantiene en la lista «peace_order» de common/cb_types.txt.

## Comprobaciones propias

- `cb_remove_cores_needs_transfer`: Por qué quitar núcleos no basta solo

## Ejemplo mínimo

```text
my_casus_belli = {
	sprite_index = 1
	is_triggered_only = yes
	months = 12
	truce_months = 0
	war_name = "WAR_NAME"
	badboy_factor = 1
	prestige_factor = 1
	peace_cost_factor = 1
	penalty_factor = 1
	break_truce_prestige_factor = 1
	break_truce_infamy_factor = 1
	break_truce_militancy_factor = 1
	good_relation_prestige_factor = 1
	good_relation_infamy_factor = 1
	good_relation_militancy_factor = 1
	po_demand_state = yes
}
```
