"""Fuzzing ligero y determinista: el parser nunca falla y ``to_source`` es exacto."""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import CLAUSEWITZ_SUFFIXES, corpus_files  # noqa: E402
from vic2studio.core.clausewitz import (  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
