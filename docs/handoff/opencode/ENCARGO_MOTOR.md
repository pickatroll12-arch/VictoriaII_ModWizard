# Encargo: corte vertical del motor de esquemas (iteración 4)

Eres el **agente A** de la iteración 4, pero con un alcance más corto que el de `ENCARGO.md`:

- el **contrato completo** de `docs/diseno/wizard.md` §10;
- la **implementación necesaria para dos esquemas de punta a punta**, `government` (gobiernos) y `unit`
  (unidades terrestres y navales);
- sus pruebas.

No escribes interfaz. Si sale bien, Claude sigue desde tu rama con el resto de la iteración.

**Es también una evaluación.** Claude puntuará tu rama con comprobaciones que no se te dan. Se harán sobre la
**API pública fijada abajo**, con el corpus real (vanilla y una copia de un mod grande) y con casos difíciles.
Cómo se puntúa está al final. Lo que no está en esa API puedes diseñarlo como quieras, siguiendo §10.

Rama: `git checkout claude/keen-fermi-nw8itc && git pull && git checkout -b opencode/it4-motor`. Haz commit y
`git push -u origin opencode/it4-motor` al final de cada fase. No abras PR.

## Lee antes de escribir código

1. `AGENTS.md`, `docs/handoff/opencode/REGLAS.md` y `docs/handoff/opencode/PRUEBAS.md`, enteros.
2. De `docs/handoff/opencode/ENCARGO.md`, la tabla «Qué ya existe y debes usar»: vale igual aquí. No reimplementes
   nada de lo que nombra.
3. De `docs/diseno/wizard.md`:
   - **§3** (invariantes);
   - **§10 entera** (tu especificación);
   - **§19.3** (arnés);
   - **§22, iteración 4**;
   - los hechos H16 (gobiernos) y H18 (unidades) de §2;
   - §14.4 y §14.12 (unidades).
4. `ARCHITECTURE.md` §2.2–2.7.
5. Lee el código de verdad, no solo los nombres: `core/clausewitz/nodes.py` (la API de edición sin pérdidas),
   `core/project/workspace.py` (`transaction`, `open`, `create`, `touch`, `delete`) y `core/validate/fixes.py`
   hasta `_register_tag`.

## Tus archivos (y solo estos)

```
src/vic2studio/core/schema/{__init__,types,fields,entity,layouts,record,placement,companions,recipes,history,
                            validate,registry}.py
src/vic2studio/core/schemas/{__init__,government,unit}.py
src/vic2studio/core/schemas/texts/<área>.{es,en}.json
tests/schema_harness.py
tests/test_schema_*.py
docs/handoff/opencode/INFORME_MOTOR.md
```

Además, una clave por cada archivo de textos nuevo en `SMOKE_KEYS` de `src/vic2studio/app.py` (REGLAS.md §5). Nada
más. Si hace falta cambiar otro archivo, apúntalo en el informe como «Petición para Claude» y rodéalo.

`history.py` y `recipes.py` quedan solo como contrato: firmas de §10 que lanzan `NotImplementedError`. Ninguno de
tus dos esquemas los necesita.

## API pública fija (lo que se puntúa)

Importable desde `vic2studio.core.schema`, con estos nombres y estas firmas:

```python
from vic2studio.core.schema import (
    MISSING, EntitySchema, Entities, EntitySummary, Record, RecordRef, LocSpec,
    EntityInUseError, InvalidIdentError, registry,
)

registry.get(kind: str) -> EntitySchema          # "government" y "unit"; KeyError si no existe
registry.all_schemas() -> tuple[EntitySchema, ...]   # por descubrimiento (pkgutil), sin listas centrales

entities = Entities(ws, index, loc)              # Workspace, SymbolIndex, LocSync (los que ya existen)
entities.list(kind: str, *, view: str | None = None) -> list[EntitySummary]
entities.open(ref: RecordRef) -> Record
entities.create(kind: str, ident: str, values: dict | None = None, *,
                texts: Mapping[str, Mapping[str, str]] | None = None) -> RecordRef
entities.duplicate(ref: RecordRef, new_ident: str) -> RecordRef
entities.delete(ref: RecordRef, *, force: bool = False) -> None
entities.where_used(ref: RecordRef) -> list[SymbolRef]

@dataclass(frozen=True)
class RecordRef:   kind: str; ident: str; rel: VPath | None = None
@dataclass(frozen=True)
class EntitySummary:   ref: RecordRef; rel: VPath    # rel: archivo efectivo donde está

class Record:
    schema: EntitySchema; ref: RecordRef; handle: DocHandle; block: Block
    def get(self, key: str, default=MISSING) -> object
    def set(self, key: str, value: object) -> None           # None o MISSING quitan la entrada
    def dynamic(self, name: str) -> dict[str, object]
    def set_dynamic(self, name: str, key: str, value: object) -> None
    def unknown(self) -> list[Entry]
    def issues(self) -> list[Problem]                        # Problem de core/validate/model.py
    def loc_keys(self) -> list[tuple[LocSpec, str]]
```

