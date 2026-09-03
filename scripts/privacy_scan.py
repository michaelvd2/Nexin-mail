from __future__ import annotations

import re
import sys
from pathlib import Path


BLOCKED_TEXT = (
    "c:" + "\\users\\",
    "c:" + "/users/",
    "kart" + "plaza",
    "mic" + "ha",
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*['\"][^'\"\r\n]{4,}"),
    re.compile(r"\bgh[oprsu]_[A-Za-z0-9_]{20,}\b"),
)
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,}|example\.test)\b")
ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "example.test",
    "users.noreply.github.com",
}
ALLOWED_EMAIL_ADDRESSES = {
    "49699333+dependabot[bot]@users.noreply.github.com",
    "noreply@github.com",
    "support@github.com",
}
SKIP_PARTS = {".git", ".pytest_cache", ".venv", "__pycache__", "dist", "receipts", "runtime"}
TEXT_SUFFIXES = {".cmd", ".json", ".lock", ".md", ".ps1", ".py", ".sh", ".toml", ".txt", ".yml", ".yaml"}


def candidate_files(root: Path):
    for path in root.rglob("*"):
        relative_path = path.relative_to(root)
        if not path.is_file() or any(part in SKIP_PARTS for part in relative_path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", ".gitignore"}:
            yield path


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    findings: list[str] = []
    scanned = 0
    for path in candidate_files(root):
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"non-UTF-8 text file: {path.relative_to(root).as_posix()}")
            continue
        lowered = text.casefold()
        for blocked in BLOCKED_TEXT:
            if blocked in lowered:
                findings.append(f"blocked personal marker '{blocked}': {path.relative_to(root).as_posix()}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"possible secret: {path.relative_to(root).as_posix()}")
        for match in EMAIL_PATTERN.finditer(text):
            if match.group(0).casefold() in ALLOWED_EMAIL_ADDRESSES:
                continue
            domain = match.group(1).casefold()
            if domain not in ALLOWED_EMAIL_DOMAINS and not domain.endswith((".test", ".example", ".invalid")):
                findings.append(f"non-example email domain '{domain}': {path.relative_to(root).as_posix()}")
    if findings:
        print(f"privacy scan failed ({len(findings)} finding(s), {scanned} file(s) scanned)")
        for finding in sorted(set(findings)):
            print(f"- {finding}")
        return 3
    print(f"privacy scan passed ({scanned} file(s) scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
