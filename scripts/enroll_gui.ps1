$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$script:setupReport = $null
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$dpiSource = @'
using System;
using System.Runtime.InteropServices;

public static class ImapPluginDpi {
    [DllImport("user32.dll", SetLastError=true)]
    private static extern bool SetProcessDpiAwarenessContext(IntPtr value);

    [DllImport("shcore.dll", SetLastError=true)]
    private static extern int SetProcessDpiAwareness(int value);

    [DllImport("user32.dll", SetLastError=true)]
    private static extern bool SetProcessDPIAware();

    public static void EnablePerMonitor() {
        try {
            if (SetProcessDpiAwarenessContext(new IntPtr(-4))) return;
        } catch (EntryPointNotFoundException) { }
        try {
            if (SetProcessDpiAwareness(2) == 0) return;
        } catch (DllNotFoundException) { }
        try { SetProcessDPIAware(); } catch (EntryPointNotFoundException) { }
    }
}
'@
Add-Type -TypeDefinition $dpiSource -Language CSharp
[ImapPluginDpi]::EnablePerMonitor()
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)

$source = @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class ImapPluginCredential {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct CREDENTIAL {
        public UInt32 Flags;
        public UInt32 Type;
        public string TargetName;
        public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public UInt32 CredentialBlobSize;
        public IntPtr CredentialBlob;
        public UInt32 Persist;
        public UInt32 AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    [DllImport("Advapi32.dll", EntryPoint="CredWriteW", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern bool CredWrite(ref CREDENTIAL credential, UInt32 flags);

    [DllImport("Advapi32.dll", EntryPoint="CredReadW", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern bool CredRead(string target, UInt32 type, UInt32 flags, out IntPtr credential);

    [DllImport("Advapi32.dll", SetLastError=true)]
    private static extern void CredFree(IntPtr credential);

    public static void WriteLocalMachine(string target, string secret) {
        if (String.IsNullOrEmpty(secret)) throw new ArgumentException("Empty secret rejected");
        if ((ulong)secret.Length * 2UL > 5120UL) throw new ArgumentException("Secret exceeds Credential Manager limit");
        IntPtr blob = Marshal.StringToCoTaskMemUni(secret);
        try {
            CREDENTIAL credential = new CREDENTIAL();
            credential.Type = 1;
            credential.TargetName = target;
            credential.CredentialBlobSize = (UInt32)(secret.Length * 2);
            credential.CredentialBlob = blob;
            credential.Persist = 2;
            credential.UserName = null;
            if (!CredWrite(ref credential, 0)) throw new Win32Exception(Marshal.GetLastWin32Error());
        } finally {
            Marshal.ZeroFreeCoTaskMemUnicode(blob);
        }
    }

    public static string Metadata(string target) {
        IntPtr pointer;
        if (!CredRead(target, 1, 0, out pointer)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            CREDENTIAL credential = (CREDENTIAL)Marshal.PtrToStructure(pointer, typeof(CREDENTIAL));
            if (credential.Persist != 2) throw new InvalidOperationException("Credential persistence is not local-machine");
            return "Type=" + credential.Type + " Persist=" + credential.Persist + " BlobSize=" + credential.CredentialBlobSize;
        } finally {
            CredFree(pointer);
        }
    }
}
'@
Add-Type -TypeDefinition $source -Language CSharp

function Escape-TomlString([string]$Value) {
    if ($Value.IndexOfAny([char[]]"`r`n`0") -ge 0) { throw 'Configuration values must be single-line.' }
    return $Value.Replace('\', '\\').Replace('"', '\"')
}

function Write-Config([object]$Result) {
    $stateDirectory = Join-Path $env:LOCALAPPDATA 'imap-plugin'
    [IO.Directory]::CreateDirectory($stateDirectory) | Out-Null
    $configPath = Join-Path $stateDirectory 'config.toml'
    $configurationLines = @(
        'account_id = "default"'
        'username = "' + (Escape-TomlString ([string]$Result.username)) + '"'
        'email_address = "' + (Escape-TomlString ([string]$Result.email_address)) + '"'
        'host = "' + (Escape-TomlString ([string]$Result.host)) + '"'
        'port = ' + [int]$Result.port
        'imap_security = "' + (Escape-TomlString ([string]$Result.imap_security)) + '"'
        'credential_target = "imap-plugin/imap"'
        'smtp_credential_target = "imap-plugin/smtp"'
        'trusted_authserv_ids = []'
        'operator_enabled = ' + $(if ([bool]$Result.operator_enabled) { 'true' } else { 'false' })
        'timeout_seconds = 15.0'
        'max_results = 20'
        'max_scan = 250'
        'max_days = 31'
        'max_message_bytes = 262144'
        'trace_max_bytes = 262144'
        'trace_files = 3'
    )
    if ([bool]$Result.smtp_configured) {
        $configurationLines += @(
            'smtp_host = "' + (Escape-TomlString ([string]$Result.smtp_host)) + '"'
            'smtp_port = ' + [int]$Result.smtp_port
            'smtp_security = "' + (Escape-TomlString ([string]$Result.smtp_security)) + '"'
            'smtp_username = "' + (Escape-TomlString ([string]$Result.smtp_username)) + '"'
        )
    }
    $temporary = Join-Path $stateDirectory ("config." + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temporary, (($configurationLines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $temporary -Destination $configPath -Force
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $configPath '/inheritance:r' '/grant:r' "${identity}:(F)" '/grant:r' 'SYSTEM:(F)' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not protect the local configuration file.' }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Invoke-AutoConfigure([string]$EmailAddress, [string]$Password) {
    $pluginRoot = Split-Path -Parent $PSScriptRoot
    $python = Join-Path $pluginRoot 'runtime\python\python.exe'
    $helper = Join-Path $pluginRoot 'scripts\autoconfigure.py'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $helper -PathType Leaf)) {
        throw 'The verified local setup components are incomplete.'
    }
    $hints = $null
    if (-not [string]::IsNullOrWhiteSpace($env:IMAP_PLUGIN_DISCOVERY_HINTS)) {
        try { $hints = $env:IMAP_PLUGIN_DISCOVERY_HINTS | ConvertFrom-Json } catch { throw 'Codex supplied invalid provider hints.' }
    }
    $request = [ordered]@{ email_address = $EmailAddress; password = $Password; hints = $hints } | ConvertTo-Json -Compress -Depth 5
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $python
    $start.Arguments = '-X utf8 "' + $helper.Replace('"', '\"') + '"'
    $start.WorkingDirectory = $pluginRoot
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables['PYTHONPATH'] = Join-Path $pluginRoot 'src'
    $start.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw 'Automatic setup could not start.' }
        $process.StandardInput.Write($request)
        $process.StandardInput.Close()
        $request = $null
        $output = $process.StandardOutput.ReadToEnd()
        [void]$process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ([string]::IsNullOrWhiteSpace($output)) { throw 'Automatic setup returned no result.' }
        try { $result = $output | ConvertFrom-Json } catch { throw 'Automatic setup returned an invalid result.' }
        if ($process.ExitCode -ne 0 -or $result.status -ne 'configured') {
            $script:setupReport = $result
            throw 'De mailcontrole is niet gelukt.'
        }
        return $result
    } finally {
        $request = $null
        $process.Dispose()
    }
}

function Invoke-OAuthConfigure([string]$EmailAddress, [bool]$IncludeSmtp) {
    $pluginRoot = Split-Path -Parent $PSScriptRoot
    $python = Join-Path $pluginRoot 'runtime\python\python.exe'
    $helper = Join-Path $pluginRoot 'scripts\oauth_enroll.py'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $helper -PathType Leaf)) {
        throw 'The verified local setup components are incomplete.'
    }
    # This request contains no password or token. The helper opens MSAL's
    # official browser flow and keeps its cache inside Credential Manager.
    $request = [ordered]@{ email_address = $EmailAddress; include_smtp = $IncludeSmtp } | ConvertTo-Json -Compress
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $python
    $start.Arguments = '-X utf8 "' + $helper.Replace('"', '\"') + '"'
    $start.WorkingDirectory = $pluginRoot
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables['PYTHONPATH'] = Join-Path $pluginRoot 'src'
    $start.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw 'Microsoft setup could not start.' }
        $process.StandardInput.Write($request)
        $process.StandardInput.Close()
        $request = $null
        $output = $process.StandardOutput.ReadToEnd()
        [void]$process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ([string]::IsNullOrWhiteSpace($output)) { throw 'Microsoft setup returned no result.' }
        try { $result = $output | ConvertFrom-Json } catch { throw 'Microsoft setup returned an invalid result.' }
        if ($process.ExitCode -ne 0 -or $result.status -ne 'configured') {
            $code = [string]$result.error_code
            $allowedCodes = @(
                'oauth_unconfigured', 'oauth_consent_required', 'oauth_reauth_required',
                'oauth_browser_unavailable', 'oauth_cancelled', 'oauth_identity_invalid',
                'oauth_cache_corrupt', 'oauth_provider_failed', 'smtp_auth_disabled',
                'setup_failed'
            )
            if ($result.status -eq 'cancelled') {
                $script:setupReport = [ordered]@{
                    status = 'cancelled'
                    message = 'Microsoft sign-in was cancelled. There is no automatic retry.'
                }
            } else {
                if ($code -notin $allowedCodes) { $code = 'setup_failed' }
                $script:setupReport = [ordered]@{
                    status = 'error'
                    error_code = $code
                    message = 'Microsoft sign-in did not complete safely.'
                }
            }
            throw 'Microsoft sign-in did not complete.'
        }
        # Keep the native process as the only secret boundary.  Whitelist the
        # tiny public setup report before it can be emitted by this script.
        $safe = [ordered]@{ status = 'configured' }
        foreach ($field in @('mailbox_actions_ready', 'send_ready', 'smtp_enabled')) {
            $property = $result.PSObject.Properties[$field]
            if ($null -ne $property -and $property.Value -is [bool]) {
                $safe[$field] = [bool]$property.Value
            }
        }
        if ($result.auth_method -in @('password', 'microsoft')) {
            $safe['auth_method'] = [string]$result.auth_method
        }
        if ($result.account_type -in @('microsoft365', 'outlook.com')) {
            $safe['account_type'] = [string]$result.account_type
        }
        return $safe
    } finally {
        $request = $null
        $process.Dispose()
    }
}

$background = [Drawing.Color]::FromArgb(247, 249, 252)
$surface = [Drawing.Color]::White
$textColor = [Drawing.Color]::FromArgb(25, 39, 58)
$mutedColor = [Drawing.Color]::FromArgb(91, 105, 122)
$borderColor = [Drawing.Color]::FromArgb(214, 222, 233)
$accentColor = [Drawing.Color]::FromArgb(38, 105, 232)
$accentHoverColor = [Drawing.Color]::FromArgb(27, 85, 196)
$statusBackground = [Drawing.Color]::FromArgb(238, 245, 255)

$form = New-Object Windows.Forms.Form
$form.SuspendLayout()
$form.Text = 'IMAP Plugin'
$form.ClientSize = New-Object Drawing.Size(720, 560)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.AutoScaleDimensions = New-Object Drawing.SizeF(96, 96)
$form.AutoScaleMode = [Windows.Forms.AutoScaleMode]::Dpi
$form.BackColor = $background
$form.Font = New-Object Drawing.Font('Segoe UI', 10)

$header = New-Object Windows.Forms.Panel
$header.Location = New-Object Drawing.Point(0, 0)
$header.Size = New-Object Drawing.Size(720, 128)
$header.BackColor = [Drawing.Color]::FromArgb(242, 246, 252)
$form.Controls.Add($header)

$accentBar = New-Object Windows.Forms.Panel
$accentBar.Location = New-Object Drawing.Point(0, 0)
$accentBar.Size = New-Object Drawing.Size(6, 128)
$accentBar.BackColor = $accentColor
$header.Controls.Add($accentBar)

$eyebrow = New-Object Windows.Forms.Label
$eyebrow.Location = New-Object Drawing.Point(32, 18)
$eyebrow.Size = New-Object Drawing.Size(620, 20)
$eyebrow.Text = 'IMAP PLUGIN'
$eyebrow.ForeColor = $accentColor
$eyebrow.Font = New-Object Drawing.Font('Segoe UI', 9, [Drawing.FontStyle]::Bold)
$header.Controls.Add($eyebrow)

$title = New-Object Windows.Forms.Label
$title.Location = New-Object Drawing.Point(32, 39)
$title.Size = New-Object Drawing.Size(640, 36)
$title.Font = New-Object Drawing.Font('Segoe UI', 21, [Drawing.FontStyle]::Bold)
$title.ForeColor = $textColor
$title.Text = 'Verbind je e-mail'
$header.Controls.Add($title)

$intro = New-Object Windows.Forms.Label
$intro.Location = New-Object Drawing.Point(34, 82)
$intro.Size = New-Object Drawing.Size(650, 42)
$intro.ForeColor = $mutedColor
$intro.Text = 'Kies Microsoft browseraanmelding of je bestaande wachtwoord/app-wachtwoord. Geheimen blijven op deze computer.'
$header.Controls.Add($intro)

$card = New-Object Windows.Forms.Panel
$card.Location = New-Object Drawing.Point(32, 148)
$card.Size = New-Object Drawing.Size(656, 230)
$card.BackColor = $surface
$card.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
$form.Controls.Add($card)

$cardTitle = New-Object Windows.Forms.Label
$cardTitle.Location = New-Object Drawing.Point(24, 15)
$cardTitle.Size = New-Object Drawing.Size(600, 22)
$cardTitle.Text = 'Veilige verbinding'
$cardTitle.ForeColor = $textColor
$cardTitle.Font = New-Object Drawing.Font('Segoe UI', 10, [Drawing.FontStyle]::Bold)
$card.Controls.Add($cardTitle)

$cardHint = New-Object Windows.Forms.Label
$cardHint.Location = New-Object Drawing.Point(24, 38)
$cardHint.Size = New-Object Drawing.Size(600, 20)
$cardHint.Text = 'Microsoft opent de officiele browseraanmelding; de oude route blijft beschikbaar.'
$cardHint.ForeColor = $mutedColor
$cardHint.Font = New-Object Drawing.Font('Segoe UI', 9)
$card.Controls.Add($cardHint)

$methodLabel = New-Object Windows.Forms.Label
$methodLabel.Location = New-Object Drawing.Point(24, 76)
$methodLabel.Size = New-Object Drawing.Size(128, 24)
$methodLabel.Text = 'Aanmeldmethode'
$methodLabel.ForeColor = $textColor
$card.Controls.Add($methodLabel)

$microsoftRadio = New-Object Windows.Forms.RadioButton
$microsoftRadio.Location = New-Object Drawing.Point(160, 74)
$microsoftRadio.Size = New-Object Drawing.Size(220, 26)
$microsoftRadio.Text = 'Microsoft browser'
$microsoftRadio.ForeColor = $textColor
$microsoftRadio.TabIndex = 0
$card.Controls.Add($microsoftRadio)

$passwordRadio = New-Object Windows.Forms.RadioButton
$passwordRadio.Location = New-Object Drawing.Point(390, 74)
$passwordRadio.Size = New-Object Drawing.Size(230, 26)
$passwordRadio.Text = 'Wachtwoord/app-wachtwoord'
$passwordRadio.ForeColor = $textColor
$passwordRadio.Checked = $true
$passwordRadio.TabIndex = 1
$card.Controls.Add($passwordRadio)

$emailLabel = New-Object Windows.Forms.Label
$emailLabel.Location = New-Object Drawing.Point(24, 112)
$emailLabel.Size = New-Object Drawing.Size(128, 24)
$emailLabel.Text = 'E-mailadres'
$emailLabel.ForeColor = $textColor
$card.Controls.Add($emailLabel)

$email = New-Object Windows.Forms.TextBox
$email.Location = New-Object Drawing.Point(160, 108)
$email.Size = New-Object Drawing.Size(456, 29)
$email.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
$email.BackColor = $surface
$email.ForeColor = $textColor
$email.Font = New-Object Drawing.Font('Segoe UI', 10)
$email.TabIndex = 2
$card.Controls.Add($email)

$passwordLabel = New-Object Windows.Forms.Label
$passwordLabel.Location = New-Object Drawing.Point(24, 154)
$passwordLabel.Size = New-Object Drawing.Size(128, 24)
$passwordLabel.Text = 'Wachtwoord'
$passwordLabel.ForeColor = $textColor
$card.Controls.Add($passwordLabel)

$password = New-Object Windows.Forms.TextBox
$password.Location = New-Object Drawing.Point(160, 150)
$password.Size = New-Object Drawing.Size(320, 29)
$password.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
$password.BackColor = $surface
$password.ForeColor = $textColor
$password.Font = New-Object Drawing.Font('Segoe UI', 10)
$password.UseSystemPasswordChar = $true
$password.TabIndex = 3
$card.Controls.Add($password)

$showPassword = New-Object Windows.Forms.CheckBox
$showPassword.Location = New-Object Drawing.Point(500, 152)
$showPassword.Size = New-Object Drawing.Size(120, 24)
$showPassword.Text = 'Tonen'
$showPassword.ForeColor = $mutedColor
$showPassword.Font = New-Object Drawing.Font('Segoe UI', 9)
$showPassword.Checked = $false
$showPassword.TabIndex = 4
$showPassword.Add_CheckedChanged({ $password.UseSystemPasswordChar = -not $showPassword.Checked })
$card.Controls.Add($showPassword)

$smtpCheck = New-Object Windows.Forms.CheckBox
$smtpCheck.Location = New-Object Drawing.Point(160, 188)
$smtpCheck.Size = New-Object Drawing.Size(456, 26)
$smtpCheck.Text = 'SMTP verzenden inschakelen (extra Microsoft-toestemming)'
$smtpCheck.ForeColor = $textColor
$smtpCheck.Enabled = $false
$smtpCheck.TabIndex = 5
$card.Controls.Add($smtpCheck)

$microsoftRadio.Add_CheckedChanged({
    $isMicrosoft = $microsoftRadio.Checked
    $passwordLabel.Visible = -not $isMicrosoft
    $password.Visible = -not $isMicrosoft
    $showPassword.Visible = -not $isMicrosoft
    $smtpCheck.Enabled = $isMicrosoft
    if ($isMicrosoft) {
        $status.Text = 'Microsoft opent een lokale browser. Dit venster vraagt geen wachtwoord.'
    } else {
        $smtpCheck.Checked = $false
        $status.Text = 'Na de controle gaat Codex automatisch verder, ook als hulp nodig is.'
    }
})

$statusPanel = New-Object Windows.Forms.Panel
$statusPanel.Location = New-Object Drawing.Point(32, 400)
$statusPanel.Size = New-Object Drawing.Size(656, 64)
$statusPanel.BackColor = $statusBackground
$statusPanel.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
$form.Controls.Add($statusPanel)

$status = New-Object Windows.Forms.Label
$status.Location = New-Object Drawing.Point(16, 12)
$status.Size = New-Object Drawing.Size(624, 38)
$status.ForeColor = $accentColor
$status.Text = 'Na de controle gaat Codex automatisch verder, ook als hulp nodig is.'
$status.AutoEllipsis = $true
$statusPanel.Controls.Add($status)

$footerNote = New-Object Windows.Forms.Label
$footerNote.Location = New-Object Drawing.Point(32, 480)
$footerNote.Size = New-Object Drawing.Size(440, 24)
$footerNote.Text = 'Je wachtwoord wordt niet naar Codex gestuurd.'
$footerNote.ForeColor = $mutedColor
$footerNote.Font = New-Object Drawing.Font('Segoe UI', 9)
$form.Controls.Add($footerNote)

$connectButton = New-Object Windows.Forms.Button
$connectButton.Location = New-Object Drawing.Point(496, 504)
$connectButton.Size = New-Object Drawing.Size(112, 38)
$connectButton.Text = 'Verbinden'
$connectButton.Font = New-Object Drawing.Font('Segoe UI', 10, [Drawing.FontStyle]::Bold)
$connectButton.BackColor = $accentColor
$connectButton.ForeColor = $surface
$connectButton.FlatStyle = [Windows.Forms.FlatStyle]::Flat
$connectButton.FlatAppearance.BorderSize = 0
$connectButton.FlatAppearance.MouseOverBackColor = $accentHoverColor
$connectButton.Cursor = [Windows.Forms.Cursors]::Hand
$connectButton.TabIndex = 3
$form.Controls.Add($connectButton)
$form.AcceptButton = $connectButton

$cancelButton = New-Object Windows.Forms.Button
$cancelButton.Location = New-Object Drawing.Point(616, 504)
$cancelButton.Size = New-Object Drawing.Size(72, 38)
$cancelButton.Text = 'Sluiten'
$cancelButton.ForeColor = $textColor
$cancelButton.BackColor = $surface
$cancelButton.FlatStyle = [Windows.Forms.FlatStyle]::Flat
$cancelButton.FlatAppearance.BorderColor = $borderColor
$cancelButton.FlatAppearance.BorderSize = 1
$cancelButton.FlatAppearance.MouseOverBackColor = $background
$cancelButton.Cursor = [Windows.Forms.Cursors]::Hand
$cancelButton.DialogResult = [Windows.Forms.DialogResult]::Cancel
$cancelButton.TabIndex = 4
$form.Controls.Add($cancelButton)
$form.CancelButton = $cancelButton

$connectButton.Add_Click({
    $address = $email.Text.Trim()
    $isMicrosoft = $microsoftRadio.Checked
    if ($address -notmatch '^[^\s@]+@[^\s@]+$' -or (-not $isMicrosoft -and [string]::IsNullOrEmpty($password.Text))) {
        $status.ForeColor = [Drawing.Color]::DarkRed
        $status.Text = if ($isMicrosoft) { 'Vul een geldig e-mailadres in.' } else { 'Vul een geldig e-mailadres en je wachtwoord of app-wachtwoord in.' }
        return
    }
    $connectButton.Enabled = $false
    $status.ForeColor = [Drawing.Color]::DarkBlue
    $status.Text = if ($isMicrosoft) { 'Microsoft browseraanmelding openen...' } else { 'Veilige serverinstellingen zoeken en controleren...' }
    $form.Refresh()
    $stage = 'connection'
    try {
        if ($isMicrosoft) {
            $result = Invoke-OAuthConfigure $address $smtpCheck.Checked
            $script:setupReport = $result
        } else {
            $result = Invoke-AutoConfigure $address $password.Text
            $stage = 'local_storage'
            [ImapPluginCredential]::WriteLocalMachine('imap-plugin/imap', $password.Text)
            [void][ImapPluginCredential]::Metadata('imap-plugin/imap')
            if ([bool]$result.smtp_configured) {
                [ImapPluginCredential]::WriteLocalMachine('imap-plugin/smtp', $password.Text)
                [void][ImapPluginCredential]::Metadata('imap-plugin/smtp')
            }
            Write-Config $result
            $script:setupReport = [ordered]@{
                status = 'configured'
                mailbox_actions_ready = [bool]$result.mailbox_actions_ready
                send_ready = [bool]$result.send_ready
                smtp_diagnostics = $result.smtp_diagnostics
            }
        }
        $form.DialogResult = [Windows.Forms.DialogResult]::OK
    } catch {
        if ($null -eq $script:setupReport) {
            $script:setupReport = [ordered]@{
                status = 'error'
                error_code = if ($stage -eq 'local_storage') { 'local_storage_failed' } else { 'setup_failed' }
                message = if ($stage -eq 'local_storage') { 'De mailverbinding werkt, maar lokale opslag mislukt. Controleer de gebruikerscontext, Credential Manager en maprechten. De installatie is nog niet afgerond.' } else { 'De lokale setup kon niet afronden. Codex kan de installatiecomponenten controleren.' }
            }
        }
        $form.DialogResult = [Windows.Forms.DialogResult]::Abort
    } finally {
        $password.Clear()
        $showPassword.Checked = $false
        $connectButton.Enabled = $true
    }
})

$form.Add_Shown({ $email.Focus() })
$form.ResumeLayout($true)
$result = $form.ShowDialog()
$showPassword.Checked = $false
$password.Clear()
if ($null -ne $script:setupReport) {
    $script:setupReport | ConvertTo-Json -Compress -Depth 6
    if ($result -ne [Windows.Forms.DialogResult]::OK) { exit 20 }
    exit 0
}
[ordered]@{ status = 'cancelled'; message = 'De setup is gesloten. Er wordt niet automatisch opnieuw geprobeerd.' } | ConvertTo-Json -Compress
exit 2
