$ErrorActionPreference = 'Stop'
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
        if ($process.ExitCode -ne 0 -or $result.status -ne 'configured') { throw [string]$result.message }
        return $result
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
$form.Text = 'IMAP Plugin'
$form.ClientSize = New-Object Drawing.Size(720, 500)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
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
$title.Text = 'Connect your email'
$header.Controls.Add($title)

$intro = New-Object Windows.Forms.Label
$intro.Location = New-Object Drawing.Point(34, 82)
$intro.Size = New-Object Drawing.Size(650, 30)
$intro.ForeColor = $mutedColor
$intro.Text = 'Secure setup takes one step. We detect your provider settings automatically and keep your password on this computer.'
$header.Controls.Add($intro)

$card = New-Object Windows.Forms.Panel
$card.Location = New-Object Drawing.Point(32, 148)
$card.Size = New-Object Drawing.Size(656, 170)
$card.BackColor = $surface
$card.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
$form.Controls.Add($card)

$cardTitle = New-Object Windows.Forms.Label
$cardTitle.Location = New-Object Drawing.Point(24, 15)
$cardTitle.Size = New-Object Drawing.Size(600, 22)
$cardTitle.Text = 'Secure connection'
$cardTitle.ForeColor = $textColor
$cardTitle.Font = New-Object Drawing.Font('Segoe UI', 10, [Drawing.FontStyle]::Bold)
$card.Controls.Add($cardTitle)

$cardHint = New-Object Windows.Forms.Label
$cardHint.Location = New-Object Drawing.Point(24, 38)
$cardHint.Size = New-Object Drawing.Size(600, 20)
$cardHint.Text = 'Use your normal password or a provider-issued app password.'
$cardHint.ForeColor = $mutedColor
$cardHint.Font = New-Object Drawing.Font('Segoe UI', 9)
$card.Controls.Add($cardHint)

$emailLabel = New-Object Windows.Forms.Label
$emailLabel.Location = New-Object Drawing.Point(24, 76)
$emailLabel.Size = New-Object Drawing.Size(128, 24)
$emailLabel.Text = 'Email address'
$emailLabel.ForeColor = $textColor
$card.Controls.Add($emailLabel)

$email = New-Object Windows.Forms.TextBox
$email.Location = New-Object Drawing.Point(160, 72)
$email.Size = New-Object Drawing.Size(456, 29)
$email.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
$email.BackColor = $surface
$email.ForeColor = $textColor
$email.Font = New-Object Drawing.Font('Segoe UI', 10)
$email.TabIndex = 0
$card.Controls.Add($email)

$passwordLabel = New-Object Windows.Forms.Label
$passwordLabel.Location = New-Object Drawing.Point(24, 118)
$passwordLabel.Size = New-Object Drawing.Size(128, 24)
$passwordLabel.Text = 'Password'
$passwordLabel.ForeColor = $textColor
$card.Controls.Add($passwordLabel)

$password = New-Object Windows.Forms.TextBox
$password.Location = New-Object Drawing.Point(160, 114)
$password.Size = New-Object Drawing.Size(320, 29)
$password.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
$password.BackColor = $surface
$password.ForeColor = $textColor
$password.Font = New-Object Drawing.Font('Segoe UI', 10)
$password.UseSystemPasswordChar = $true
$password.TabIndex = 1
$card.Controls.Add($password)

$showPassword = New-Object Windows.Forms.CheckBox
$showPassword.Location = New-Object Drawing.Point(500, 116)
$showPassword.Size = New-Object Drawing.Size(120, 24)
$showPassword.Text = 'Show password'
$showPassword.ForeColor = $mutedColor
$showPassword.Font = New-Object Drawing.Font('Segoe UI', 9)
$showPassword.Checked = $false
$showPassword.TabIndex = 2
$showPassword.Add_CheckedChanged({ $password.UseSystemPasswordChar = -not $showPassword.Checked })
$card.Controls.Add($showPassword)

$statusPanel = New-Object Windows.Forms.Panel
$statusPanel.Location = New-Object Drawing.Point(32, 340)
$statusPanel.Size = New-Object Drawing.Size(656, 64)
$statusPanel.BackColor = $statusBackground
$statusPanel.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
$form.Controls.Add($statusPanel)

$status = New-Object Windows.Forms.Label
$status.Location = New-Object Drawing.Point(16, 12)
$status.Size = New-Object Drawing.Size(624, 38)
$status.ForeColor = $accentColor
$status.Text = 'Ready when you are. Secure settings will be detected automatically.'
$status.AutoEllipsis = $true
$statusPanel.Controls.Add($status)

$footerNote = New-Object Windows.Forms.Label
$footerNote.Location = New-Object Drawing.Point(32, 420)
$footerNote.Size = New-Object Drawing.Size(440, 24)
$footerNote.Text = 'Credentials stay on this computer and are never sent to Codex.'
$footerNote.ForeColor = $mutedColor
$footerNote.Font = New-Object Drawing.Font('Segoe UI', 9)
$form.Controls.Add($footerNote)

$connectButton = New-Object Windows.Forms.Button
$connectButton.Location = New-Object Drawing.Point(496, 444)
$connectButton.Size = New-Object Drawing.Size(112, 38)
$connectButton.Text = 'Connect'
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
$cancelButton.Location = New-Object Drawing.Point(616, 444)
$cancelButton.Size = New-Object Drawing.Size(72, 38)
$cancelButton.Text = 'Cancel'
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
    $connectButton.Enabled = $false
    $status.ForeColor = [Drawing.Color]::DarkBlue
    $status.Text = 'Finding and verifying secure mail settings...'
    try {
        $address = $email.Text.Trim()
        if ($address -notmatch '^[^\s@]+@[^\s@]+$') { throw 'Enter one valid email address.' }
        if ([string]::IsNullOrEmpty($password.Text)) { throw 'Enter your password or provider-issued app password.' }
        $result = Invoke-AutoConfigure $address $password.Text
        [ImapPluginCredential]::WriteLocalMachine('imap-plugin/imap', $password.Text)
        [void][ImapPluginCredential]::Metadata('imap-plugin/imap')
        if ([bool]$result.smtp_configured) {
            [ImapPluginCredential]::WriteLocalMachine('imap-plugin/smtp', $password.Text)
            [void][ImapPluginCredential]::Metadata('imap-plugin/smtp')
        }
        Write-Config $result
        $capabilities = @('reading')
        if ([bool]$result.mailbox_actions_ready) { $capabilities += 'reviewed mailbox actions' }
        if ([bool]$result.send_ready) { $capabilities += 'reviewed sending' }
        [Windows.Forms.MessageBox]::Show(
            ('Connected. Ready for ' + ($capabilities -join ', ') + '.'),
            'IMAP Plugin',
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
        $form.DialogResult = [Windows.Forms.DialogResult]::OK
    } catch {
        $status.ForeColor = [Drawing.Color]::DarkRed
        $status.Text = $_.Exception.Message
    } finally {
        $password.Clear()
        $showPassword.Checked = $false
        $connectButton.Enabled = $true
    }
})

$form.Add_Shown({ $email.Focus() })
$result = $form.ShowDialog()
$showPassword.Checked = $false
$password.Clear()
if ($result -ne [Windows.Forms.DialogResult]::OK) {
    throw 'Mailbox setup was cancelled or did not complete.'
}
