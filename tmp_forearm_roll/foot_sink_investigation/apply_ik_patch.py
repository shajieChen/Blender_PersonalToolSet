"""Apply the reviewed ik.py diff onto the installed addon, then bump to 1.7.6."""
import hashlib
import shutil
from pathlib import Path

OFFICIAL = Path(r"C:\Users\chenshajie1\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\humanoid_retarget")
CANDIDATE = Path(r"H:\Blender_Plugin\tmp_forearm_roll\candidate_root\humanoid_retarget\ik.py")
DIFF = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation\candidate_ik.diff")
BACKUP = Path(r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation\backup_official_1.7.5")
EXPECTED_IK = "AD87866E49A40A711A3344C1868CE54A768DA779BA29B355C523E4F7A84A6A08"


def sha256(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    return digest


def split_lines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def apply_diff(original, diff_text):
    source = split_lines(original)
    diff = split_lines(diff_text)
    output = []
    index = 0
    cursor = 0
    while cursor < len(diff) and not diff[cursor].startswith("@@"):
        cursor += 1
    while cursor < len(diff):
        if not diff[cursor].startswith("@@"):
            raise SystemExit("unexpected diff line: " + diff[cursor])
        old_start = int(diff[cursor].split()[1].split(",")[0][1:])
        while index < old_start - 1:
            output.append(source[index])
            index += 1
        cursor += 1
        while cursor < len(diff) and not diff[cursor].startswith("@@"):
            line = diff[cursor]
            cursor += 1
            if line.startswith("\\"):
                continue
            if line.startswith(" "):
                if source[index] != line[1:]:
                    raise SystemExit("context mismatch at line %s" % (index + 1))
                output.append(source[index])
                index += 1
            elif line.startswith("-"):
                if source[index] != line[1:]:
                    raise SystemExit("removal mismatch at line %s" % (index + 1))
                index += 1
            elif line.startswith("+"):
                output.append(line[1:])
            elif line == "":
                continue
            else:
                raise SystemExit("bad diff line: " + line)
    output.extend(source[index:])
    return "\n".join(output)


def main():
    ik_path = OFFICIAL / "ik.py"
    init_path = OFFICIAL / "__init__.py"
    current = sha256(ik_path)
    if current != EXPECTED_IK:
        raise SystemExit("official ik.py hash changed: " + current)
    diff_bytes = DIFF.read_bytes()
    if diff_bytes.startswith(b"\xff\xfe") or diff_bytes.startswith(b"\xfe\xff"):
        diff_text = diff_bytes.decode("utf-16")
    else:
        diff_text = diff_bytes.decode("utf-8")
    patched = apply_diff(ik_path.read_text(encoding="utf-8"), diff_text)
    expected = "\n".join(split_lines(CANDIDATE.read_text(encoding="utf-8")))
    if patched != expected:
        raise SystemExit("patched ik.py does not match the reviewed candidate")
    init_text = init_path.read_text(encoding="utf-8")
    needle = '"version": (1, 7, 5),'
    if init_text.count(needle) != 1:
        raise SystemExit("version line is not the single 1.7.5 marker")
    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ik_path, BACKUP / "ik.py")
    shutil.copy2(init_path, BACKUP / "__init__.py")
    if sha256(BACKUP / "ik.py") != EXPECTED_IK:
        raise SystemExit("backup hash mismatch")
    newline = "\r\n" if "\r\n" in ik_path.read_bytes().decode("utf-8") else "\n"
    ik_path.write_text(patched.replace("\n", newline), encoding="utf-8", newline="")
    # write_text newline="" keeps the newlines already in the string.
    init_path.write_text(init_text.replace(needle, '"version": (1, 7, 6),', 1), encoding="utf-8")
    print("IK_AFTER", sha256(ik_path))
    print("INIT_AFTER", sha256(init_path))
    print("BACKUP_IK", sha256(BACKUP / "ik.py"))
    print("APPLIED")


if __name__ == "__main__":
    main()
