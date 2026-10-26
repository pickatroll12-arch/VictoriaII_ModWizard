"""Fuzzing ligero y determinista: el parser nunca falla, ``to_source`` es exacto y las ediciones se releen igual."""

import random
import sys
import time
import unittest
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import CLAUSEWITZ_SUFFIXES, corpus_files  # noqa: E402
from vic2studio.core.clausewitz import (  # noqa: E402
    Block,
    ClausewitzDate,
    EditError,
    Scalar,
    Severity,
    format_canonical,
    from_json,
    parse,
    simplify,
    to_json,
    to_source,
    walk,
)
from vic2studio.core.encoding import decode_bytes  # noqa: E402

PIECES = [
    "{", "}", "=", "==", "<", ">", "<=", ">=", "!=", "!", '"', '"cadena"', '"multi\nlínea"', "#c", "#", "\n",
    "\r\n", "\r", " ", "\t", "a", "b", "1861.1.1", "-0.5", "yes", "no", "Málaga", "\x00", "﻿", "x#y", "a=b",
    "{}", "}}", "{{", "= =", "\x7f", "''", "{ a } = b", "a = = b",
]
FALLBACK_SAMPLES = [
    "political_decisions = {\n\tunite = {\n\t\tpotential = { tag = GEL }\n\t\tallow = { war = no }\n\t}\n}\n",
    "owner = MEX\r\ncontroller = MEX\r\n1861.1.1 = {\r\n\towner = USA # cambio\r\n}\r\n",
    'leader = {\n\tname = "Nicholas Geffrard"\n\tdate = 1855.1.1\n\tprestige = 0.1\n}\n',
]


class FuzzTests(unittest.TestCase):
    def check(self, text, label):
        result = parse(text)
        self.assertEqual(to_source(result.document), text, label)
        exported = to_json(result.document)
        self.assertEqual(to_json(parse(format_canonical(from_json(exported))).document), exported, label)
        # El resto de la API tampoco debe fallar sobre árboles con errores.
        to_json(result.document, include_comments=True)
        format_canonical(result.document, comments=True)
        simplify(result.document)
        for _ in walk(result.document):
            pass
        for diagnostic in result.diagnostics:
            diagnostic.message("es")
            diagnostic.message("en")

    def test_random_token_sequences(self):
        rng = random.Random(20240601)
        for _ in range(3000):
            text = "".join(rng.choice(PIECES) for _ in range(rng.randint(0, 60)))
            self.check(text, repr(text))

    def test_random_bytes(self):
        rng = random.Random(1861)
        for _ in range(1500):
            raw = bytes(rng.randrange(256) for _ in range(rng.randint(0, 200)))
            self.check(decode_bytes(raw).text, repr(raw))

    def test_mutated_corpus_files(self):
        rng = random.Random(1836)
        files = corpus_files(CLAUSEWITZ_SUFFIXES)
        sources = [p.read_bytes() for p in rng.sample(files, min(250, len(files)))] if files else []
        sources += [s.encode("cp1252") for s in FALLBACK_SAMPLES]
        insertions = [b"{", b"}", b'"', b"= =", b"#", b"!", b"{ a } = b", b"\r", b"\x00"]
        for data in sources:
            for _ in range(4):
                mutated = bytearray(data)
                for _ in range(rng.randint(1, 8)):
                    if not mutated:
                        break
                    pos = rng.randrange(len(mutated))
                    roll = rng.random()
                    if roll < 0.4:
                        mutated[pos] = rng.choice(b'{}="#!<>\n\r \t\x00a1')
                    elif roll < 0.7:
                        del mutated[pos:pos + rng.randint(1, 20)]
                    else:
                        mutated[pos:pos] = rng.choice(insertions)
                self.check(decode_bytes(bytes(mutated)).text, f"mutación de {len(data)} bytes")

    def test_token_level_mutations(self):
        rng = random.Random(1914)
        base = FALLBACK_SAMPLES[0].replace("{", " { ").replace("}", " } ").split()
        for _ in range(500):
            tokens = list(base)
            for _ in range(rng.randint(1, 5)):
                pos = rng.randrange(len(tokens))
                roll = rng.random()
                if roll < 0.33:
                    del tokens[pos]
                elif roll < 0.66:
                    tokens.insert(pos, rng.choice(["{", "}", "=", '"', "!", "x"]))
                else:
                    other = rng.randrange(len(tokens))
                    tokens[pos], tokens[other] = tokens[other], tokens[pos]
            text = rng.choice([" ", "\n", "\t", ""]).join(tokens)
            self.check(text, text)

    def test_extreme_nesting(self):
        deep = "{" * 100000 + "a = b" + "}" * 50000 + '"abierta'
        result = parse(deep)
        self.assertEqual(to_source(result.document), deep)
        self.assertEqual(sum(1 for d in result.errors if d.code == "unclosed_block"), 50000)
        medium = "x = {" * 3000 + "a = b" + "}" * 1500
        result = parse(medium)
        self.assertEqual(to_source(result.document), medium)
        canonical = format_canonical(from_json(to_json(result.document)))
        self.assertEqual(format_canonical(parse(canonical).document), canonical)
        self.assertEqual(sum(1 for _ in walk(result.document)), 3001)


