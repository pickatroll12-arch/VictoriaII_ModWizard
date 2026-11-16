# Handoff para OpenCode: guía para el usuario

Esta carpeta prepara sesiones de **OpenCode** para avanzar el proyecto con agentes externos. Claude Code revisa
cada rama antes de fusionarla: comprobaciones ocultas, el corpus real y mutantes.

| Archivo | Para quién | Qué es |
|---|---|---|
| `README.md` (este) | Tú | Cómo preparar el equipo, arrancar OpenCode, elegir modelo y esfuerzo, vigilar el gasto y entregar |
| **`ENCARGO_IT4.md`** | El agente | **El encargo actual: terminar la iteración 4** (resto del núcleo, interfaz, integración, revisión y cierre) |
| `REGLAS.md` | El agente | Las reglas del proyecto que no se ven leyendo un archivo |
| `PRUEBAS.md` | Los dos | Cómo pasar las pruebas, con y sin corpus, y las combinaciones de versiones |
| `INFORME_MOTOR.md`, `INFORME_EDITOR.md` | El agente | Informes de los encargos ya hechos (motor de esquemas y editor de texto): decisiones y límites |
| `ENCARGO_MOTOR.md`, `ENCARGO.md` | — | Encargos anteriores, hechos o sustituidos (no se ejecutan) |

`AGENTS.md`, en la raíz del repositorio, es lo que OpenCode lee solo al empezar: apunta a `ENCARGO_IT4.md`.

## 1. Preparar el equipo (una vez)

Necesitas Git, [uv](https://docs.astral.sh/uv/) (instala Python y entornos sin tocar el del sistema) y OpenCode.

**Linux:**

```bash
git clone https://github.com/pickatroll12-arch/VictoriaII_ModWizard.git   # o git pull si ya lo tienes
cd VictoriaII_ModWizard
git checkout main && git pull           # si aún no fusionaste el PR #12: git checkout claude/keen-fermi-nw8itc
git checkout -b opencode/it4-claude
uv python install 3.12 3.10
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt
uv venv -p 3.10 .venv310 && uv pip install -p .venv310 -r requirements.txt
# Qt sin pantalla y las fuentes de las pruebas de disposición (Debian/Ubuntu):
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 fonts-dejavu
```

**Windows (PowerShell):** las mismas órdenes, con `uv venv -p 3.12 .venv; uv pip install -p .venv -r
requirements.txt` (y lo mismo para `.venv310`).

No uses Python 3.14 para las pruebas. Las carpetas `.venv*` no se suben: añádelas a `.git/info/exclude` si
`git status` las enseña.

**Comprueba que todo funciona** antes de gastar un céntimo de API (unos 7 minutos):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests
```

Debe acabar en `OK (skipped=54)`. Si fallan pruebas de disposición («… recortado»), son las fuentes: instala
`fonts-dejavu` (`PRUEBAS.md` §5). Cualquier otro fallo es del entorno: arréglalo antes.

## 2. El corpus (recomendado)

Los criterios 1 y 7 y la revisión adversarial se comprueban contra vanilla real y una copia del mod grande. El
corpus no está en el repositorio: usa tu propia copia local. **Descomprímelo fuera del repositorio**:

```bash
mkdir -p ~/vic2corpus && cd ~/vic2corpus
# Descomprime cada zip como dice CONTINUAR_EN_CLAUDE_CODE.md §4: quedan vanilla/, «Plantilla Mod»/ y ShagoMod/
```

Apunta siempre a **copias** (`PRUEBAS.md` §4). Las pruebas nunca abren el mod real, pero con copias no hay riesgo.

## 3. OpenCode, modelo y esfuerzo

1. Conecta tu clave de Anthropic en OpenCode (`opencode auth login`, proveedor Anthropic).
2. **Pon un tope de gasto** en la consola de Anthropic: **$150** para esta tanda. Si corta a mitad, no se pierde
   nada, porque cada fase termina en un commit.
3. **Modelo: Claude Opus 5.5** (`anthropic/claude-opus-5-5`), el mismo toda la sesión. Cambiar de modelo a mitad
   rompe la caché de prompts y encarece todo lo que viene después.
4. **Esfuerzo:** Opus 5.5 tiene `low`, `medium`, `high`, `xhigh` y `max`, y **por defecto usa `medium`**, así que
   ponlo a mano.

   | Fases | Esfuerzo | Por qué |
   |---|---|---|
   | 0 (orientación) | `medium` | Leer y pasar pruebas: no necesita pensar mucho |
   | 1, 3, 4, 5 (núcleo, formularios, editor, integración) | **`high`** | Programación larga con criterio: el punto dulce entre calidad y gasto |
   | 2 (contrato de la interfaz) y 6 (revisión adversarial) | **`xhigh`** | Decisiones de diseño que condicionan todo y la búsqueda de fallos propios: aquí rinde pensar más |
   | — | nunca `max` | Cuesta mucho más y no compensa en este tipo de trabajo |

   Si tu OpenCode no deja cambiar el esfuerzo a mitad de sesión, usa **`high` para todo**. Si no deja elegirlo,
   comprueba que no se queda en el `medium` por defecto.
5. Abre OpenCode **en la raíz del repositorio**, en una sesión nueva, y escribe:

   > Lee AGENTS.md y docs/handoff/opencode/ENCARGO_IT4.md y empieza por la fase 0. Respóndeme en español.

6. **En los primeros 10 minutos, mira el coste por paso.** Debe ser de céntimos. Si cada paso cuesta dólares, la
   caché de prompts no funciona: para y revisa la configuración.

## 4. Presupuesto (estimación, no medida)

| Fase | Qué | Aprox. |
|---|---|---|
| 0 | Orientación | ~$3 |
| 1 | Resto del núcleo: 5 esquemas, compañeros, docgen | ~$20 |
| 2 | Contrato de la interfaz | ~$8 |
| 3 | Formularios y selectores | ~$30 |
| 4 | Editor de entidades y las 6 secciones | ~$30 |
| 5 | Integración y prueba de punta a punta | ~$15 |
| 6 | Revisión adversarial, capturas y cierre | ~$15 |
| | **Total** | **~$120** (rango probable $90–150) |

Si se acerca a **$150**, el encargo le dice que pare, haga commit y cierre con una fase 6 mínima. Lo que falte lo
termina Claude Code.

## 5. Mientras trabaja

- Cada fase termina en un **commit** y un **push** a `opencode/it4-claude`. Puedes cortar entre fases.
- Si te pregunta algo de diseño, contesta si lo tienes claro. Si no, dile que lo anote en `INFORME_IT4.md` como
  duda abierta y siga con la opción más conservadora.
- **Apunta el gasto y el tiempo de cada fase.** Sirven para comparar con las rondas de DeepSeek.

## 6. Al terminar

1. Comprueba que hizo push de `opencode/it4-claude` y que `docs/handoff/opencode/INFORME_IT4.md` está relleno.
2. **No abras PR todavía.**
3. En Claude Code:

   > Revisa la rama opencode/it4-claude (encargo ENCARGO_IT4.md) como las anteriores: comprobaciones ocultas
   > selladas, corpus, mutantes y puntuación.
