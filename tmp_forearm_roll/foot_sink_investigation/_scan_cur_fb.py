"""Extra F2 attribution bake: CURRENT reference with sole fallback (sigma=0)."""
import sys
from pathlib import Path

sys.path.insert(0, r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation")
import pelvis_fix_scan as scan
import humanoid_retarget.retarget as retarget

scan.world["data"] = scan.load_world()
real_sole = retarget._reference_sole_height
retarget._reference_sole_height = lambda *a, **k: None
try:
    scan.bake_and_scan("CURFB0", "a050_300000", 0.0, mode="CURRENT")
finally:
    retarget._reference_sole_height = real_sole
with (scan.OUT / "pelvis_fix_curfb_frames.csv").open("w", newline="", encoding="utf-8") as handle:
    import csv
    writer = csv.DictWriter(handle, fieldnames=list(scan.rows[0].keys()))
    writer.writeheader()
    writer.writerows(scan.rows)
print("CURFB_DONE", len(scan.rows), flush=True)
