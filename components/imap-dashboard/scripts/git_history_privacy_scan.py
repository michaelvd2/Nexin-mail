from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


BLOCKED_BYTES = (
    b"c:" + b"\\users\\",
    b"c:" + b"/users/",
    b"/users/" + b"mic" + b"ha",
    b"kart" + b"plaza",
    b"mic" + b"hael",
)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        rb"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)"
        rb"\s*[:=]\s*['\"][^'\"\r\n]{4,}"
    ),
    re.compile(rb"\bgh[oprsu]_[A-Za-z0-9_]{20,}\b"),
)
EMAIL_PATTERN = re.compile(rb"(?i)\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,}|example\.test)\b")
ALLOWED_EMAIL_DOMAINS = {
    b"example.com",
    b"example.net",
    b"example.org",
    b"example.test",
    b"users.noreply.github.com",
}
ALLOWED_EMAIL_ADDRESSES = {
    b"49699333+dependabot[bot]@users.noreply.github.com",
    b"noreply@github.com",
    b"support@github.com",
}
ALLOWED_AUTHOR_NAMES = {"IMAP Plugin contributors", "dependabot[bot]", "GitHub"}


def identity_is_allowed(name: str, email: str) -> bool:
    address = email.casefold().encode("utf-8")
    domain = email.rpartition("@")[2].casefold()
    return name in ALLOWED_AUTHOR_NAMES and (
        address in ALLOWED_EMAIL_ADDRESSES
        or domain in {item.decode("ascii") for item in ALLOWED_EMAIL_DOMAINS}
    )


def _git(root: Path, *args: str, text: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=text,
    )
    if result.returncode != 0:
        error = result.stderr.strip() if text else result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {error}")
    return result.stdout


def _scan_bytes(data: bytes, location: str) -> list[str]:
    lowered = data.lower()
    findings: list[str] = []
    if any(marker in lowered for marker in BLOCKED_BYTES):
        findings.append(f"personal marker in {location}")
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        findings.append(f"possible secret in {location}")
    for match in EMAIL_PATTERN.finditer(data):
        if match.group(0).lower() in ALLOWED_EMAIL_ADDRESSES:
            continue
        domain = match.group(1).lower()
        if domain not in ALLOWED_EMAIL_DOMAINS and not domain.endswith((b".test", b".example", b".invalid")):
            findings.append(f"non-example email domain in {location}")
            break
    return findings


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not (root / ".git").exists():
        raise SystemExit("git history privacy scan requires a repository checkout")

    findings: list[str] = []
    objects = str(_git(root, "rev-list", "--objects", "--all", text=True)).splitlines()
    seen: set[str] = set()
    scanned_objects = 0
    for line in objects:
        object_id, _, path = line.partition(" ")
        if path:
            findings.extend(_scan_bytes(path.encode("utf-8", "surrogatepass"), f"path {path}"))
        if object_id in seen:
            continue
        seen.add(object_id)
        object_type = str(_git(root, "cat-file", "-t", object_id, text=True)).strip()
        if object_type not in {"blob", "commit", "tag"}:
            continue
        scanned_objects += 1
        content = bytes(_git(root, "cat-file", object_type, object_id))
        findings.extend(_scan_bytes(content, f"{path or object_type} ({object_id[:12]})"))

    identities = str(_git(root, "log", "--all", "--format=%an%x00%ae%x00%cn%x00%ce", text=True)).splitlines()
    for identity in identities:
        parts = identity.split("\x00")
        if len(parts) != 4:
            findings.append("unparseable author identity")
            continue
        author_name, author_email, committer_name, committer_email = parts
        if author_name not in ALLOWED_AUTHOR_NAMES or committer_name not in ALLOWED_AUTHOR_NAMES:
            findings.append("non-generic Git author or committer name")
        if not identity_is_allowed(author_name, author_email) or not identity_is_allowed(
            committer_name, committer_email
        ):
            findings.append("non-generic Git author or committer email")

    unique = sorted(set(findings))
    if unique:
        print(f"git history privacy scan failed ({len(unique)} finding(s))")
        for finding in unique:
            print(f"- {finding}")
        return 3
    print(f"git history privacy scan passed ({scanned_objects} commit/tag/blob object(s) scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
