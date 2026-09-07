"""Nonsecret, declarative recovery advice. Never executes a repair or grants access."""
from __future__ import annotations

from typing import Any

from .config import _validated_hostname


# stage, explanation, checks, next action, prerequisite for ONE recovery attempt.
_ROUTES = {
    "permission_denied": (
        "permissions", "Lokale toegangsrechten blokkeren de controle.",
        ["Controleer procesgebruiker en doelprofiel zonder accountgegevens te publiceren.",
         "Onderscheid sandboxtoegang, maprechten en netwerkbeleid; een timeout bewijst geen rechtenblokkade."],
        "Vraag alleen voor de aantoonbaar geblokkeerde stap toestemming via het beschikbare Codex-mechanisme.",
        "Benodigde toestemming is verleend en de juiste gebruikerscontext is bevestigd."),
    "powershell_blocked": (
        "launch", "Geen geschikte toegestane PowerShell-start is gevonden.",
        ["Controleer de aanwezige PowerShell-hosts en hun effectieve scriptbeleid.",
         "Controleer organisatiebeleid en ondertekening apart van sandboxrechten."],
        "Gebruik een reeds toegestane host met -File. Is beleid de blokkade, vraag een goedgekeurde route aan de beheerder.",
        "Een toegestane host of door de beheerder goedgekeurde installatie is beschikbaar; beveiliging blijft intact."),
    "setup_launch_failed": (
        "launch", "De lokale setup gaf geen bruikbaar resultaat terug.",
        ["Verifieer pakket, runtime en launcherpad.", "Controleer toegestane gebruikerscontext en zichtbaarheid van het venster."],
        "Herstel uitsluitend een bewezen pakket- of startprobleem; behoud bestaande instellingen.",
        "De concrete startfout is hersteld en er loopt geen eerdere setup meer."),
    "local_storage_failed": (
        "local_storage", "De verbinding werkt, maar lokale opslag is niet afgerond.",
        ["Controleer of setup en plugin onder hetzelfde bedoelde klantaccount werken.",
         "Controleer alleen metadata en toegang tot de lokale credential-opslag en configuratiemap."],
        "Herstel via een toegestane route de juiste gebruikerscontext of gerichte toegang. Exporteer of verplaats geen credentials.",
        "De opslagblokkade is opgelost; de klant voert het wachtwoord zelf opnieuw in indien nodig."),
    "authentication_failed": (
        "authentication", "De bereikte mailserver weigert de login.",
        ["Bevestig server en gebruikersnaamformaat via officiele providerdocumentatie.",
         "Controleer vereisten voor IMAP, app-wachtwoorden en OAuth; lees geen wachtwoord uit."],
        "Vraag maximaal eenmaal om persoonlijke herinvoer in de gemaskeerde setup met bevestigde providerinstellingen.",
        "Providerinstellingen zijn bevestigd en de klant kiest zelf om opnieuw in te loggen."),
    "password_login_disabled": (
        "authentication", "Deze server staat deze wachtwoordlogin niet toe.",
        ["Controleer de officiele ondersteunde inlogmethode."],
        "Stop wachtwoordpogingen. Leg uit wanneer OAuth nodig is; deze setup implementeert geen OAuth.", None),
    "tls_failed": (
        "tls", "De beveiligde serververbinding is niet bevestigd.",
        ["Controleer de officiele servernaam, transportinstelling en lokale klok zonder instellingen te wijzigen."],
        "Gebruik alleen een officieel bevestigde endpoint met geldige certificaatcontrole; stop als die controle blijft falen.",
        "Een concrete endpointfout is gecorrigeerd; TLS- en hostnaamcontrole blijven verplicht."),
    "dns_failed": (
        "discovery", "De gevonden servernaam kan niet worden opgezocht.",
        ["Controleer DNS en alleen het gerapporteerde domein in officiele providerdocumentatie."],
        "Gebruik complete niet-geheime providerinstellingen voor een gerichte controle.",
        "DNS werkt of de officiele serverinstellingen zijn bevestigd."),
    "network_failed": (
        "connection", "De mailserver is niet bereikbaar.",
        ["Controleer DNS en bereikbaarheid van uitsluitend de bedoelde mailendpoint zonder login.",
         "Controleer beschikbare netwerktoestemming; neem niet aan dat het wachtwoord fout is."],
        "Herstel een aantoonbare netwerk- of endpointfout; vraag gerichte toestemming alleen wanneer die nodig is.",
        "Bereikbaarheid of toestemming is aantoonbaar veranderd."),
    "autodiscovery_failed": (
        "discovery", "Automatische providerinstellingen konden niet worden bevestigd.",
        ["Zoek met alleen het domein in officiele providerdocumentatie, niet met het volledige e-mailadres."],
        "Heropen configure.py met complete IMAP-hints en zo nodig SMTP-hints; de klant vult zelf de twee velden in.",
        "Officiele instellingen zijn bevestigd; geen herhaling van dezelfde ongewijzigde zoekpoging."),
    "setup_timeout": (
        "setup", "De wachttijd voor setup is verstreken; voltooiing is niet bevestigd.",
        ["Controleer of het bestaande setupvenster nog actief is.",
         "Controleer daarna setup_status en mail_health indien beschikbaar; afgebroken wachten bewijst geen mislukte opslag."],
        "Start geen tweede setup zolang de eerste mogelijk actief is. Rapporteer de onbekende uitkomst en hervat alleen na controle.", None),
    "setup_failed": (
        "unknown", "De setup is niet afgerond; de oorzaak is nog niet vastgesteld.",
        ["Controleer pakketintegriteit, procesresultaat en niet-geheime foutcode.",
         "Controleer gebruikerscontext en bestaande setupstatus zonder wachtwoorden op te vragen."],
        "Verzamel eerst gericht bewijs. Verander geen beveiliging en herhaal geen login op basis van een vermoeden.", None),
}


def _host(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 253:
        return None
    try:
        return _validated_hostname(value, "setup endpoint")
    except ValueError:
        return None


def recovery_report(raw: Any) -> dict[str, Any]:
    """Only allow known codes and endpoint metadata; discard raw messages/commands."""
    value = raw if isinstance(raw, dict) else {}
    code = value.get("error_code")
    if not isinstance(code, str) or code not in _ROUTES:
        code = "setup_failed"
    stage, message, checks, action, condition = _ROUTES[code]
    report: dict[str, Any] = {
        "schema_version": 1, "status": "error", "error_code": code,
        "stage": stage, "message": message,
        "recovery": {
            "checks": list(checks), "next_action": action,
            "max_recovery_attempts": 1 if condition else 0,
            "retry_only_when": condition,
            "automatic_login_retry": False,
            "guide": "docs/SETUP_RECOVERY.md",
        },
    }
    domain = _host(value.get("domain"))
    if domain:
        report["domain"] = domain
    diagnostics = []
    items = value.get("diagnostics")
    for item in items[:8] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        host = _host(item.get("host"))
        port = item.get("port")
        security = item.get("security")
        item_code = item.get("error_code")
        if (host and type(port) is int and 1 <= port <= 65535
                and security in ("implicit_tls", "starttls")
                and isinstance(item_code, str) and item_code in _ROUTES):
            diagnostics.append({"host": host, "port": port, "security": security, "error_code": item_code})
    report["diagnostics"] = diagnostics
    return report
