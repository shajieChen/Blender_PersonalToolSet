import os
import tempfile
import unittest

from humanoid_retarget.environment import (
    EnvironmentError,
    load_environment,
    normalized_environment,
    save_environment,
)


class EnvironmentTests(unittest.TestCase):
    def test_defaults_are_gentler_than_blender_defaults(self):
        data = normalized_environment({})
        self.assertTrue(data["enabled"])
        self.assertEqual(data["shading"], "MATERIAL")
        self.assertLess(data["studio_intensity"], 1.0)
        self.assertLess(data["world_strength"], 1.0)
        self.assertLess(data["exposure"], 0.0)

    def test_invalid_shading_falls_back_to_material(self):
        data = normalized_environment({"shading": "bogus"})
        self.assertEqual(data["shading"], "MATERIAL")

    def test_values_are_clamped(self):
        data = normalized_environment(
            {"studio_intensity": 99.0, "world_strength": -5.0, "exposure": 42.0}
        )
        self.assertEqual(data["studio_intensity"], 2.0)
        self.assertEqual(data["world_strength"], 0.0)
        self.assertEqual(data["exposure"], 3.0)

    def test_world_color_accepts_rgb(self):
        data = normalized_environment({"world_color": [0.1, 0.2, 0.3]})
        self.assertEqual(data["world_color"], (0.1, 0.2, 0.3, 1.0))

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = save_environment(
                os.path.join(folder, "dim"),
                {
                    "shading": "TEXTURE",
                    "studio_intensity": 0.25,
                    "world_strength": 0.1,
                    "world_color": [0.01, 0.02, 0.03, 1.0],
                    "exposure": -0.8,
                },
            )
            self.assertTrue(path.endswith(".json"))
            loaded = load_environment(path)
            self.assertEqual(loaded["shading"], "TEXTURE")
            self.assertAlmostEqual(loaded["studio_intensity"], 0.25)
            self.assertAlmostEqual(loaded["exposure"], -0.8)

    def test_load_missing_file_raises(self):
        with self.assertRaises(EnvironmentError):
            load_environment(os.path.join(tempfile.gettempdir(), "no_such_env.json"))


if __name__ == "__main__":
    unittest.main()