Contrato de comportamiento:

- `set`, `set_dynamic` y cualquier otra mutación de un `Record` **exigen una transacción abierta** por quien
  llama (`with ws.transaction(...)`), igual que `ws.touch`. En cambio, `create`, `duplicate` y `delete` **abren la
  suya**: una sola transacción con el archivo, los compañeros y las claves de localización. Un `ws.undo()` lo
  deshace todo.
- `create` y `duplicate` con un id inválido o que ya existe lanzan `InvalidIdentError` (con `.code`) y **no cambian
  nada**: ni documentos, ni deshacer, ni archivos.
- `delete` de algo con usos en el índice (`index.refs_to`), sin `force`, lanza `EntityInUseError` (con `.uses`, la
  lista de `SymbolRef`) y no cambia nada.
- `list` refleja la **vista efectiva** (I7): lo creado y no guardado sale; lo borrado y no guardado, no.
- Leer (`list`, `open`, `get`, `issues`, `dynamic`, `loc_keys`, `where_used`) **nunca** deja un documento sucio ni
  escribe nada (I4).
- `unit` tiene dos vistas, `land` y `naval` (§10.3, `View`), sobre **un solo esquema**.

## Qué tiene que hacer cada esquema

- **`government`** (`common/governments.txt`, `SingleFile`):
  - las ideologías como `DynamicKeys` con `only_true` (§10.10: el ejemplo completo está ahí);
  - `election`, `duration`, `appoint_ruling_party` y `flagType`;
  - las claves de localización `{id}` y `{id}_ruler`;
  - los validadores `government_without_ideology` y `government_election_without_duration`.

  El compañero `MappingTable` de `rebel_types.txt` es **extra** (ver «Puntos extra»).
- **`unit`** (`units/*.txt`, `OnePerFile`, un bloque `<id> = { … }` por archivo):
  - los campos comunes y, con `Variant` sobre `type`, los propios de `land` y de `naval`;
  - las listas de bienes (`build_cost`, `supply_cost`) como `DynamicKeys` sobre bienes;
  - las claves `{id}` y `{id}_short`;
  - lo nuevo va a `units/<id>.txt` en el mod.

  Mira los 21 archivos de vanilla en el corpus y la copia del mod grande. El esquema tiene que describirlos sin
  `unknown_field` ni `bad_type`. **Gana el corpus**: si §2 o §14 dicen otra cosa, anota la desviación.

**Códigos de problema.** Algunos ya existen en la validación actual (`core/validate`) con sus textos
(`issue.*`, `explain.title.*`, `explain.outcome.*`). Antes de crear una clave de texto, búscala:
`core/texts.load_texts` falla si una clave se repite entre archivos. Los códigos nuevos llevan los tres textos en
ES y EN (REGLAS.md §4).

## Criterios que tus pruebas deben demostrar

| # | Criterio |
|---|---|
| 1 | **Corpus.** Los 8 gobiernos y las 21 unidades de vanilla (11 terrestres y 10 navales por vista) sin `unknown_field` ni `bad_type`. Abrir cada registro, leer cada campo y guardar no escribe nada. |
| 2 | **Corpus y minijuego.** Poner `attack` de `infantry` a otro valor cambia una sola línea de `units/infantry.txt` y conserva CRLF y comentarios. |
| 3 | `duplicate(infantry, "my_unit")` crea `units/my_unit.txt` en el mod y las claves `my_unit` y `my_unit_short`, en una transacción. Un `undo` lo quita todo. |
| 4 | `create("government", "junta", ...)` copia `governments.txt` al mod con `junta` al final y crea `junta` y `junta_ruler`. Con `election = yes` sin `duration` da `government_election_without_duration`. |
| 5 | `delete(infantry)` se bloquea con sus usos (la tecnología que hace `activate_unit = infantry`). Borrar `my_unit`, que no se usa, funciona en una transacción. |
| 6 | Una clave desconocida y un comentario dentro del bloque sobreviven a `set` de otro campo. `maximum_speed = 4.00` puesto a 5 queda `5.00` (§10.1, `Float`). |

