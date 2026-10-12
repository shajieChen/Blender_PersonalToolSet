import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if (HERE / "shortcut_hint").is_dir():
    ROOT = HERE / "shortcut_hint"
else:
    ROOT = HERE.parent / "shortcut_hint"


def load(name):
    path = ROOT / (name + ".py")
    spec = importlib.util.spec_from_file_location("shortcut_hint_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


chords = load("chords")
hotspots = load("hotspots")


class ChordTests(unittest.TestCase):
    def test_move_view_uses_shift_and_middle_mouse_not_the_trackpad(self):
        items = [
            {"type": "TRACKPADPAN", "shift": True, "ctrl": False, "alt": False, "oskey": False},
            {"type": "MIDDLEMOUSE", "shift": True, "ctrl": False, "alt": False, "oskey": False},
        ]
        chips = chords.binding_for("view3d.move", items, "zh_CN")
        self.assertEqual(
            chips,
            [{"text": "Shift", "kind": "mod"}, {"text": "中键", "kind": "mouse"}],
        )

    def test_factory_move_matches_the_default_keymap(self):
        chips = chords.binding_for("view3d.move", [], "en_US")
        self.assertEqual([chip["text"] for chip in chips], ["Shift", "MMB"])
        self.assertEqual(chips[0]["kind"], "mod")
        self.assertEqual(chips[1]["kind"], "mouse")

    def test_zoom_prefers_ctrl_middle_mouse_over_the_wheel(self):
        items = [
            {"type": "WHEELINMOUSE", "shift": False, "ctrl": False, "alt": False, "oskey": False},
            {"type": "MIDDLEMOUSE", "shift": False, "ctrl": True, "alt": False, "oskey": False},
        ]
        chips = chords.binding_for("view3d.zoom", items, "zh_CN")
        self.assertEqual([chip["text"] for chip in chips], ["Ctrl", "中键"])

    def test_camera_uses_numpad_zero(self):
        chips = chords.binding_for("view3d.view_camera", [], "zh_CN")
        self.assertEqual(chips, [{"text": "小键盘0", "kind": "key"}])


class HotspotTests(unittest.TestCase):
    def spots(self, **overrides):
        values = dict(
            ui_scale=1.0,
            gizmo_size=80,
            mini_axis_type="GIZMO",
            mini_axis_size=25,
            show_navigate=True,
            show_gizmo=True,
            view_perspective="PERSP",
            lock_rotation=False,
        )
        values.update(overrides)
        return hotspots.navigation_hotspots(400, 300, **values)

    def test_move_button_sits_under_zoom_on_the_right(self):
        spots = self.spots()
        move = next(spot for spot in spots if spot["id"] == "move")
        zoom = next(spot for spot in spots if spot["id"] == "zoom")
        self.assertAlmostEqual(move["cx"], 378)
        self.assertAlmostEqual(move["cy"], 160)
        self.assertLess(move["cy"], zoom["cy"])
        self.assertEqual(hotspot_at_id(spots, move["cx"], move["cy"]), "move")

    def test_hovering_the_hand_button_does_not_hit_zoom(self):
        spots = self.spots()
        move = next(spot for spot in spots if spot["id"] == "move")
        self.assertEqual(hotspots.hotspot_at(spots, move["cx"], move["cy"])["id"], "move")

    def test_chip_sits_under_the_lowest_button(self):
        spots = self.spots()
        persp = next(spot for spot in spots if spot["id"] == "persp")
        anchor = hotspots.chip_anchor(spots, gap=8)
        self.assertAlmostEqual(anchor["top"], persp["cy"] - persp["radius"] - 8)
        self.assertGreater(anchor["right"], persp["cx"])

    def test_camera_view_drops_the_perspective_button(self):
        ids = [spot["id"] for spot in self.spots(view_perspective="CAMERA")]
        self.assertEqual(ids, ["rotate", "zoom", "move", "camera"])

    def test_hidden_gizmo_has_no_hotspots(self):
        self.assertEqual(self.spots(show_gizmo=False), [])

    def test_chip_stays_inside_a_short_region(self):
        x, y = hotspots.place_chip(30, 10, 80, 24, 400, 300, 8)
        self.assertGreaterEqual(x, 8)
        self.assertGreaterEqual(y, 8)
        self.assertLessEqual(x + 80, 392)


def hotspot_at_id(spots, x, y):
    found = hotspots.hotspot_at(spots, x, y)
    return None if found is None else found["id"]


if __name__ == "__main__":
    unittest.main()
