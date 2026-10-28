# Informe del agente A: iteración 4, núcleo

> Plantilla. Rellénala al acabar cada fase (no al final de todo): si el usuario corta, Claude debe poder seguir
> desde aquí. Sin adornos: lo que está, lo que no y por qué. Claude lo revisará contra el código.

## Entorno

- Sistema:
- Python (3.12 y 3.10) y PySide6:
- Corpus: sí / no (rutas de `VIC2_CORPUS`, sin datos personales)
- Batería de partida (fase 0): `Ran N tests … OK (skipped=N)`

## Fases

| Fase | Estado | Commit | Gasto acumulado (si lo sabes) |
|---|---|---|---|
| 0 Orientación | | | |
| 1 Contrato | | | |
| 2 Motor | | | |
| 3 Esquemas y criterios | | | |
| 4 docgen | | | |
| 5 Entrega | | | |

## Qué está hecho

Por archivo de `core/schema/` y `core/schemas/`: qué hace y qué queda en `NotImplementedError` (y por qué).

## Criterios de la iteración 4 (parte de núcleo)

| Criterio | Estado (cumple / no / parcial / sin corpus) | Prueba que lo demuestra | Notas |
|---|---|---|---|
| 1 Conformidad vanilla, abrir y guardar no escribe | | | |
| 2 `attack` de infantry: una línea | | | |
| 3 `my_cb`: `peace_order`, 4 claves, borrado bloqueado, un Ctrl+Z | | | |
| 4 `junta`: 14 tablas, 2 claves, aviso sin `duration` | | | |
| 5 Terrestres y navales: un esquema, dos vistas | | | |
| 6 `event_modifier`: prueba de 3 líneas, nada en `ui/` | | | |
| 7 docgen ES/EN sin claves sin traducir | | | |

## Pruebas

- Batería final con 3.12: `Ran N tests … OK (skipped=N)`
- Batería final con 3.10:
- Con corpus (si lo hay):
- Pruebas nuevas: número y archivos.

## Mutantes

| Archivo | Cambio | Prueba que lo mató (o prueba añadida) |
|---|---|---|
| | | |

## Desviaciones de wizard §10

Cada sitio donde el código no hace lo que dice §10, con el porqué (el corpus, una API existente, un hueco del
diseño).

## API para el agente B (interfaz)

Lo que la interfaz necesita saber y no es obvio leyendo `core/schema/__init__.py`: cómo se obtiene un
`Entities`, qué lanza cada operación, cómo se leen los `View`, `Section` y `visible_if`, cómo pedir los textos de
un campo.

## Peticiones para Claude

Cambios que harían falta en archivos que no son tuyos (archivo, cambio, porqué).

## Dudas abiertas

Decisiones que tomaste por la opción conservadora y que alguien debería confirmar.
