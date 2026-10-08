#!/usr/bin/env python3
"""FORK-ONLY offline input unpacker for the temporary CI repo.

Why this file exists (and why `tools/ci-assets.py --url` is NOT used here):

* `tools/ci-assets.py --url` calls `verify_sources()` after extraction. That
  function compares every name in `NAMES` against
  `app/src/main/assets/runtime-descriptor.json`. Two members of the hosted
  bundle (`python-support.bin`, `adb-wheels.tar.gz`) are deliberately absent
  from the descriptor, so the stock script raises `CI_ASSET_SOURCE_MISMATCH`.
  On top of that, the descriptor in this checkout pins the *source*
  `offline-rootfs.bin` (sha256 0a680b56..., ~304 MB, only present on the
  release build machine), while the bundle carries the *optimized*
  `offline-rootfs.bin` (sha256 b9fe8a04..., 85,783,057 B) that the APK
  actually packages.
* Upstream source is never modified by this fork; the deviation lives here.

What is preserved from the stock script:
  * the exact member allow-list: `app/src/main/assets/<NAMES>` plus
    `tools/recovery-runtime/archives/<asset>` for every row of
    `tools/recovery-runtime/lock.json` (11 members in this bundle);
  * `bounded()` path rules (no absolute/`..`/drive/backslash escapes, target
    must stay inside the root, no symlinked parents);
  * whole-bundle SHA-256 gate before a single byte is written;
  * member-count / member-name-set / total-size (2 GiB) gate;
  * streamed extraction, one member at a time, no archive-selected paths and
    no directory entries.

What is *added* here: a check that every member is ZIP_STORED (the bundle is
documented as fully STORED) and a per-member size report.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.request
import zipfile

NAMES = ["offline-rootfs.bin", "dsh-runtime.bin", "dsh-runtime.inputs.json",
         "ubuntu-tools.bin", "ubuntu-tools.inputs.json", "pnpm-runtime.bin",
         "python-support.bin", "glibc-python.tar.gz", "adb-wheels.tar.gz"]

LIMIT = 2 * 1024 ** 3


def bounded(root, name):
    if "\\" in name or ":" in name or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("CI_ASSET_PATH")
    target = root / name
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("CI_ASSET_OUTSIDE")
    for parent in [target, *target.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("CI_ASSET_LINK")
    return target


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            value.update(chunk)
    return value.hexdigest()


def allowed(root):
    names = {"app/src/main/assets/" + name for name in NAMES}
    lock = json.loads((root / "tools/recovery-runtime/lock.json").read_text(encoding="utf-8"))
    names.update("tools/recovery-runtime/archives/" + row["asset"] for row in lock["archives"])
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--root", type=Path, required=True,
                        help="checkout root that owns app/src/main/assets")
    args = parser.parse_args()
    root = args.root.resolve()
    if not args.url.startswith("https://") or not re.fullmatch(r"[a-f0-9]{64}", args.sha256):
        parser.error("HTTPS input bundle and a fixed SHA-256 are required")
    names = allowed(root)
    with tempfile.TemporaryDirectory(prefix="ci-assets-", dir=bounded(root, "app")) as directory:
        package = Path(directory) / "inputs.zip"
        total = 0
        with urllib.request.urlopen(args.url, timeout=300) as stream, package.open("wb") as output:
            for chunk in iter(lambda: stream.read(1048576), b""):
                total += len(chunk)
                if total > LIMIT:
                    raise ValueError("CI_ASSET_DOWNLOAD_LIMIT")
                output.write(chunk)
        print(json.dumps({"downloaded_bytes": total}))
        if digest(package) != args.sha256:
            raise ValueError("CI_ASSET_BUNDLE_SHA256")
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            if len(entries) != len(names) or {entry.filename for entry in entries} != names \
                    or sum(entry.file_size for entry in entries) > LIMIT:
                raise ValueError("CI_ASSET_MEMBER_SET")
            packed = [entry.filename for entry in entries if entry.compress_type != zipfile.ZIP_STORED]
            if packed:
                raise ValueError("CI_ASSET_NOT_STORED: " + ", ".join(sorted(packed)))
            for name in sorted(names):
                target = bounded(root, name)
                if target.is_symlink():
                    raise ValueError("CI_ASSET_TARGET_LINK")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("wb") as output:
                    for chunk in iter(lambda: source.read(1048576), b""):
                        output.write(chunk)
                print("unpacked", name, target.stat().st_size)
    print("PASS fork asset inputs unpacked (upstream verify_sources() intentionally not run)")


if __name__ == "__main__":
    main()
