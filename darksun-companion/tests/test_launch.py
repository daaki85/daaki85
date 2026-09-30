import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import launch


def make_game(root: str, cloud_saves: bool) -> str:
    game = os.path.join(root, "Dark Sun Shattered Lands")
    os.makedirs(os.path.join(game, "DOSBOX"))
    for path in ("DSUN.EXE", os.path.join("DOSBOX", "DOSBox.exe"), "dosbox_darksun.conf"):
        open(os.path.join(game, path), "w").close()
    if cloud_saves:
        os.mkdir(os.path.join(game, "cloud_saves"))
    return game


class LaunchTests(unittest.TestCase):
    def test_recognises_the_game_folder(self):
        with tempfile.TemporaryDirectory() as d:
            game = make_game(d, cloud_saves=False)
            self.assertTrue(launch.is_game_dir(game))
            self.assertFalse(launch.is_game_dir(d))
            self.assertEqual(launch.find_game_dir(game), game)

    def test_conf_loads_the_helper_before_the_game(self):
        with tempfile.TemporaryDirectory() as d:
            game = make_game(d, cloud_saves=True)
            conf = launch.write_conf(game, os.path.join(d, "test.conf"))
            with open(conf, newline="") as f:
                text = f.read()
        lines = text.split("\r\n")
        self.assertIn("[autoexec]", lines)
        self.assertIn(r'mount C "..\cloud_saves" -t overlay', lines)
        self.assertIn(f'mount d "{launch.DOS_DIR}"', lines)
        self.assertLess(lines.index(r"lh d:\dsclog.exe"), lines.index(r"d:\dsunlog.exe"))
        self.assertLess(lines.index("c:"), lines.index(r"d:\dsunlog.exe"))  # run from the game folder
        self.assertEqual(lines[-2:], ["exit", ""])

    def test_a_window_three_times_the_game_unless_asked_otherwise(self):
        self.assertEqual(launch.display_lines({}),
                         ["[sdl]", "fullscreen=false", "[render]", "aspect=true", "scaler=normal3x", ""])
        self.assertIn("scaler=normal3x", launch.display_lines({"window_scale": 3}))
        self.assertIn("scaler=none", launch.display_lines({"window_scale": 1}))
        self.assertIn("scaler=normal3x", launch.display_lines({"window_scale": 7}))
        self.assertIn("scaler=normal2x", launch.display_lines({"window_scale": 2}))
        four = launch.display_lines({"window_scale": 4})
        self.assertIn("windowresolution=1280x960", four)
        self.assertIn("output=opengl", four)
        self.assertEqual(launch.display_lines({"fullscreen": True}), [])  # GOG's own full screen
        saved = launch.load_settings
        launch.load_settings = lambda: {}
        try:
            with tempfile.TemporaryDirectory() as d:
                game = make_game(d, cloud_saves=False)
                with open(launch.write_conf(game, os.path.join(d, "test.conf")), newline="") as f:
                    lines = f.read().split("\r\n")
        finally:
            launch.load_settings = saved
        self.assertLess(lines.index("fullscreen=false"), lines.index("[autoexec]"))

    def test_without_the_dice_log_it_runs_the_game_as_usual(self):
        with tempfile.TemporaryDirectory() as d:
            game = make_game(d, cloud_saves=False)
            with open(launch.write_conf(game, os.path.join(d, "test.conf"), dice_log=False)) as f:
                text = f.read()
        self.assertIn("darksun\n", text)
        self.assertNotIn("dsclog", text)

    def test_unknown_game_version_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            game = make_game(d, cloud_saves=False)
            self.assertIn("GOG release", launch.prepare_patched_game(game))

    def test_no_overlay_mount_without_cloud_saves(self):
        with tempfile.TemporaryDirectory() as d:
            game = make_game(d, cloud_saves=False)
            with open(launch.write_conf(game, os.path.join(d, "test.conf"))) as f:
                self.assertNotIn("cloud_saves", f.read())


if __name__ == "__main__":
    unittest.main()
