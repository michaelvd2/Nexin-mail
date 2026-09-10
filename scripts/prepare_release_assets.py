"""Preserve a verified platform package with public, path-free provenance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from scripts.release_check import inspect_archive

PLATFORMS = ("windows-x64", "macos-arm64")


def prepare(archive: Path, platform: str, output: Path, commit: str, build_url: str) -> dict:
    if platform not in PLATFORMS:
        raise ValueError("unsupported release platform")
    checked = inspect_archive(archive)
    output.mkdir(parents=True, exist_ok=False)
    name = f"Nexin-Mail-0.2.0-{platform}.zip"
    shutil.copyfile(archive, output / name)
    (output / f"SHA256SUMS-{platform}.txt").write_text(f"{checked['sha256']}  {name}\n", encoding="ascii")
    provenance = {
        "product": "nexin-mail", "version": "0.2.0", "platform": platform,
        "source_commit": commit, "build_url": build_url, "archive": name,
        "sha256": checked["sha256"], "signing": "not_attested",
        "customer_installation": "not_checked",
    }
    (output / f"build-provenance-{platform}.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--build-url", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.archive, args.platform, args.output, args.commit, args.build_url)))
