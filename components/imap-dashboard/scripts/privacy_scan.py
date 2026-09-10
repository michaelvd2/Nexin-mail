from __future__ import annotations

import re
import sys
from pathlib import Path


IGNORED_PARTS = {".git", ".venv", "_backend", "node_modules", "dist", "receipts", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {
    ".cmd", ".css", ".html", ".json", ".lock", ".md", ".ps1", ".py",
    ".sh", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}
PRIVATE_MARKERS = (
    "kart" + "plaza",
    "mich" + "ael",
    "mich" + "aelvd2",
    "c:" + "\\users\\",
    "/users/" + "mic" + "ha",
)
EMAIL_RE = re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z][a-z0-9-]*\b")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*['\"][^'\"\r\n]{4,}['\"]"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
ALLOWED_EMAIL_ADDRESSES = {
    "49699333+dependabot[bot]@users.noreply.github.com",
    "noreply@github.com",
    "support@github.com",
}


def allowed_demo_address(address: str) -> bool:
    if address.casefold() in ALLOWED_EMAIL_ADDRESSES:
        return True
    domain = address.rsplit("@", 1)[-1].casefold()
    return domain.endswith(".test") or domain.endswith(".example") or domain.endswith(".invalid")


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        if not path.is_file() or any(part in IGNORED_PARTS for part in relative_path.parts):
            continue
        if path.suffix.casefold() not in TEXT_SUFFIXES and path.name not in {"LICENSE"}:
            continue
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8-sig", errors="strict")
        lowered = text.casefold()
        for marker in PRIVATE_MARKERS:
            if marker in lowered:
                findings.append(f"{relative}: private marker")
        if SECRET_ASSIGNMENT_RE.search(text):
            findings.append(f"{relative}: likely embedded secret assignment")
        if PRIVATE_KEY_RE.search(text):
            findings.append(f"{relative}: private key material")
        for address in EMAIL_RE.findall(text):
            if not allowed_demo_address(address):
                findings.append(f"{relative}: non-example email address")
    return sorted(set(findings))


def main() -> None:
    root = (Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()).resolve()
    findings = scan(root)
    if findings:
        print("privacy scan failed")
        for finding in findings:
            print(f"- {finding}")
        raise SystemExit(1)
    count = sum(
        1 for path in root.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_PARTS for part in path.relative_to(root).parts)
    )
    print(f"privacy scan passed ({count} file(s) scanned)")


if __name__ == "__main__":
    main()
