import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import gamepatch


def fake_dsun() -> bytearray:
    data = bytearray(gamepatch.GOG_SIZE)
    for p in gamepatch.PATCHES:
        data[p.offset:p.offset + len(p.original)] = p.original
    return data


class GamePatchTests(unittest.TestCase):
    def test_patches_replace_known_bytes_only(self):
        original = fake_dsun()
        patched = gamepatch.patched(bytes(original))
        self.assertEqual(len(patched), len(original))
        changed = [i for i in range(len(original)) if original[i] != patched[i]]
        self.assertTrue(all(any(p.offset <= i < p.offset + len(p.original) for p in gamepatch.PATCHES)
                            for i in changed))
        rand = gamepatch.PATCHES[0]
        self.assertEqual(patched[rand.offset:rand.offset + 2], bytes((0xCD, gamepatch.VEC_RAND)))
        for p in gamepatch.PATCHES:
            self.assertEqual(len(p.replacement), len(p.original))

    def test_other_versions_are_refused(self):
        with self.assertRaisesRegex(gamepatch.PatchError, "GOG release"):
            gamepatch.patched(bytes(1000))
        data = fake_dsun()
        data[gamepatch.PATCHES[1].offset] ^= 0xFF
        with self.assertRaisesRegex(gamepatch.PatchError, "save differs"):
            gamepatch.patched(bytes(data))

    def test_write_patched_leaves_the_original_alone(self):
        with tempfile.TemporaryDirectory() as d:
            src, dest = os.path.join(d, "DSUN.EXE"), os.path.join(d, "DSUNLOG.EXE")
            with open(src, "wb") as f:
                f.write(fake_dsun())
            gamepatch.write_patched(src, dest)
            gamepatch.write_patched(src, dest)  # again: nothing to do
            with open(src, "rb") as f:
                self.assertEqual(f.read(), bytes(fake_dsun()))
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), gamepatch.patched(bytes(fake_dsun())))


if __name__ == "__main__":
    unittest.main()