EDIT_VALUES = [
    1, -2, 0.5, 1e-7, True, False, "GEL", "con espacios", "", "ñandú", ClausewitzDate(1861, 4, 12), [1, 2, 3], [],
    {}, {"a": 1, "b": [4, 5]}, {"n": {"d": {"x": "y"}}}, Scalar("q", quoted=True), ["x y", "z"], list(range(40)),
    np.float64(3092.0), np.int64(5), Block.from_pairs([("tag", "GEL"), ("tag", "MAJ"), ("literacy", ">", 0.5)]),
]


def edit_value(rng):
    """Valor aleatorio de ``EDIT_VALUES``; los bloques, copiados (cada bloque está en un solo sitio)."""
    value = rng.choice(EDIT_VALUES)
    return value.clone() if isinstance(value, Block) else value


EDIT_KEYS = ["new_key", "1861.1.1", "add_core", "two words", 1234, ClausewitzDate(1900, 1, 1), "OR"]
EDIT_OPS = ["=", "<", ">", ">=", "<=", "!=", "=="]
EDIT_COMMENTS = ["# nuevo", "otro comentario", ["# a", "# b"], [], "# x\n# y"]
# Texto descartado (errores) tras muchas líneas de comentario o de blancos: antes, backtracking exponencial (P1).
SLOW_BEFORE = [
    "1861.1.1 = {\r\n        owner = SOM\r\n" + "".join(f"        # add_core = X{i}\r\n" for i in range(300))
    + "        controller =\r\n}\r\n",
    "political_decisions = {\r\n\tx = 1\r\n}\r\n" + "".join(f"\t# antigua_{i} = {{ desactivada }}\r\n" for i in range(300))
    + "}\r\n",
    "a = { b = 1" + " " * 3000 + "} c = 2 }\n",
]


