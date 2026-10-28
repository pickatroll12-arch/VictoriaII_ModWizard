# Iteración 4 con OpenCode: guía para el usuario

Esta carpeta prepara una sesión de **OpenCode** con la API de Anthropic para hacer **la mitad de núcleo de la
iteración 4**: el motor de esquemas y los esquemas de 6 entidades, con sus pruebas. Es el trabajo del «agente A»
de `docs/diseno/wizard.md` §22. La otra mitad (formularios, editor de entidades, selectores y salas, la integración,
la revisión adversarial y el cierre) la hace Claude Code después, con el límite semanal renovado.

| Archivo | Para quién | Qué dice |
|---|---|---|
| `README.md` (este) | Tú | Cómo preparar el equipo, arrancar OpenCode, vigilar el gasto y entregar |
| `ENCARGO.md` | El agente | Qué construir, en qué orden, con qué pruebas y cuándo parar |
| `REGLAS.md` | El agente | Las reglas del proyecto que no se ven leyendo un archivo |
| `PRUEBAS.md` | Los dos | Cómo pasar las pruebas, con y sin corpus, y las combinaciones de versiones |
| `INFORME.md` | El agente | La plantilla del informe final, que Claude revisará |

`AGENTS.md`, en la raíz del repositorio, es lo que OpenCode lee solo al empezar: apunta aquí.

## 1. Preparar el equipo (una vez)

Necesitas Git, [uv](https://docs.astral.sh/uv/) (instala Python y entornos sin tocar el del sistema) y OpenCode.

**Linux:**

```bash
git clone https://github.com/pickatroll12-arch/VictoriaII_ModWizard.git
cd VictoriaII_ModWizard
git checkout claude/keen-fermi-nw8itc          # o main, si ya fusionaste el PR #10
git checkout -b opencode/it4-nucleo
uv python install 3.12 3.10
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt
uv venv -p 3.10 .venv310 && uv pip install -p .venv310 -r requirements.txt
# Qt sin pantalla (Debian/Ubuntu):
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 fonts-dejavu
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/pickatroll12-arch/VictoriaII_ModWizard.git
cd VictoriaII_ModWizard
git checkout claude/keen-fermi-nw8itc
git checkout -b opencode/it4-nucleo
uv python install 3.12 3.10
uv venv -p 3.12 .venv; uv pip install -p .venv -r requirements.txt
uv venv -p 3.10 .venv310; uv pip install -p .venv310 -r requirements.txt
```

No uses Python 3.14 para las pruebas: nadie las ha pasado con él (CONTINUAR §4). Las carpetas `.venv*` no se
suben: añádelas a `.git/info/exclude` si `git status` las enseña.

**Comprueba que todo funciona** antes de gastar un céntimo de API (unos 7 minutos):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests
# Windows: $env:QT_QPA_PLATFORM="offscreen"; .venv\Scripts\python -m unittest discover -s tests
```

Debe acabar en `OK (skipped=40)`. Si falla aquí, el problema es del entorno, no del código: arréglalo antes.

## 2. El corpus (recomendado)

Los criterios 1, 2, 4 y 5 de la iteración 4 se comprueban contra vanilla real. El corpus está en la release
privada `recursos-v1` del repositorio. **Descomprímelo fuera del repositorio** (nunca dentro: no se puede subir
ningún dato de Paradox):

```bash
mkdir -p ~/vic2corpus && cd ~/vic2corpus
gh auth login                                   # una vez: el repositorio es privado
gh release download recursos-v1 -R pickatroll12-arch/VictoriaII_ModWizard
# Descomprime cada zip como dice CONTINUAR_EN_CLAUDE_CODE.md §4 («Corpus»):
# quedan vanilla/, «Plantilla Mod»/ y ShagoMod/
```

También puedes apuntar a tu instalación del juego y a tus mods, **pero siempre a copias**: las pruebas nunca abren
el VSM real como proyecto, pero un agente con prisa podría. Con copias no hay riesgo.

## 3. OpenCode y la API

1. Instala OpenCode (ver [opencode.ai](https://opencode.ai)) y conecta tu clave de Anthropic (`opencode auth
   login`, proveedor Anthropic).
2. **Pon un tope de gasto en la consola de Anthropic** antes de empezar (en los límites de gasto de tu
   organización; si no lo encuentras, carga solo los $100 de crédito). Si el tope corta a mitad, no se pierde
   nada: el encargo hace commit al final de cada fase.
3. Modelo: **Claude Opus 5.5** (`anthropic/claude-opus-5-5`) para todo. Si tu OpenCode deja elegir el esfuerzo,
   usa `high`; `xhigh` solo para la fase 1 (el contrato).
4. Abre OpenCode **en la raíz del repositorio**, en una sesión nueva, y escribe:

   > Lee AGENTS.md y docs/handoff/opencode/ENCARGO.md y empieza por la fase 0. Respóndeme en español.

5. **En los primeros 10 minutos, mira el coste por paso** (OpenCode lo enseña en la sesión). Debe ser de céntimos.
   Si cada paso cuesta dólares, la caché de prompts no está funcionando: para y revisa la configuración, o los $100
   se irán en una hora.

## 4. Presupuesto

El encargo está repartido para unos **$100 con Opus 5.5** (estimación; no medida):

| Fase | Qué | Coste aproximado |
|---|---|---|
| 0 | Orientación y comprobar el entorno | ~$5 |
| 1 | Contrato del motor (tipos y firmas) | ~$10 |
| 2 | El motor de esquemas | ~$35 |
| 3 | Los 7 esquemas y los criterios del núcleo | ~$25 |
| 4 | Documentación generada (docgen) | ~$10 |
| 5 | Baterías, informe y entrega | ~$10 |

Si al acabar la fase 3 llevas más de **$80**, dile que pare y haga solo la fase 5 (informe y entrega). La fase 4
la puede hacer Claude el domingo.

## 5. Mientras trabaja

- Cada fase termina en un **commit** y un **push** a `opencode/it4-nucleo`. Puedes cortar entre fases.
- Si te pregunta algo de diseño que no sabes contestar, dile que lo anote en `INFORME.md` como duda abierta y siga
  con la opción más conservadora: Claude lo revisa después.
- Si se atasca más de 3 intentos en la misma prueba, que lo anote y pase a lo siguiente.

## 6. Al terminar

1. Comprueba que hizo push de `opencode/it4-nucleo` y que `docs/handoff/opencode/INFORME.md` está relleno.
2. **No abras PR todavía** ni fusiones nada en `main`.
3. El domingo, en una sesión nueva de Claude Code:

   > Lee CONTINUAR_EN_CLAUDE_CODE.md y docs/handoff/opencode/INFORME.md. Revisa la rama opencode/it4-nucleo como
   > revisaste el trabajo de Gemini (mutantes, corpus y las cuatro combinaciones) y sigue con la iteración 4.
