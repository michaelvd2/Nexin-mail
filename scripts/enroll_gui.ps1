$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

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

function Normalize-DnsHost([string]$Value) {
    $candidate = $Value.Trim().TrimEnd('.')
    if ([string]::IsNullOrWhiteSpace($candidate)) { throw 'Mail server names are required.' }
    $parsedAddress = $null
    if ([System.Net.IPAddress]::TryParse($candidate, [ref]$parsedAddress)) { throw 'Use a DNS server name, not an IP address.' }
    $idn = New-Object System.Globalization.IdnMapping
    $ascii = $idn.GetAscii($candidate).ToLowerInvariant()
    if ([Uri]::CheckHostName($ascii) -ne [UriHostNameType]::Dns) { throw "Invalid DNS server name: $candidate" }
    return $ascii
}

function Read-Port([string]$Value, [string]$Name) {
    $number = 0
    if (-not [int]::TryParse($Value.Trim(), [ref]$number) -or $number -lt 1 -or $number -gt 65535) {
        throw "$Name must be between 1 and 65535."
    }
    return $number
}

function Write-Config([hashtable]$Values, [bool]$OperatorEnabled) {
    $stateDirectory = Join-Path $env:LOCALAPPDATA 'imap-plugin'
    [IO.Directory]::CreateDirectory($stateDirectory) | Out-Null
    $configPath = Join-Path $stateDirectory 'config.toml'
    $trusted = @($Values.TrustedAuthservIds | ForEach-Object { '"' + (Escape-TomlString $_) + '"' }) -join ', '
    $configurationLines = @(
        'account_id = "default"'
        'username = "' + (Escape-TomlString $Values.ImapUsername) + '"'
        'email_address = "' + (Escape-TomlString $Values.EmailAddress) + '"'
        'host = "' + (Escape-TomlString $Values.ImapHost) + '"'
        'port = ' + $Values.ImapPort
        'imap_security = "' + (Escape-TomlString $Values.ImapSecurity) + '"'
        'credential_target = "imap-plugin/imap"'
        'smtp_credential_target = "imap-plugin/smtp"'
        'trusted_authserv_ids = [' + $trusted + ']'
        'operator_enabled = ' + $(if ($OperatorEnabled) { 'true' } else { 'false' })
        'timeout_seconds = 15.0'
        'max_results = 20'
        'max_scan = 250'
        'max_days = 31'
        'max_message_bytes = 262144'
        'trace_max_bytes = 262144'
        'trace_files = 3'
    )
    if ($Values.ConfigureSmtp) {
        $configurationLines += @(
            'smtp_host = "' + (Escape-TomlString $Values.SmtpHost) + '"'
            'smtp_port = ' + $Values.SmtpPort
            'smtp_security = "' + (Escape-TomlString $Values.SmtpSecurity) + '"'
            'smtp_username = "' + (Escape-TomlString $Values.SmtpUsername) + '"'
        )
    }
    $configuration = $configurationLines -join "`n"
    $configuration += "`n"
    $temporary = Join-Path $stateDirectory ("config." + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temporary, $configuration, (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $temporary -Destination $configPath -Force
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $configPath '/inheritance:r' '/grant:r' "${identity}:(F)" '/grant:r' 'SYSTEM:(F)' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not apply the private configuration ACL.' }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
    return $configPath
}

function Add-Label([Windows.Forms.Form]$Form, [string]$Text, [int]$X, [int]$Y, [int]$Width = 145) {
    $control = New-Object Windows.Forms.Label
    $control.Location = New-Object Drawing.Point($X, $Y)
    $control.Size = New-Object Drawing.Size($Width, 24)
    $control.Text = $Text
    $Form.Controls.Add($control)
}

function Add-TextBox([Windows.Forms.Form]$Form, [int]$X, [int]$Y, [int]$Width = 425) {
    $control = New-Object Windows.Forms.TextBox
    $control.Location = New-Object Drawing.Point($X, $Y)
    $control.Size = New-Object Drawing.Size($Width, 24)
    $Form.Controls.Add($control)
    return $control
}

$form = New-Object Windows.Forms.Form
$form.Text = 'IMAP Plugin — secure local setup'
$form.Size = New-Object Drawing.Size(700, 790)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false

$intro = New-Object Windows.Forms.Label
$intro.Location = New-Object Drawing.Point(20, 16)
$intro.Size = New-Object Drawing.Size(650, 42)
$intro.Text = 'Connect one standards-based IMAP mailbox. SMTP is optional. Passwords stay in Windows Credential Manager and never enter Codex chat or configuration files.'
$form.Controls.Add($intro)

Add-Label $form 'Email address' 20 70
$email = Add-TextBox $form 170 67 485
Add-Label $form 'IMAP username' 20 106
$imapUsername = Add-TextBox $form 170 103 485
Add-Label $form 'IMAP server' 20 142
$imapHost = Add-TextBox $form 170 139 365
$imapHost.Text = ''
Add-Label $form 'Port' 545 142 35
$imapPort = Add-TextBox $form 585 139 70
$imapPort.Text = '993'
Add-Label $form 'IMAP security' 20 178
$imapSecurity = New-Object Windows.Forms.ComboBox
$imapSecurity.Location = New-Object Drawing.Point(170, 175)
$imapSecurity.Size = New-Object Drawing.Size(220, 24)
$imapSecurity.DropDownStyle = 'DropDownList'
[void]$imapSecurity.Items.Add('Implicit TLS')
[void]$imapSecurity.Items.Add('Mandatory STARTTLS')
$imapSecurity.SelectedIndex = 0
$form.Controls.Add($imapSecurity)
$imapSecurity.Add_SelectedIndexChanged({
    if ($imapSecurity.SelectedIndex -eq 1 -and $imapPort.Text -eq '993') { $imapPort.Text = '143' }
    if ($imapSecurity.SelectedIndex -eq 0 -and $imapPort.Text -eq '143') { $imapPort.Text = '993' }
})
Add-Label $form 'IMAP password' 20 214
$imapPassword = Add-TextBox $form 170 211 350
$imapPassword.UseSystemPasswordChar = $true
$showImapPassword = New-Object Windows.Forms.CheckBox
$showImapPassword.Location = New-Object Drawing.Point(530, 211)
$showImapPassword.Size = New-Object Drawing.Size(125, 24)
$showImapPassword.Text = 'Show password'
$showImapPassword.Checked = $false
$form.Controls.Add($showImapPassword)
Add-Label $form 'Confirm IMAP' 20 250
$imapConfirm = Add-TextBox $form 170 247 485
$imapConfirm.UseSystemPasswordChar = $true
$showImapPassword.Add_CheckedChanged({
    $masked = -not $showImapPassword.Checked
    $imapPassword.UseSystemPasswordChar = $masked
    $imapConfirm.UseSystemPasswordChar = $masked
})

$divider = New-Object Windows.Forms.Label
$divider.BorderStyle = 'Fixed3D'
$divider.Location = New-Object Drawing.Point(20, 288)
$divider.Size = New-Object Drawing.Size(635, 2)
$form.Controls.Add($divider)

$configureSmtp = New-Object Windows.Forms.CheckBox
$configureSmtp.Location = New-Object Drawing.Point(20, 296)
$configureSmtp.Size = New-Object Drawing.Size(635, 24)
$configureSmtp.Text = 'Also configure SMTP for exact reviewed sending'
$configureSmtp.Checked = $false
$form.Controls.Add($configureSmtp)

Add-Label $form 'SMTP username' 20 328
$smtpUsername = Add-TextBox $form 170 325 485
Add-Label $form 'SMTP server' 20 364
$smtpHost = Add-TextBox $form 170 361 365
Add-Label $form 'Port' 545 364 35
$smtpPort = Add-TextBox $form 585 361 70
$smtpPort.Text = '465'
Add-Label $form 'SMTP security' 20 400
$smtpSecurity = New-Object Windows.Forms.ComboBox
$smtpSecurity.Location = New-Object Drawing.Point(170, 397)
$smtpSecurity.Size = New-Object Drawing.Size(220, 24)
$smtpSecurity.DropDownStyle = 'DropDownList'
[void]$smtpSecurity.Items.Add('Implicit TLS')
[void]$smtpSecurity.Items.Add('Mandatory STARTTLS')
$smtpSecurity.SelectedIndex = 0
$form.Controls.Add($smtpSecurity)

$samePassword = New-Object Windows.Forms.CheckBox
$samePassword.Location = New-Object Drawing.Point(170, 434)
$samePassword.Size = New-Object Drawing.Size(330, 24)
$samePassword.Text = 'SMTP uses the same password/app-password'
$samePassword.Checked = $true
$samePassword.Enabled = $false
$form.Controls.Add($samePassword)
Add-Label $form 'SMTP password' 20 470
$smtpPassword = Add-TextBox $form 170 467 350
$smtpPassword.UseSystemPasswordChar = $true
$smtpPassword.Enabled = $false
$showSmtpPassword = New-Object Windows.Forms.CheckBox
$showSmtpPassword.Location = New-Object Drawing.Point(530, 467)
$showSmtpPassword.Size = New-Object Drawing.Size(125, 24)
$showSmtpPassword.Text = 'Show password'
$showSmtpPassword.Checked = $false
$showSmtpPassword.Enabled = $false
$form.Controls.Add($showSmtpPassword)
Add-Label $form 'Confirm SMTP' 20 506
$smtpConfirm = Add-TextBox $form 170 503 485
$smtpConfirm.UseSystemPasswordChar = $true
$smtpConfirm.Enabled = $false
$showSmtpPassword.Add_CheckedChanged({
    $masked = -not $showSmtpPassword.Checked
    $smtpPassword.UseSystemPasswordChar = $masked
    $smtpConfirm.UseSystemPasswordChar = $masked
})
$samePassword.Add_CheckedChanged({
    if ($samePassword.Checked) { $showSmtpPassword.Checked = $false }
    $smtpPassword.Enabled = $configureSmtp.Checked -and -not $samePassword.Checked
    $smtpConfirm.Enabled = $configureSmtp.Checked -and -not $samePassword.Checked
    $showSmtpPassword.Enabled = $configureSmtp.Checked -and -not $samePassword.Checked
})
$smtpFields = @($smtpUsername, $smtpHost, $smtpPort, $smtpSecurity)
foreach ($control in $smtpFields) { $control.Enabled = $false }
$configureSmtp.Add_CheckedChanged({
    foreach ($control in $smtpFields) { $control.Enabled = $configureSmtp.Checked }
    $samePassword.Enabled = $configureSmtp.Checked
    if (-not $configureSmtp.Checked -or $samePassword.Checked) { $showSmtpPassword.Checked = $false }
    $smtpPassword.Enabled = $configureSmtp.Checked -and -not $samePassword.Checked
    $smtpConfirm.Enabled = $configureSmtp.Checked -and -not $samePassword.Checked
    $showSmtpPassword.Enabled = $configureSmtp.Checked -and -not $samePassword.Checked
})

Add-Label $form 'Trusted auth server' 20 542
$trustedAuthserv = Add-TextBox $form 170 539 485

$enableOperator = New-Object Windows.Forms.CheckBox
$enableOperator.Location = New-Object Drawing.Point(20, 577)
$enableOperator.Size = New-Object Drawing.Size(635, 38)
$enableOperator.Text = 'Enable reviewed mailbox actions when MOVE, Drafts and Trash are safely available'
$enableOperator.Checked = $false
$form.Controls.Add($enableOperator)

$status = New-Object Windows.Forms.Label
$status.Location = New-Object Drawing.Point(20, 620)
$status.Size = New-Object Drawing.Size(635, 52)
$status.ForeColor = [Drawing.Color]::DarkRed
$form.Controls.Add($status)

$storeButton = New-Object Windows.Forms.Button
$storeButton.Location = New-Object Drawing.Point(440, 678)
$storeButton.Size = New-Object Drawing.Size(130, 32)
$storeButton.Text = 'Store && verify'
$form.Controls.Add($storeButton)
$form.AcceptButton = $storeButton

$cancelButton = New-Object Windows.Forms.Button
$cancelButton.Location = New-Object Drawing.Point(580, 678)
$cancelButton.Size = New-Object Drawing.Size(75, 32)
$cancelButton.Text = 'Cancel'
$cancelButton.DialogResult = [Windows.Forms.DialogResult]::Cancel
$form.Controls.Add($cancelButton)
$form.CancelButton = $cancelButton

$email.Add_Leave({
    if ([string]::IsNullOrWhiteSpace($imapUsername.Text)) { $imapUsername.Text = $email.Text }
    if ([string]::IsNullOrWhiteSpace($smtpUsername.Text)) { $smtpUsername.Text = $email.Text }
})

$storeButton.Add_Click({
    $storeButton.Enabled = $false
    $status.ForeColor = [Drawing.Color]::DarkBlue
    $status.Text = 'Validating locally…'
    try {
        $address = $email.Text.Trim()
        if ($address -notmatch '^[^\s@]+@[^\s@]+$') { throw 'Enter a valid single email address.' }
        if ([string]::IsNullOrWhiteSpace($imapUsername.Text)) { throw 'The IMAP username is required.' }
        if ([string]::IsNullOrEmpty($imapPassword.Text) -or $imapPassword.Text -cne $imapConfirm.Text) { throw 'The IMAP password entries are empty or do not match.' }
        $smtpSecret = $null
        if ($configureSmtp.Checked) {
            if ([string]::IsNullOrWhiteSpace($smtpUsername.Text)) { throw 'The SMTP username is required when SMTP is enabled.' }
            $smtpSecret = if ($samePassword.Checked) { $imapPassword.Text } else { $smtpPassword.Text }
            $smtpSecretConfirmation = if ($samePassword.Checked) { $imapConfirm.Text } else { $smtpConfirm.Text }
            if ([string]::IsNullOrEmpty($smtpSecret) -or $smtpSecret -cne $smtpSecretConfirmation) { throw 'The SMTP password entries are empty or do not match.' }
        }

        $values = @{
            EmailAddress = $address
            ImapUsername = $imapUsername.Text.Trim()
            ImapHost = Normalize-DnsHost $imapHost.Text
            ImapPort = Read-Port $imapPort.Text 'IMAP port'
            ImapSecurity = if ($imapSecurity.SelectedIndex -eq 0) { 'implicit_tls' } else { 'starttls' }
            ConfigureSmtp = $configureSmtp.Checked
            SmtpUsername = if ($configureSmtp.Checked) { $smtpUsername.Text.Trim() } else { '' }
            SmtpHost = if ($configureSmtp.Checked) { Normalize-DnsHost $smtpHost.Text } else { '' }
            SmtpPort = if ($configureSmtp.Checked) { Read-Port $smtpPort.Text 'SMTP port' } else { 0 }
            SmtpSecurity = if ($smtpSecurity.SelectedIndex -eq 0) { 'implicit_tls' } else { 'starttls' }
            TrustedAuthservIds = @($trustedAuthserv.Text.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ } | ForEach-Object { Normalize-DnsHost $_ })
        }

        [ImapPluginCredential]::WriteLocalMachine('imap-plugin/imap', $imapPassword.Text)
        [void][ImapPluginCredential]::Metadata('imap-plugin/imap')
        if ($configureSmtp.Checked) {
            [ImapPluginCredential]::WriteLocalMachine('imap-plugin/smtp', $smtpSecret)
            [void][ImapPluginCredential]::Metadata('imap-plugin/smtp')
        }
        [void](Write-Config $values $false)

        $pluginRoot = Split-Path -Parent $PSScriptRoot
        $python = Join-Path $pluginRoot 'runtime\python\python.exe'
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'The pinned local runtime is missing.' }
        $previousPythonPath = $env:PYTHONPATH
        $previousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
        $previousProfile = $env:IMAP_PLUGIN_PROFILE
        try {
            $env:PYTHONPATH = Join-Path $pluginRoot 'src'
            $env:PYTHONDONTWRITEBYTECODE = '1'
            $env:IMAP_PLUGIN_PROFILE = 'read'
            $doctorText = (& $python -m imap_plugin.cli doctor 2>&1 | Out-String)
            $doctorExit = $LASTEXITCODE
        } finally {
            $env:PYTHONPATH = $previousPythonPath
            $env:PYTHONDONTWRITEBYTECODE = $previousNoBytecode
            $env:IMAP_PLUGIN_PROFILE = $previousProfile
        }
        if ($doctorExit -ne 0) { throw 'Connection verification failed. Credentials remain local and operator mode remains disabled.' }
        $doctor = $doctorText | ConvertFrom-Json
        if ($enableOperator.Checked) {
            if (-not $doctor.mailbox_actions_ready) { throw 'Reading works, but safe MOVE, Drafts or Trash support is missing. Mailbox actions remain disabled.' }
            [void](Write-Config $values $true)
        }
        $status.ForeColor = [Drawing.Color]::DarkGreen
        $status.Text = if ($enableOperator.Checked) { 'Reviewed mailbox actions are enabled. Sending requires configured SMTP and always receives a separate exact review.' } else { 'Verified in safe read mode. Reviewed actions can be enabled later through setup.' }
        $form.DialogResult = [Windows.Forms.DialogResult]::OK
    } catch {
        $status.ForeColor = [Drawing.Color]::DarkRed
        $status.Text = $_.Exception.Message
    } finally {
        $imapPassword.Clear()
        $imapConfirm.Clear()
        $smtpPassword.Clear()
        $smtpConfirm.Clear()
        $showImapPassword.Checked = $false
        $showSmtpPassword.Checked = $false
        $storeButton.Enabled = $true
    }
})

$form.Add_Shown({ $email.Focus() })
$result = $form.ShowDialog()
$showImapPassword.Checked = $false
$showSmtpPassword.Checked = $false
$imapPassword.Clear()
$imapConfirm.Clear()
$smtpPassword.Clear()
$smtpConfirm.Clear()
if ($result -ne [Windows.Forms.DialogResult]::OK) {
    throw 'Mailbox setup was cancelled or did not complete.'
}