class EditFuzzTests(unittest.TestCase):
    """Ediciones aleatorias deterministas sobre archivos reales (y mutados, con errores).

    El texto editado se relee con el mismo árbol y sin diagnósticos nuevos (si el original
    no tenía errores) y deshacer las ediciones en orden inverso devuelve el texto exacto.
    """

    def blocks(self, doc):
        return [doc] + [entry.value for _, entry in walk(doc) if isinstance(entry.value, Block)]

    def edit(self, rng, doc, undo):
        """Aplica una edición aleatoria y añade a ``undo`` su inversa exacta (None si no la tiene)."""
        blocks = self.blocks(doc)
        block = rng.choice(blocks)
        entries = block.entries
        entry = rng.choice(entries) if entries else None
        roll = rng.random()
        if entry is None or roll < 0.2:
            new = block.insert(rng.randint(0, len(entries)), rng.choice(EDIT_KEYS), edit_value(rng),
                               rng.choice(EDIT_OPS))
            undo.append(lambda: block.remove_entry(new))
        elif roll < 0.35:
            old = entry.value
            entry.value = edit_value(rng)
            undo.append(lambda: setattr(entry, "value", old))
        elif roll < 0.5:
            index = block.remove_entry(entry)
            undo.append(lambda: block.insert_entry(index, entry))
        elif roll < 0.65:
            index = entries.index(entry)
            target = rng.choice(blocks)
            try:
                block.move(entry, rng.randint(0, len(target.entries) - (target is block)), to=target)
            except EditError as error:  # el destino está dentro de la entrada
                self.assertEqual(error.code, "cycle")
                return
            undo.append(lambda: target.move(entry, index, to=block))
        elif roll < 0.75:
            order = entries[:]
            rng.shuffle(entries)
            undo.append(lambda: entries.__setitem__(slice(None), order))
        elif roll < 0.82 and entry.key is not None:
            key, op = entry.key, entry.op
            entry.key = rng.choice(["renamed", "two words", 77])
            entry.op = rng.choice(EDIT_OPS)
            undo.append(lambda: (setattr(entry, "key", key), setattr(entry, "op", op)))
        elif roll < 0.88:
            copy = rng.choice([e for _, e in walk(doc)]).clone(comments=rng.random() < 0.5)
            block.insert_entry(rng.randint(0, len(entries)), copy)
            undo.append(lambda: block.remove_entry(copy))
        else:
            # Sin inversa exacta: comentarios y llaves que faltaban.
            choice = rng.random()
            if choice < 0.4:
                entry.comments = rng.choice(EDIT_COMMENTS)
            elif choice < 0.6:
                entry.line_comment = rng.choice([None, "# fin de línea", "nota"])
            elif choice < 0.8:
                block.trailing_comments = rng.choice(EDIT_COMMENTS)
            else:
                for unclosed in doc.unclosed_blocks():
                    unclosed.close()
            undo.append(None)

    def check(self, rng, text, label, edits):
        started = time.perf_counter()
        result = parse(text)
        doc = result.document
        before = Counter(d.code for d in result.diagnostics if d.severity is not Severity.INFO)
        undo = []
        for _ in range(edits):
            self.edit(rng, doc, undo)
        new = to_source(doc)
        reparsed = parse(new)
        format_canonical(doc, comments=True)
        to_json(doc, include_comments=True)
        if result.ok:
            self.assertEqual(to_json(reparsed.document), to_json(doc), label)
            after = Counter(d.code for d in reparsed.diagnostics if d.severity is not Severity.INFO)
            self.assertEqual([code for code in after if after[code] > before[code]], [], label)
        if None not in undo:
            for step in reversed(undo):
                step()
            self.assertEqual(to_source(doc), text, label)
        self.assertLess(time.perf_counter() - started, 5, label)
        return len(undo)

    def test_random_edits_on_real_and_broken_files(self):
        rng = random.Random(2024)
        files = [p for p in corpus_files(CLAUSEWITZ_SUFFIXES) if p.stat().st_size <= 256_000]
        sources = [(str(p), decode_bytes(p.read_bytes()).text) for p in rng.sample(files, min(300, len(files)))]
        sources += [(f"muestra {i}", text) for i, text in enumerate(FALLBACK_SAMPLES + SLOW_BEFORE)]
        broken = []
        for label, text in sources[:80]:
            data = bytearray(text.encode("utf-8"))
            for _ in range(rng.randint(1, 4)):
                pos = rng.randrange(len(data) + 1)
                data[pos:pos] = rng.choice([b"{", b"}", b"=", b"= =", b"#", b"!", b'"'])
            broken.append((f"{label} (mutado)", data.decode("utf-8", errors="replace")))
        edits = sum(self.check(rng, text, label, rng.randint(1, 10)) for label, text in sources + broken)
        self.assertGreater(edits, 500 if len(sources) > 100 else 50)


if __name__ == "__main__":
    unittest.main()
