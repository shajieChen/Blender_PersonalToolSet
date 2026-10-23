import sys

import bpy

sys.path.insert(0, r"H:\Blender_Plugin\tests")
import run_retarget_test

bpy.ops.wm.read_factory_settings(use_empty=True)
run_retarget_test.test_forearm_chain_twist_signs()
print("FOREARM_ONLY_OK")
