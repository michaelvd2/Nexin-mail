# Nexin Mail — installatiekandidaat 0.2.0

Overzicht, antwoorden en opvolging in je bestaande mailbox.

Deze bronversie is een lokale ontwikkelkandidaat. Er is nog geen ondertekende,
op een schone Windows-machine geteste klantdownload. Gebruik de broncheckout of
het eerdere testartefact niet als installer. Een volledige platformbuild bevat
de eigen Python-runtime en het vooraf gebouwde dashboard; de klant installeert
geen Python, pip of Node.

## Installeren vanuit Codex

1. Verifieer de herkomst en de SHA256 van de volledige download tegenover de
   vertrouwde release. Het interne bestandenmanifest bewijst op zichzelf geen
   uitgeversidentiteit. Respecteer Windows- en organisatiebeleid.
2. Pak uit in een eigen tijdelijke map. Start `install.cmd`. Het pakket gebruikt
   uitsluitend de meegeleverde Python. Gebruik zo nodig `--codex` met het exacte
   pad naar de bedoelde native `codex.exe`; geen WSL- of shellshim gokken.
3. Het pakket controleert integriteit, runtime-imports en Codex-registratie.
   De immutable payload blijft intact; absolute MCP-paden worden in een aparte
   lokale registratie gegenereerd. Eén plugin en één lazy server (`python -m
   nexin_mail.server`) bevatten teksttools en dashboard.
4. De installer start standaard de persoonlijke gemaskeerde setup en geeft een
   `setup_session` terug. Gebruik het exacte `wait_command` met de aangegeven
   `pythonpath`, of `wait_setup` wanneer de plugin al geladen is. Wacht stil in
   blokken van maximaal 50 seconden op dezelfde sessie; vraag nooit om "klaar",
   open geen tweede formulier en rond de taak niet af zolang invoer nog loopt.
   Een onderbroken host-aanroep wordt hervat via dezelfde sessie. Annuleren stopt.
   `--skip-setup` is alleen voor een expliciet verzochte registratie zonder setup.
5. Na invullen controleert de sessie de read-only verbinding. Bij `ready` open je
   het dashboard eenmaal. Een fout levert een specifieke herstelroute op;
   herhaal geen ongewijzigde loginpoging. Alleen pluginontdekking voor het tonen
   van het dashboard kan nog een nieuwe Codex-taak vereisen.
6. Sluiten van het dashboard laat tekstbediening beschikbaar. Opnieuw openen
   gebeurt op verzoek. De huidige instructie opent eenmaal per mailsessie;
   automatische detectie van de sluitactie moet nog in de host worden getest.

Een pakket kan goed geïnstalleerd zijn terwijl aanmelden of SMTP nog aandacht
vraagt. Niet opnieuw installeren om een authenticatiefout te verhelpen. Nooit
wachtwoorden in chat, mail wijzigen als test, beleidsinstellingen wijzigen of
downloadmarkeringen wissen om installatie mogelijk te maken.

## Bereik en grenzen van deze kandidaat

- macOS arm64: er is een echt self-contained lokaal buildartefact gemaakt met
  CPython 3.12.14 en hash-locked dependencies. De exacte archive identity,
  upstream receipt, runtime- en manifesthash staan in de lokale receipt
  `runtime-provenance.json` onder
  `${HOME}/.codex/artifacts/nexin-mail/20260909-macos-arm64-3.12.14-20260901-secure-reviewed/`.
  Het is alleen op deze macOS arm64 buildhost uitgevoerd; Intel macOS,
  Codex-hostregistratie, Keychain en klantacceptatie zijn niet bewezen.
- Windows x64: bron en gesimuleerde installatietests; echte Windows-acceptatie
  ontbreekt nog. Het oude 3.12.10-embeddable recept is vervallen. De actuele
  route gebruikt de gepinde CPython 3.12.14 x86_64 standalone asset van
  python-build-standalone, maar vereist een Windows-buildhost en native
  runtime-/installerproef. ARM/WSL/32-bit worden niet als bewezen ondersteund
  voorgesteld.
- Codex-app zonder vindbare native CLI: gerichte melding, geen blinde installatie
  van systeemonderdelen. App-only installatie vereist nog hostonderzoek.
- Eerste installatie, herhaling en update-in-place zijn geïmplementeerd. Elke
  release blijft als `packages/<manifest-hash>` bewaard. Een registry-switch
  wordt gejournaliseerd; een onderbroken switch wordt bij de volgende lokale
  controle hersteld en een vorige hash kan worden teruggezet met
  `rollback.cmd`. Een onbekende Nexin Mail-registratie blijft een conflict.
- De oude `imap-plugin-handoff`-marketplace wordt nooit stilzwijgend vervangen.
  Migratie vereist de expliciete vlag `--migrate-legacy --confirm-migration`,
  controleert eerst de exacte legacy-identiteit en verwijdert die registratie
  pas nadat Nexin Mail succesvol is geregistreerd. Configuratie en credentials
  blijven op hun bestaande OS-doelen staan.
