from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "receipts" / "sbom.cdx.json"


def component(name: str, version: str, ecosystem: str) -> dict[str, object]:
    return {
        "type": "library",
        "name": name,
        "version": version,
        "purl": f"pkg:{ecosystem}/{name}@{version}",
    }


def main() -> None:
    components: list[dict[str, object]] = []
    for line in (ROOT / "requirements-runtime.lock").read_text(encoding="utf-8").splitlines():
        if "==" not in line or line.lstrip().startswith("#"):
            continue
        requirement = Requirement(line)
        versions = [item.version for item in requirement.specifier if item.operator == "=="]
        if len(versions) != 1:
            raise RuntimeError(f"dependency is not exactly pinned: {line}")
        item = component(requirement.name, versions[0], "pypi")
        if requirement.marker is not None:
            item["properties"] = [{"name": "environment-marker", "value": str(requirement.marker)}]
        components.append(item)
    components.sort(key=lambda item: (str(item["purl"])))
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    value = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {
                "type": "application",
                "name": "imap-plugin",
                "version": str(manifest["version"]),
                "hashes": [{"alg": "SHA-256", "content": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}],
            },
        },
        "components": components,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
