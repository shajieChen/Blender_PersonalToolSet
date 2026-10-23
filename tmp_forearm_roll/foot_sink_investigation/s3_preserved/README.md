# S3 preserved experiment (do not overwrite)

- Scheme: skin-geometry feedback recheck + hard minimum knee 15 degrees
  (`ik._CONTACT_MIN_KNEE_DEG = 15.0`, `_CONTACT_MAX_RAISE = None`,
  no knee smoothing; smoothing switch did not exist yet at capture time).
- Runner: `scan_frames.py -- B skin_scan_s3.csv S3`, Blender 5.1.2 headless,
  single action `a050_300000`, frames 0-52, no .blend saved.
- Result summary: 0 frames below -0.01 m; worst mesh lowest -0.001 m;
  full-clip minimum knee 15.0 deg (frame 16, left); frame 17 left knee 15.0 deg,
  left foot lowest 0.158 m; max toe-Z step 0.1267 m (frame 18, left).
- File: `skin_scan_s3.csv`
  SHA256 `30EB6793646F1359B1AFD3DB672064A9D263C62C0194F4111B5C08E64E695309`
- Copy `ik.py` at capture time SHA256
  `36606B9538545E68D09188674AE7E10BD6E603FA124B5010F74417733B76E03A`
  (before `_CONTACT_KNEE_SMOOTH_DEG` was added; that addition defaults to
  None, so S3 behaviour is unchanged when the switch is unset).
- To reproduce: check out the copy state above, run the runner command,
  compare the CSV byte-for-byte or by the summary numbers.
