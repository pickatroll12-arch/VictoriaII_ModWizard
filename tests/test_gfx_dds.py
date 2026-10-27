"""DDS sin comprimir (``core/gfx/dds.py``, wizard D11, H8 y H23): cabeceras de vanilla, mips y lectura."""

import io
import pickle
import struct
import sys
import unittest
from pathlib import Path

import numpy as np
import PIL
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import vanilla_root  # noqa: E402

from vic2studio.core.gfx.dds import (  # noqa: E402
    CAPS,
    CAPS_MIPS,
    DDS_NOT_DDS,
    DDS_SHAPE,
    DDS_TRUNCATED,
    DDS_UNSUPPORTED,
    FLAGS,
    FLAGS_MIPS,
    HEADER_SIZE,
    DdsError,
    dds_info,
    mip_levels,
    read_dds,
    write_dds,
)

RNG = np.random.default_rng(1871)
# Pillow 10.0 y 10.1 leen X8R8G8B8 como si fuera de 24 bits; desde 10.2 sirve de referencia también para ese.
PILLOW_READS_X8 = tuple(int(part) for part in PIL.__version__.split(".")[:2]) >= (10, 2)


def pillow_rgba(data: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))


def hand_dds(pixels: bytes, width: int, height: int, bits: int, masks, pf_flags: int, fourcc: bytes = bytes(4)):
    header = struct.pack("<4sIIIIIII44sII4sIIIIIIIIII", b"DDS ", 124, FLAGS, height, width,
                         width * height * bits // 8, 0, 0, bytes(44), 32, pf_flags, fourcc, bits, *masks,
                         CAPS, 0, 0, 0, 0)
    return header + pixels


class WriteTests(unittest.TestCase):
    def test_pillow_reads_what_we_write(self):
        for height, width in ((1, 1), (3, 5), (7, 2), (64, 93), (16, 16)):
            for mipmaps in (False, True):
                with self.subTest(tamaño=(width, height), mips=mipmaps):
                    rgba = RNG.integers(0, 256, (height, width, 4), dtype=np.uint8)
                    data = write_dds(rgba, mipmaps=mipmaps)
                    np.testing.assert_array_equal(pillow_rgba(data), rgba)
                    np.testing.assert_array_equal(read_dds(data).rgba, rgba)
                    levels = mip_levels(rgba) if mipmaps else [rgba]
                    self.assertEqual(len(data), HEADER_SIZE + sum(level.size for level in levels))

    def test_header_fields_like_vanilla(self):
        info = dds_info(write_dds(np.zeros((720, 1880, 4), np.uint8)))
        self.assertEqual((info.flags, info.pitch, info.mip_count, info.caps), (0x81007, 1880 * 720 * 4, 0, 0x1000))
        self.assertEqual((info.pf_flags, info.fourcc, info.bit_count), (0x41, None, 32))
        self.assertEqual(info.masks, (0xFF0000, 0xFF00, 0xFF, 0xFF000000))
        data = write_dds(np.zeros((360, 936, 4), np.uint8), mipmaps=True)
        info = dds_info(data)
        self.assertEqual((info.flags, info.mip_count, info.caps), (FLAGS_MIPS, 10, CAPS_MIPS))
        self.assertEqual(len(data), 1_796_960, "como colormap_water.dds")
        self.assertEqual((FLAGS, CAPS), (0x81007, 0x1000))

    def test_pixels_are_bgra_in_memory(self):
        data = write_dds(np.array([[[1, 2, 3, 4]]], np.uint8))
        self.assertEqual(data[HEADER_SIZE:], bytes([3, 2, 1, 4]))

    def test_mips_box_filter_and_sizes(self):
        rgba = np.zeros((3, 5, 4), np.uint8)
        rgba[0, 0] = rgba[0, 1] = rgba[1, 0] = (101, 101, 101, 255)
        rgba[1, 1] = (0, 0, 0, 255)
        levels = mip_levels(rgba)
        self.assertEqual([level.shape[:2] for level in levels], [(3, 5), (1, 2), (1, 1)])
        self.assertEqual(tuple(levels[1][0, 0]), (76, 76, 76, 255))   # (101·3 + 0) / 4 = 75,75, redondeado
        self.assertEqual([l.shape[:2] for l in mip_levels(np.zeros((1, 4, 4), np.uint8))], [(1, 4), (1, 2), (1, 1)])

    def test_bad_input(self):
        for array in (np.zeros((2, 2, 3), np.uint8), np.zeros((2, 2, 4), np.uint16), np.zeros((0, 2, 4), np.uint8)):
            with self.subTest(forma=array.shape, tipo=str(array.dtype)):
                with self.assertRaises(DdsError) as caught:
                    write_dds(array)
                self.assertEqual(caught.exception.code, DDS_SHAPE)


