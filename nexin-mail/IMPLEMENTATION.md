# Nexin Mail — vastgesteld implementatieplan

## Product en veiligheidscontract
Een gedeelde, lazy gestarte mailruntime en een MCP-server met teksttools en dashboard. Een nog niet gekoppelde mailbox mag de server of setup niet onbereikbaar maken. Mailboxidentiteiten, voorstellen en actuele staat zijn gedeeld. Alle consequentiele acties krijgen native review; een UI-sessie of door het model gehouden waarde geldt nooit als menselijke toestemming.

Microsoft365 en Outlook.com krijgen public-client browseraanmelding via de officiele MSAL-bibliotheek, met passende gedelegeerde scopes en XOAUTH2 voor IMAP/SMTP. Wachtwoord/app-wachtwoord voor gewone IMAP blijft behouden. Geen app-secret op een klantmachine. Geheimen en token/cachemateriaal uitsluitend in de OS-keystore en noodzakelijk werkgeheugen; geen bestandscache, logs, chat of rapportage. Config bevat alleen niet-geheime koppelinformatie. Gedeeltelijke keystore-writes mogen een gezonde bestaande generatie niet verliezen. Geen automatische herhaling van een mogelijk uitgevoerde mailactie.

Een immutable pakket, afgeleide absolute registratie, veilige update/rollback en bewuste legacy-migratie. Native Windows en macOS, met expliciete diagnose voor ongeteste host-/architectuurvarianten. Geen veiligheidsbeleid omzeilen, geen klanten-Python/pip/Node. Herkomst en ondertekening zijn afzonderlijk van hashintegriteit. Ondertekening en live providerregistratie worden voorbereid maar zonder sleutel/account of kostenautoriteit niet als uitgevoerd aangemerkt.

Lokale technisch begrensde herstelrapporten blijven de basis; geen GitHub-uploadfunctie of algemene GitHub-rechten bij klanten. Een eventuele opt-in ontvangstdienst is een afzonderlijk ontwerp met servervalidatie, nauw begrensde toegang, intrekbaarheid en geen automatische patches.

## Uitvoering en eigendom
- Mailserver/dashboard-eigenaar: gedeelde server, native actiepoort, frontend, protocoltests en beveiligingsdocumentatie.
- Authenticatie-eigenaar: OAuth/config/credentialopslag, IMAP/SMTP-authenticatie, native enrollment, dependencylocks en authenticatietests.
- Installatie-eigenaar: pakket/registratie/update/migratie/macOS-bundel, build/CI, native bewijsharnas en klantinstallatiedocumentatie.
Alle drie werken aan expliciet disjuncte bestanden in dezelfde bestaande checkout. Zij bewaren de bestaande wijzigingen en maken geen subagents. Een eigenaar voert daarna de gecombineerde integratie en validatie uit zodra alle inputs stabiel zijn.

## Oplevering
281 unieke tests; protocolbewijs voor de ene server en exacte native review; OAuth en onderbroken keystore-opslag; staged update/rollback en rollback bij registratieproblemen; UI-build en consistent gebundelde assets; privacy-/structuur-/schema- en hash-locked dependencychecks. Een echt macOS arm64 package met private CPython 3.12.14 en twee relocatieproeven is lokaal uitgevoerd. Geen bekende onopgeloste beveiligingsbevinding bij release en geen claim van nul risico.

Echte Windowsinstallatie, Windows Credential Manager, macOS Codex/Keychain, OS-beleid, native Codex-dashboard, providerlogin, signing en platform-/providerclaims vereisen afzonderlijke uitvoering. Geen publicatie, productie-installatie, aankoop of echte mailboxactie is via dit plan automatisch geautoriseerd. Afwezige externe middelen blokkeren code en synthetische tests niet, maar blokkeren wel overeenkomstige live of klantklaar-claims.

## Geintegreerde validatie 2026-09-09

De eerdere bronvalidatie omvatte 281 unieke tests: 253 backendtests, 14 dashboard-Python-tests en 14 frontendtests. Backend en dependencies zijn toen in een verse Python 3.12.13-omgeving met `--require-hashes` gecontroleerd. Dit is bestaand bronbewijs; de suite is bij de hervatte pakketbouw niet opnieuw uitgevoerd.

Het oorspronkelijke echte macOS-arm64-pakket onder `...-final/`, SHA-256 `b181c9df2fac52cc94de45d991dc34315601a57110f2ff72a84b73dd16704108`, is AFGEKEURD wegens pip-launchers met persoonlijke bouwpaden en mag niet als distributie worden aangeboden. Het eerdere synthetische Windows-pakket bevat alleen een fixture-runtime en is evenmin een distributie.

De gecorrigeerde macOS-bouw onder `...-secure/` gebruikt CPython 3.12.14 arm64, release `20260901`, upstream SHA-256 `3ee3ee547cedfeb7c2b16b2b7156039f7b470bb8f857e226fd3d2eb11db83c76`, met hash-locked `mcp==2.1.1` en `msal==1.38.0`. ZIP SHA-256 `030d1ce893abbeeaf1e346d5b923840c560446c0807767cbddae2bf6a1fcba86`; manifest SHA-256 `0da03e0b965bd60b457c1f9d8caf55c668b98558de767d65aebc467779072955`. Twee relocaties, eigen runtime, een lazy server met 56 unieke tools, unconfigured onboarding, stdio-registratievorm, manifestintegriteit en pakketprivacy zijn geslaagd. Geen persoonlijke bouwpaden of pip-launchers blijven in het pakket. Generieke externe wheel-/SBOM-bouwmetadata is afzonderlijk beoordeeld; de gecontroleerde cryptography-library heeft geen Homebrew-dylibafhankelijkheid.

