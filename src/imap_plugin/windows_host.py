"""Select an installed PowerShell host without changing execution policy."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess


class PowerShellUnavailable(RuntimeError):
    pass


def powershell_command(script: Path) -> list[str]:
    candidates = [os.environ.get("IMAP_PLUGIN_POWERSHELL"), shutil.which("pwsh.exe")]
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(str(Path(program_files) / "PowerShell" / "7" / "pwsh.exe"))
    candidates.append(shutil.which("powershell.exe"))
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate.casefold() in seen:
            continue
        seen.add(candidate.casefold())
        path = Path(candidate)
        if path.name.casefold() not in {"pwsh.exe", "powershell.exe"} or not path.is_file():
            continue
        try:
            result = subprocess.run(
                [str(path), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                 "@{effective=[string](Get-ExecutionPolicy); machine=[string](Get-ExecutionPolicy -Scope MachinePolicy); user=[string](Get-ExecutionPolicy -Scope UserPolicy); language=[string]($ExecutionContext.SessionState.LanguageMode)} | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if result.returncode:
                continue
            policy = json.loads(result.stdout)
            if policy.get("language") in {"ConstrainedLanguage", "RestrictedLanguage", "NoLanguage"}:
                raise PowerShellUnavailable("De beperkte PowerShell-taalmodus blokkeert het beveiligde setupvenster. Vraag je beheerder om een goedgekeurde installatie; de plugin omzeilt deze beperking niet.")
            if policy.get("language") != "FullLanguage":
                continue
            if policy.get("effective") == "Restricted":
                if any(policy.get(scope) not in {None, "Undefined"} for scope in ("machine", "user")):
                    raise PowerShellUnavailable("Het organisatiebeleid blokkeert scripts. Vraag je beheerder om een goedgekeurde installatie; de plugin wijzigt dit beleid niet.")
                continue
            if policy.get("effective") not in {"RemoteSigned", "AllSigned", "Unrestricted", "Bypass"}:
                continue
            # -File still enforces signature/download and organizational restrictions.
            return [str(path), "-NoLogo", "-NoProfile", "-STA", "-File", str(script)]
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
    raise PowerShellUnavailable("Geen beschikbare PowerShell-host mag de setup starten. Gebruik een goedgekeurde PowerShell-installatie of vraag je beheerder; beveiligingsinstellingen zijn niet gewijzigd.")
