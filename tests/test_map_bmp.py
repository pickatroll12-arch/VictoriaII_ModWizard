"""Códec BMP propio (``core/map/bmp.py``, wizard D11 y H1): ida y vuelta exacta y los mismos píxeles que Pillow."""

import io
import pickle
import struct
import sys
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import vanilla_root  # noqa: E402

from vic2studio.core.map.bmp import (  # noqa: E402
    BMP_NOT_BMP,
    BMP_SHAPE,
    BMP_TRUNCATED,
    BMP_UNSUPPORTED,
    BmpError,
    new_bmp,
    read_bmp,
    read_bmp_header,
    write_bmp,
)

RNG = np.random.default_rng(1836)


def pillow_bmp(array: np.ndarray, palette: list[int] | None = None) -> bytes:
    image = Image.fromarray(array, "P" if array.ndim == 2 else "RGB")
    if palette is not None:
        image.putpalette(palette)
    buffer = io.BytesIO()
    image.save(buffer, "BMP")
    return buffer.getvalue()


def pillow_pixels(data: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(data))
    return np.asarray(image if image.mode == "P" else image.convert("RGB"))


def hand_bmp(rows_in_file: list[bytes], width: int, height: int, bits: int, *, palette: bytes = b"",
             used: int = 0, trailer: bytes = b"") -> bytes:
    """BMP escrito a mano: ``height`` negativo = filas de arriba abajo en el archivo."""
    image = b"".join(rows_in_file)
    offset = 14 + 40 + len(palette)
    return (struct.pack("<2sIHHI", b"BM", offset + len(image) + len(trailer), 0, 0, offset)
            + struct.pack("<IiiHHIIiiII", 40, width, height, 1, bits, 0, len(image), 2834, 2834, used, 0)
            + palette + image + trailer)


class RoundTripTests(unittest.TestCase):
    def test_24_bits_with_every_padding(self):
        for width in (1, 2, 3, 4, 5, 7):
            with self.subTest(ancho=width):
                array = RNG.integers(0, 256, (3, width, 3), dtype=np.uint8)
                data = pillow_bmp(array)
                image = read_bmp(data)
                self.assertEqual((image.width, image.height, image.bits), (width, 3, 24))
                np.testing.assert_array_equal(image.pixels, array)
                np.testing.assert_array_equal(image.pixels, pillow_pixels(data))
                self.assertEqual(write_bmp(image), data)

    def test_8_bits_with_palette(self):
        for width in (1, 2, 3, 5, 8):
            with self.subTest(ancho=width):
                array = RNG.integers(0, 16, (4, width), dtype=np.uint8)
                data = pillow_bmp(array, [v for i in range(16) for v in (i * 16, 255 - i * 16, i)])
                image = read_bmp(data)
                self.assertEqual(image.bits, 8)
                np.testing.assert_array_equal(image.pixels, array)
                np.testing.assert_array_equal(image.pixels, pillow_pixels(data))
                self.assertEqual(tuple(image.palette[3]), (3, 255 - 48, 48, 0))   # BGRA tal cual
                self.assertEqual(write_bmp(image), data)

    def test_top_down_rows(self):
        # 2x2, de arriba abajo en el archivo: rojo y verde arriba, azul y blanco abajo (relleno de 2 bytes).
        rows = [b"\x00\x00\xff" + b"\x00\xff\x00" + b"\x00\x00", b"\xff\x00\x00" + b"\xff\xff\xff" + b"\x00\x00"]
        data = hand_bmp(rows, 2, -2, 24)
        image = read_bmp(data)
        self.assertTrue(image.top_down)
        np.testing.assert_array_equal(image.pixels, [[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [255, 255, 255]]])
        np.testing.assert_array_equal(image.pixels, pillow_pixels(data))
        self.assertEqual(write_bmp(image), data)

    def test_nonzero_padding_and_trailing_bytes_are_kept(self):
        rows = [b"\x01\x02\x03\xab", b"\x04\x05\x06\xcd"]           # ancho 1: un byte de relleno por fila
        data = hand_bmp(rows, 1, 2, 24, trailer=b"\x00\x00")         # como los mapas de vanilla
        image = read_bmp(data)
        self.assertEqual(write_bmp(image), data)
        np.testing.assert_array_equal(image.pixels, [[[6, 5, 4]], [[3, 2, 1]]])

    def test_short_palette(self):
        palette = bytes(range(16 * 4))
        rows = [bytes([0, 1, 2, 0]), bytes([15, 14, 13, 0])]
        data = hand_bmp(rows, 3, 2, 8, palette=palette, used=16)
        image = read_bmp(data)
        self.assertEqual(image.palette.shape, (16, 4))
        np.testing.assert_array_equal(image.pixels, [[15, 14, 13], [0, 1, 2]])
        self.assertEqual(write_bmp(image), data)


class OrientationTests(unittest.TestCase):
    def test_asymmetric_pixel(self):
        """Fila 0 = la de arriba, como Pillow: en los mapas del juego, la y del motor (H1)."""
        array = np.zeros((3, 4, 3), np.uint8)
        array[0, 1] = (255, 0, 0)
        data = new_bmp(array)
        np.testing.assert_array_equal(pillow_pixels(data), array)
        image = read_bmp(data)
        self.assertEqual(tuple(image.pixels[0, 1]), (255, 0, 0))
        stride = 12
        last_row_in_file = data[54 + 2 * stride:54 + 3 * stride]
        self.assertEqual(last_row_in_file[3:6], b"\x00\x00\xff", "de abajo arriba: la fila 0 va al final")


