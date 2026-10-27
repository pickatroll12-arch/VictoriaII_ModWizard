"""Banderas TGA (``core/gfx/flags.py``, wizard §14.2 y H22): 32 bits, 93×64, origen abajo a la izquierda."""

import io
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import vanilla_root  # noqa: E402

from vic2studio.core.gfx import flags  # noqa: E402
from vic2studio.core.gfx.flags import FLAG_SIZE, FLAG_SUFFIXES, fit_flag, make_flag_set, write_tga  # noqa: E402

RED, BLUE, GREEN = (200, 0, 0, 255), (0, 0, 200, 255), (0, 255, 0, 0)


def halves(size, left, right, *, vertical=False) -> Image.Image:
    """Imagen partida en dos colores: izquierda/derecha (o arriba/abajo con ``vertical``)."""
    image = Image.new("RGBA", size, left)
    box = (0, size[1] // 2, size[0], size[1]) if vertical else (size[0] // 2, 0, size[0], size[1])
    image.paste(right, box)
    return image


def reread(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGBA"))


class WriteTgaTests(unittest.TestCase):
    def test_header_and_orientation(self):
        rgba = np.zeros((2, 3, 4), np.uint8)
        rgba[0, 0] = (255, 0, 0, 128)                        # arriba a la izquierda
        data = write_tga(rgba)
        self.assertEqual((data[2], data[16], data[17]), (2, 32, 0x08))
        self.assertEqual(int.from_bytes(data[12:14], "little"), 3)
        self.assertEqual(int.from_bytes(data[14:16], "little"), 2)
        np.testing.assert_array_equal(reread(data), rgba)
        last_row = 18 + 1 * 3 * 4                            # de abajo arriba: la fila 0 va al final
        self.assertEqual(data[last_row:last_row + 4], bytes([0, 0, 255, 128]), "BGRA")

    def test_bad_input(self):
        for array in (np.zeros((2, 2, 3), np.uint8), np.zeros((2, 2, 4), np.float32), np.zeros((0, 3, 4), np.uint8)):
            with self.subTest(forma=array.shape):
                with self.assertRaises(ValueError):
                    write_tga(array)


class FitFlagTests(unittest.TestCase):
    def assert_flag(self, image):
        self.assertEqual((image.size, image.mode), (FLAG_SIZE, "RGBA"))

    def test_cover_crops_around_the_focus(self):
        wide = halves((300, 100), RED, BLUE)
        centre = fit_flag(wide)
        self.assert_flag(centre)
        pixels = np.asarray(centre)
        self.assertEqual(tuple(pixels[32, 5]), RED)
        self.assertEqual(tuple(pixels[32, 88]), BLUE)
        self.assertEqual(tuple(np.asarray(fit_flag(wide, focus=(0, 0.5)))[32, 88]), RED)
        self.assertEqual(tuple(np.asarray(fit_flag(wide, focus=(1, 0.5)))[32, 5]), BLUE)
        tall = halves((50, 400), RED, BLUE, vertical=True)
        self.assertEqual(tuple(np.asarray(fit_flag(tall, focus=(0.5, 0)))[60, 46]), RED)
        self.assertEqual(tuple(np.asarray(fit_flag(tall, focus=(0.5, 1)))[3, 46]), BLUE)

    def test_contain_pads_with_transparency(self):
        image = fit_flag(Image.new("RGB", (186, 64), (10, 20, 30)), mode="contain")
        self.assert_flag(image)
        pixels = np.asarray(image)
        self.assertEqual(pixels[0, 46, 3], 0, "arriba, transparente")
        self.assertEqual(pixels[63, 46, 3], 0, "abajo, transparente")
        self.assertEqual(tuple(pixels[32, 46]), (10, 20, 30, 255))

    def test_stretch_deforms(self):
        image = fit_flag(halves((10, 10), RED, BLUE), mode="stretch")
        self.assert_flag(image)
        self.assertEqual(tuple(np.asarray(image)[32, 2]), RED)
        self.assertEqual(tuple(np.asarray(image)[32, 90]), BLUE)

    def test_a_flag_sized_image_is_untouched(self):
        source = np.random.default_rng(3).integers(0, 256, (64, 93, 3), dtype=np.uint8)
        image = fit_flag(Image.fromarray(source, "RGB"))
        np.testing.assert_array_equal(np.asarray(image)[..., :3], source)
        self.assertTrue((np.asarray(image)[..., 3] == 255).all())

    def test_downscaling_filters_instead_of_sampling(self):
        """Un tablero de 1 px a la mitad sale del color medio: se filtra, no se toma un píxel de cada dos."""
        rows, cols = np.indices((128, 186))
        board = np.where(((rows + cols) % 2 == 0)[..., None], RED, BLUE).astype(np.uint8)
        pixels = np.asarray(fit_flag(Image.fromarray(board, "RGBA"), mode="stretch"))[5:-5, 5:-5]
        self.assertTrue((abs(pixels[..., 0].astype(int) - 100) <= 2).all(), "rojo medio")
        self.assertTrue((abs(pixels[..., 2].astype(int) - 100) <= 2).all(), "azul medio")

    def test_transparent_colour_does_not_bleed(self):
        """Alfa premultiplicado: el verde de los píxeles transparentes no tiñe el borde al escalar."""
        image = halves((40, 40), RED, GREEN)
        pixels = np.asarray(fit_flag(image, mode="stretch"))
        visible = pixels[pixels[..., 3] > 0]
        self.assertLess(int(visible[..., 1].max()), 8, "el verde transparente se coló en el borde")

    def test_other_modes(self):
        palette = Image.new("P", (186, 128))
        palette.putpalette([255, 0, 0] * 256)
        palette.info["transparency"] = 0
        self.assertEqual(np.asarray(fit_flag(palette))[10, 10, 3], 0)
        self.assert_flag(fit_flag(Image.new("L", (20, 30), 128)))
        with self.assertRaises(ValueError):
            fit_flag(Image.new("RGB", (5, 5)), mode="zoom")


class FlagSetTests(unittest.TestCase):
    def test_five_verified_tgas(self):
        images = {suffix: halves((120, 80), RED, BLUE) for suffix in FLAG_SUFFIXES}
        result = make_flag_set(images)
        self.assertEqual(list(result), list(FLAG_SUFFIXES))
        for suffix, data in result.items():
            with self.subTest(sufijo=suffix):
                self.assertEqual(len(data), 18 + 93 * 64 * 4)
                np.testing.assert_array_equal(reread(data), np.asarray(fit_flag(images[suffix])))
        with self.assertRaises(ValueError):
            make_flag_set({"_democracy": Image.new("RGB", FLAG_SIZE)})

    def test_a_flag_that_does_not_reread_is_refused(self):
        rgba = np.asarray(fit_flag(Image.new("RGB", FLAG_SIZE, (1, 2, 3))))
        other = write_tga(np.zeros_like(rgba))
        with self.assertRaises(ValueError):
            flags._verified(other, rgba)
        self.assertEqual(flags._verified(write_tga(rgba), rgba), write_tga(rgba))


class CorpusTests(unittest.TestCase):
    def test_vanilla_flags_survive_unchanged(self):
        game = vanilla_root()
        if game is None:
            self.skipTest("sin el juego base (VIC2_CORPUS)")
        folder = game / "gfx" / "flags"
        samples = []
        for path in sorted(folder.glob("*.tga")):
            with Image.open(path) as image:
                if image.size == FLAG_SIZE and image.mode not in {m for _, m in samples}:
                    samples.append((path, image.mode))
            if len(samples) == 2:
                break
        self.assertTrue(samples)
        for path, mode in samples:
            with self.subTest(bandera=path.name, modo=mode):
                with Image.open(path) as image:
                    original = np.asarray(image.convert("RGBA"))
                    fitted = fit_flag(image)
                np.testing.assert_array_equal(np.asarray(fitted), original)
                np.testing.assert_array_equal(reread(write_tga(np.asarray(fitted))), original)


if __name__ == "__main__":
    unittest.main()