class ReadTests(unittest.TestCase):
    def test_uncompressed_layouts_of_vanilla(self):
        rgb = RNG.integers(0, 256, (2, 3, 3), dtype=np.uint8)
        alpha = RNG.integers(0, 256, (2, 3, 1), dtype=np.uint8)
        bgra = np.concatenate([rgb[..., ::-1], alpha], axis=2).tobytes()
        rgba_bytes = np.concatenate([rgb, alpha], axis=2).tobytes()
        cases = {
            "A8R8G8B8": (hand_dds(bgra, 3, 2, 32, (0xFF0000, 0xFF00, 0xFF, 0xFF000000), 0x41), alpha),
            "X8R8G8B8": (hand_dds(bgra, 3, 2, 32, (0xFF0000, 0xFF00, 0xFF, 0), 0x40), None),
            "A8B8G8R8": (hand_dds(rgba_bytes, 3, 2, 32, (0xFF, 0xFF00, 0xFF0000, 0xFF000000), 0x41), alpha),
            "R8G8B8": (hand_dds(rgb[..., ::-1].tobytes(), 3, 2, 24, (0xFF0000, 0xFF00, 0xFF, 0), 0x40), None),
        }
        for name, (data, expected_alpha) in cases.items():
            with self.subTest(formato=name):
                image = read_dds(data)
                np.testing.assert_array_equal(image.rgba[..., :3], rgb)
                np.testing.assert_array_equal(image.rgba[..., 3:], 255 if expected_alpha is None else expected_alpha)
                if name != "X8R8G8B8" or PILLOW_READS_X8:
                    np.testing.assert_array_equal(image.rgba, pillow_rgba(data))

    def test_errors(self):
        good = write_dds(np.zeros((2, 2, 4), np.uint8))
        dx10 = good[:80] + struct.pack("<I", 0x4) + b"DX10" + good[88:]
        odd_masks = good[:92] + struct.pack("<I", 0x7C00) + good[96:]
        cases = {DDS_NOT_DDS: b"PNG " + good[4:], "unsupported dx10": dx10, "unsupported masks": odd_masks,
                 DDS_TRUNCATED: good[:-1], "not dds short": good[:100]}
        expected = {DDS_NOT_DDS: DDS_NOT_DDS, "unsupported dx10": DDS_UNSUPPORTED,
                    "unsupported masks": DDS_UNSUPPORTED, DDS_TRUNCATED: DDS_TRUNCATED, "not dds short": DDS_NOT_DDS}
        for name, data in cases.items():
            with self.subTest(caso=name):
                with self.assertRaises(DdsError) as caught:
                    read_dds(data)
                self.assertEqual(caught.exception.code, expected[name])
        error = DdsError(DDS_TRUNCATED, "faltan 4 bytes")
        copy = pickle.loads(pickle.dumps(error))
        self.assertEqual((copy.code, copy.detail, str(copy)), (error.code, error.detail, str(error)))


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.game = vanilla_root()
        if self.game is None:
            self.skipTest("sin el juego base (VIC2_CORPUS)")

    def test_headers_of_vanilla(self):
        terrain = self.game / "map" / "terrain"
        water = dds_info((terrain / "colormap_water.dds").read_bytes())
        self.assertEqual((water.width, water.height, water.flags, water.mip_count, water.caps, water.pitch),
                         (936, 360, 0xA1007, 10, 0x401008, 936 * 360 * 4))
        colormap = dds_info((terrain / "colormap.dds").read_bytes())
        self.assertEqual((colormap.width, colormap.height, colormap.flags, colormap.caps), (1880, 720, 0x81007, 0x1000))
        self.assertEqual(dds_info((terrain / "colormap_no_shadow.dds").read_bytes()).fourcc, "DXT3")

    def test_rewriting_vanilla_gives_the_same_header_and_size(self):
        """Cabeceras idénticas a las de vanilla (wizard §18.5): colormap entero sale igual byte a byte."""
        terrain = self.game / "map" / "terrain"
        water = (terrain / "colormap_water.dds").read_bytes()
        rewritten = write_dds(read_dds(water).rgba, mipmaps=True)
        self.assertEqual(len(rewritten), len(water))
        self.assertEqual(rewritten[:HEADER_SIZE], water[:HEADER_SIZE])
        level0 = slice(HEADER_SIZE, HEADER_SIZE + 936 * 360 * 4)
        self.assertEqual(rewritten[level0], water[level0])
        colormap = (terrain / "colormap.dds").read_bytes()
        self.assertEqual(write_dds(read_dds(colormap).rgba), colormap)

    def test_compressed_go_through_pillow(self):
        for rel in ("map/terrain/base.dds", "map/terrain/colormap_no_shadow.dds", "gfx/load_textbg.dds"):
            path = self.game / rel
            if not path.exists():
                continue
            with self.subTest(archivo=rel):
                data = path.read_bytes()
                np.testing.assert_array_equal(read_dds(data).rgba, pillow_rgba(data))


if __name__ == "__main__":
    unittest.main()