class EditTests(unittest.TestCase):
    def test_editing_one_pixel_changes_only_its_bytes(self):
        for bits in (24, 8):
            with self.subTest(bits=bits):
                if bits == 24:
                    data = pillow_bmp(RNG.integers(0, 256, (5, 7, 3), dtype=np.uint8))
                else:
                    data = pillow_bmp(RNG.integers(0, 4, (5, 7), dtype=np.uint8), [0, 0, 0] * 4)
                image = read_bmp(data)
                image.pixels[2, 3] = (1, 2, 3) if bits == 24 else (image.pixels[2, 3] + 1) % 4
                out = write_bmp(image)
                diff = [i for i, (a, b) in enumerate(zip(data, out)) if a != b]
                self.assertEqual(len(out), len(data))
                self.assertLessEqual(len(diff), 3 if bits == 24 else 1)
                self.assertTrue(diff)
                np.testing.assert_array_equal(pillow_pixels(out), image.pixels)

    def test_palette_edit_is_written(self):
        data = pillow_bmp(np.zeros((2, 2), np.uint8), [0, 0, 0] * 256)
        image = read_bmp(data)
        image.palette[0] = (10, 20, 30, 0)
        self.assertEqual(Image.open(io.BytesIO(write_bmp(image))).getpalette()[:3], [30, 20, 10])

    def test_another_size_is_refused(self):
        image = read_bmp(new_bmp(np.zeros((2, 2, 3), np.uint8)))
        image.pixels = np.zeros((3, 2, 3), np.uint8)
        with self.assertRaises(BmpError) as caught:
            write_bmp(image)
        self.assertEqual(caught.exception.code, BMP_SHAPE)


class NewBmpTests(unittest.TestCase):
    def test_pillow_reads_new_files(self):
        for width in (1, 3, 6):
            rgb = RNG.integers(0, 256, (4, width, 3), dtype=np.uint8)
            data = new_bmp(rgb)
            np.testing.assert_array_equal(pillow_pixels(data), rgb)
            self.assertEqual(write_bmp(read_bmp(data)), data)
            indices = RNG.integers(0, 3, (4, width), dtype=np.uint8)
            data = new_bmp(indices, np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], np.uint8))
            self.assertEqual(struct.unpack_from("<I", data, 10)[0], 1078, "cabecera de 1 078 B como la del juego")
            np.testing.assert_array_equal(pillow_pixels(data), indices)
            self.assertEqual(Image.open(io.BytesIO(data)).getpalette()[:9], [255, 0, 0, 0, 255, 0, 0, 0, 255])

    def test_bad_input(self):
        for pixels, palette in ((np.zeros((2, 2, 4), np.uint8), None), (np.zeros((2, 2), np.uint8), None),
                                (np.zeros((2, 2), np.uint16), None), (np.zeros((0, 2, 3), np.uint8), None),
                                (np.zeros((2, 2), np.uint8), np.zeros((300, 3), np.uint8))):
            with self.subTest(forma=pixels.shape, paleta=None if palette is None else palette.shape):
                with self.assertRaises(BmpError):
                    new_bmp(pixels, palette)


class ErrorTests(unittest.TestCase):
    def test_unsupported_and_broken(self):
        good = new_bmp(np.zeros((2, 2, 3), np.uint8))
        compressed = good[:30] + struct.pack("<I", 1) + good[34:]
        bits32 = good[:28] + struct.pack("<H", 32) + good[30:]
        cases = {BMP_NOT_BMP: b"PK" + good[2:], BMP_UNSUPPORTED: compressed, BMP_TRUNCATED: good[:-3]}
        cases[BMP_UNSUPPORTED + " 32"] = bits32
        for name, data in cases.items():
            with self.subTest(caso=name):
                with self.assertRaises(BmpError) as caught:
                    read_bmp(data)
                self.assertEqual(caught.exception.code, name.split()[0])
        error = BmpError(BMP_TRUNCATED, "faltan 3 bytes")
        copy = pickle.loads(pickle.dumps(error))
        self.assertEqual((copy.code, copy.detail, str(copy)), (error.code, error.detail, str(error)))

    def test_header_without_decoding(self):
        data = new_bmp(np.zeros((3, 5, 3), np.uint8))
        self.assertEqual(read_bmp_header(data[:60]), (5, 3, 24))


class CorpusTests(unittest.TestCase):
    def test_vanilla_maps(self):
        game = vanilla_root()
        if game is None:
            self.skipTest("sin el juego base (VIC2_CORPUS)")
        for name, bits in (("provinces.bmp", 24), ("terrain.bmp", 8), ("rivers.bmp", 8)):
            with self.subTest(archivo=name):
                data = (game / "map" / name).read_bytes()
                self.assertEqual(read_bmp_header(data), (5616, 2160, bits))
                start = time.perf_counter()
                image = read_bmp(data)
                read = time.perf_counter() - start
                self.assertEqual(write_bmp(image), data)
                written = time.perf_counter() - start - read
                np.testing.assert_array_equal(image.pixels, pillow_pixels(data))
                print(f"\n[bmp] {name}: leer {read * 1000:.0f} ms, escribir {written * 1000:.0f} ms", end="")
                if bits == 24:
                    pixels = image.pixels.astype(np.uint32)
                    packed = (pixels[..., 0] << 16) | (pixels[..., 1] << 8) | pixels[..., 2]
                    self.assertEqual(len(np.unique(packed)), 3275)   # H4


if __name__ == "__main__":
    unittest.main()
