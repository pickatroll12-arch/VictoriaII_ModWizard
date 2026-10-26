# Avisos de terceros

Victoria II Mod Studio no contiene datos de Paradox Interactive: lee los archivos del juego de la instalación del usuario en tiempo de ejecución.

## Azgaar's Fantasy Map Generator

- **Proyecto:** https://github.com/Azgaar/Fantasy-Map-Generator
- **Qué se usa:** algoritmos portados a Python y numpy (rejilla, plantillas de relieve, clima, hidrología, biomas, partición y nombres con cadenas de Markov). Hoy solo aparecen en los prototipos de diseño de `docs/diseno/prototipos/mapforge/`. En la iteración 9 pasarán a `src/vic2studio/core/mapforge/`; cada módulo portado llevará la cabecera `# Port of Azgaar's Fantasy Map Generator <ruta>.ts (MIT, © Max Haniyeu)`. Las plantillas de relieve y las bases de nombres de FMG que se incluyan también están cubiertas por esta licencia.
- **Licencia:** MIT, con la cláusula de obras derivadas del autor. Texto íntegro:

```text
MIT License

Copyright 2017-2024 Max Haniyeu (Azgaar), azgaar.fmg@yandex.com

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

You can produce, without restrictions, any derivative works from the original
software and even reap commercial benefits from the sale of the secondary product.
The derivates include created maps, map images, screenshots, videos, and other materials.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