De meegeleverde INSTALLATIE.md is aangescherpt en byte-identiek aan de gecontroleerde bron. De toenmalige lokaal gevalideerde kandidaat is `${HOME}/.codex/artifacts/nexin-mail/20260909-macos-arm64-3.12.14-20260901-secure-reviewed/nexin-mail-0.2.zip`, 48542522 bytes, SHA-256 `5a7006d10867d70c3758476d6b6c34046e63f9a676d54048a0e6960b1b02b758`. Het manifest telt 2456 bestanden, SHA-256 `7567d7310aa264057374d7c1a2b23b175c2501ad676ad61fa4401afb373d1dca`. `runtime-provenance.json` en `checks/release-gates.json` naast de ZIP binden de bouwherkomst, privacy-/padcontrole, manifestcontrole, twee relocaties en stdio/server/onboarding aan dit exacte artefact. Beide eerdere artefacten zijn met onveranderde hashes behouden. De bronprivacycontrole, structuurcontrole en `git diff --check` zijn eveneens geslaagd.

De eerdere synthetische package-lifecycleproef heeft install/update/rollback/uninstall, manifesttampering, foreign-registrybescherming en bevestigde exact-owner legacy-migratie met behoud van synthetische config/keystore doorlopen. Signing/publisher-authenticiteit, Microsoft public client ID/tenant-consent, echte Windows-Codex/Credential Manager/beleidstest, providerlogin, macOS Codex/Keychain-acceptatie en handmatige UI-acceptatie blijven afzonderlijke open bewijsgrenzen. Geen signing, upload, live installatie, echte credentials of mailbox is gebruikt. De kandidaat is niet gereed voor klantdistributie.

## Repository en lokale Codex-installatie 2026-09-10

De productingang in deze repository omvat nu de backend, het dashboard, de skill,
installers en tests. Het dashboard is een gebundeld component. Bronontwikkeling
gebruikt Python 3.12; de platformbundel levert een eigen runtime en afgeleide
registratie voor de lokale host.

De echte macOS-installatie bracht drie installerfouten aan het licht: onschuldige
Finder-metadata werd afgewezen, de Codex-marketplacebron had een niet-ondersteunde
objectvorm en kopieren verloor uitvoerrechten. De correcties behouden de controles
op links, gewijzigde bestanden en onbekende registraties. Gerichte regressietests,
twee pakketrelocaties en de protocol-/onboardingcontroles zijn geslaagd.

De voor de eerste registratie gebruikte bundel is `20260910-host-test/r2/nexin-mail-0.2.zip`
onder de lokale artefactmap, 48541564 bytes, SHA-256
`115f906f225b4040de9779904cfe942cbb79026b9226a5ba2cd7adea8ddad9bb`.
Het manifest bevat 2456 bestanden met SHA-256
`eaa645c92283354d9ef3a1a14a8a7b90505111ae2d16cb17aca63922ddd262d1`.
Installatie via de native Codex CLI 0.153.4 slaagde; onafhankelijke readback toont
`nexin-mail@nexin-mail` versie 0.2.0 als geinstalleerd en ingeschakeld, met de
uitvoerbare private runtime uit deze manifestversie.

Een afzonderlijke stdio-proef startte daarna exact die geregistreerde runtime:
server `nexin-mail`, 56 unieke tools, dashboardresource
`ui://imap-dashboard/operator-v2.html` met MCP-app MIME-type en 633408 bytes HTML,
en de onboarding zonder account slaagden. Dit is geinstalleerd protocolbewijs;
de zichtbare hostweergave is hiermee niet bewezen.

Installatie en registratie zijn nu op deze Mac bewezen. De bestaande Codex-taak
heeft de nieuwe plugintools nog niet geladen; zichtbare dashboardacceptatie,
echte accountsetup, providerlogin en mailboxacties zijn nog niet bewezen. De
Windows-, signing- en klantacceptatiegrenzen blijven open. Lokale pakketten,
diagnostiek en accountgegevens maken geen deel uit van de bronrepository.

## Actuele lokale testversie en platformcorrecties

De volledige lokale backendset telt nu 257 geslaagde tests. Windows gebruikt een
afzonderlijk gemarkeerde, hash-locked pywin32-pin. De native review weigert te
grote verzoeken voor iedere processtart; dit is voor Windows en macOS getest.
Testfixtures lezen UTF-8-registratie expliciet en vergelijken de bestandsmodus
die het betreffende platform ondersteunt.

De actuele macOS-testbundel is `20260910-host-test/r3/nexin-mail-0.2.zip`,
48541473 bytes, SHA-256
`0016e4b99c1e3c0e543f6dad9570a2ede780e50a27a47cec2c0a44cc8fe4929e`.
Het manifest bevat 2456 bestanden met SHA-256
`56a316422aeecde687e57a5b3a8de9edb85559b27c1600e4d6855d4db9f604f5`.
Twee relocaties, de eigen runtime en onboarding zijn gecontroleerd. De lokale
update en onafhankelijke plugin-readback slagen. De geregistreerde runtime
gebruikt deze manifestversie en de native-reviewbron is byte-identiek aan de
gepubliceerde correctie. De geinstalleerde protocolproef levert opnieuw 56 tools
en de dashboardresource; echte mailbox- en zichtbare UI-acceptatie blijven open.

GitHub heeft de platformtests op zowel Windows als macOS uitgevoerd. De echte
Windows-runtime en het complete pakket zijn ook gebouwd en geimporteerd. De
CI bouwt buiten de bronmap en gebruikt voor releasecontrole het archiefpad uit
het bouwresultaat. Een geslaagde runnerbouw bewijst geen interactieve
klantinstallatie, providerlogin, signing of zichtbare dashboardacceptatie.