Las pruebas de corpus llevan `@unittest.skipUnless(vanilla_root(), "sin corpus")` y trabajan sobre copias
(`tests/_corpus.py`).

## Fases

Al final de cada fase: sus pruebas en verde, la batería completa en verde (`PRUEBAS.md` §1), una entrada en el
informe, commit y push.

- **Fase 0. Orientación.** Rama, batería de partida, lectura. Apunta en el informe el entorno y la línea base.
- **Fase 1. Contrato.** Todas las dataclasses y `Protocol` de §10.1–10.8, con firmas tipadas y docstrings en
  español; lo no implementado lanza `NotImplementedError`. `registry` ya funcional. `tests/test_schema_contract.py`:
  - el ejemplo de §10.10 se construye;
  - `core/schema` no importa Qt;
  - dos esquemas con el mismo `kind` fallan.
- **Fase 2. Motor.**
  - Los tipos que usen tus dos esquemas, con lectura y escritura sin pérdidas.
  - Campos, `Section`, `DynamicKeys`, `Variant` y `View`.
  - `SingleFile` y `OnePerFile`.
  - `Record` y `Entities` según el contrato de arriba.
  - Colocación de lo nuevo (§10.7).
  - `validate.py` con `@validator` e `issue`.
- **Fase 3. Esquemas y criterios.**
  - `government.py` y `unit.py` con sus textos.
  - `tests/schema_harness.py` con `SchemaContract` (§19.3), y un `tests/test_schema_<kind>.py` de 3 líneas por
    esquema.
  - `tests/test_schema_criteria.py` con los 6 criterios.
- **Fase 4. Cierre.**
  - Batería con 3.12 y 3.10.
  - Al menos 10 mutantes a mano, uno por pieza (`PRUEBAS.md` §6).
  - `INFORME_MOTOR.md` completo: lo hecho, lo que no, desviaciones de §10, decisiones de diseño con su porqué,
    peticiones y dudas.

## Puntos extra (solo con todo lo anterior en verde)

- `MappingTable` sobre las 14 tablas de `rebel_types.txt`: crear `junta` la añade a todas, en la misma transacción.
- `duplicate` de un gobierno y borrado de un gobierno con usos.

## Cuándo parar

- La batería falla en la fase 0: para y avisa.
- Más de 3 intentos con la misma prueba: apúntalo y sigue.
- §10 contradice al código o al corpus: gana el corpus, apunta la desviación y sigue.
- Nunca:
  - saltes, borres o marques como `skip` una prueba existente;
  - toques archivos fuera de la lista;
  - escribas archivos desde `src/`;
  - importes Qt en `core/`;
  - subas datos de Paradox. **Fallar en esto deja la nota a cero.**

## Cómo se puntúa (100 puntos)

| Parte | Puntos | Qué mira Claude |
|---|---|---|
| Comprobaciones ocultas | 40 | Unas 20 pruebas propias sobre la API pública, con el corpus y con casos difíciles (sin pérdidas, I4, I5, I7, errores sin efectos, vistas…) |
| Tus criterios | 15 | Los 6 criterios, en verde en el entorno de referencia, y la batería completa |
| Diseño | 15 | Fidelidad a §10, decisiones razonadas y una API que el agente de interfaz pueda usar sin leerte el código |
| Invariantes y arquitectura | 10 | Escritura, capas, hilos, textos, nada fuera de la lista |
| Calidad de las pruebas | 10 | Qué parte de los mutantes de Claude detectan tus pruebas |
| Honestidad del informe | 10 | Que lo que dice el informe sea verdad |
| Extra | +10 | `MappingTable` y gobiernos completos |