- De bestaande macOS-connectorroute blijft in de bron behouden. De nieuwe
  gezamenlijke macOS-package-build is lokaal bewezen; native Codex-installatie,
  OS-policy en Keychain blijven aparte gates.
- IMAP-wachtwoord/app-wachtwoord blijft beschikbaar voor gewone providers.
  Microsoft 365 en Outlook.com gebruiken de native browseraanmelding met PKCE
  en XOAUTH2; de OAuth-flow vereist een internetverbinding met Microsoft en
  kan door tenant-consentbeleid worden geblokkeerd.
- Tekst en dashboard delen één serverproces en credentialopslag. Bundelen en
  bron-tests zijn geen bewijs van live host-, provider- of dashboardacceptatie.
- Lokale mailverbinding betekent niet dat Codex de gevraagde AI-analyse lokaal
  uitvoert. Informatie voor AI-hulp kan naar de modelaanbieder gaan.

## Herstelrapporten en GitHub

De installer bewaart lokaal een technisch JSON-rapport in de Nexin Mail-map.
Alleen vaste stapnamen, foutcodes, herstelacties, uitkomsten en pakketversie zijn
toegestaan. Geen ruwe logs, vrije modeltekst, klantadres, pad, mail of geheim.
Een poging en een geslaagde controle zijn verschillende uitkomsten. Mailbox en
dashboard blijven `not_checked` totdat ze afzonderlijk zijn gecontroleerd.

Er bestaat geen uploadfunctie. Voor latere optionele rapportage: klantkeuze
bij setup, zichtbare preview, intrekbaarheid, servervalidatie van dezelfde vaste
velden, begrensde authenticatie en limieten. Een installatie-ID dient alleen
voor correlatie, niet als authenticatie. Alleen de ontvangstdienst krijgt
rechten op de gekozen private GitHub-repository. Geen algemene GitHub-token
op klantmachines, geen automatische toepassing van issue-tekst of codepatches.

## Bouwen en controleren

Op een Windows-bouwmachine: gebruik `scripts/build_runtime.ps1`. Die route
downloadt alleen de gepinde x86_64 CPython 3.12.14 standalone asset van de
onderhouden upstream release, controleert de SHA256 en vereist `tar.exe`; de
build en native verificatie zijn in deze checkout niet uitgevoerd. Bouw daarna
het dashboard met de lockfile, voer de tests uit en gebruik:

```text
python -m nexin_mail.build --platform windows --source . --runtime runtime/python --output dist/nexin-mail-windows-0.2.0
```

De Windows-builder test de werkelijke private runtime en weigert bestaande
uitvoer te overschrijven. De package-builder controleert ook de versies uit
`sources.json` en schrijft een deterministische ZIP.

Op macOS arm64 bouw je het echte lokale package met:

```text
ARTIFACT_ROOT="${HOME}/.codex/artifacts/nexin-mail/20260909-macos-arm64-3.12.14-20260901-secure-reviewed"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 scripts/build_macos_package.py \
  --source . \
  --artifact-root "$ARTIFACT_ROOT"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  "$ARTIFACT_ROOT/nexin-mail-0.2.0-macos-arm64/payload/runtime/python/bin/python3.12" \
  -B scripts/verify_macos_package.py \
  "$ARTIFACT_ROOT/nexin-mail-0.2.zip" \
  --extract-root "$ARTIFACT_ROOT/relocation-harness"
```

De macOS-builder downloadt `cpython-3.12.14+20260901-aarch64-apple-darwin-install_only.tar.gz`
van de gepinde onderhouden upstream release, controleert de release-SHA256,
materialiseert uitsluitend de bekende interne symlinks en installeert de
lockfile met `--require-hashes`. Het package gebruikt de meegeleverde runtime
en vereist geen Homebrew of ontwikkel-venv. De pakketcontrole zoekt naar
persoonlijke bouwpaden en verwijderde pip-launchers. Externe wheels kunnen
generieke upstream-bouwpaden in binaire metadata en SBOMs bevatten; die zijn
afzonderlijk beoordeeld en de gecontroleerde library laadt geen Homebrew-dylib.
Een SHA256-manifest bewijst integriteit, geen uitgeversidentiteit. Authenticode- of macOS-ondertekening heeft een
afzonderlijke, bewust niet-geconfigureerde hook; er wordt zonder aangeleverde
signing-identiteit niets ondertekend of geüpload.
Ondertekening en echte tests met Codex, beperkte gebruikersrechten, Defender,
niet-ASCII-paden en netwerkbeleid blijven aparte releasevoorwaarden. De
volledige premortem en Codex-correcties staan bij het werkverslag van deze
kandidaat.
