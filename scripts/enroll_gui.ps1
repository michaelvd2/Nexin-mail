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

$form = New-Object Windows.Forms.Form
$form.Text = 'IMAP Plugin - secure setup'
$form.Size = New-Object Drawing.Size(610, 340)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false

$title = New-Object Windows.Forms.Label
$title.Location = New-Object Drawing.Point(24, 20)
$title.Size = New-Object Drawing.Size(550, 28)
$title.Font = New-Object Drawing.Font('Segoe UI', 13, [Drawing.FontStyle]::Bold)
$title.Text = 'Connect your email'
$form.Controls.Add($title)

$intro = New-Object Windows.Forms.Label
$intro.Location = New-Object Drawing.Point(24, 52)
$intro.Size = New-Object Drawing.Size(550, 40)
$intro.Text = 'Enter only your email address and password. Secure server settings are detected automatically. Your password stays on this computer.'
$form.Controls.Add($intro)

$emailLabel = New-Object Windows.Forms.Label
$emailLabel.Location = New-Object Drawing.Point(24, 105)
$emailLabel.Size = New-Object Drawing.Size(120, 24)
$emailLabel.Text = 'Email address'
$form.Controls.Add($emailLabel)
$email = New-Object Windows.Forms.TextBox
$email.Location = New-Object Drawing.Point(150, 102)
$email.Size = New-Object Drawing.Size(420, 24)
$form.Controls.Add($email)

$passwordLabel = New-Object Windows.Forms.Label
$passwordLabel.Location = New-Object Drawing.Point(24, 145)
$passwordLabel.Size = New-Object Drawing.Size(120, 24)
$passwordLabel.Text = 'Password'
$form.Controls.Add($passwordLabel)
$password = New-Object Windows.Forms.TextBox
$password.Location = New-Object Drawing.Point(150, 142)
$password.Size = New-Object Drawing.Size(300, 24)
$password.UseSystemPasswordChar = $true
$form.Controls.Add($password)

$showPassword = New-Object Windows.Forms.CheckBox
$showPassword.Location = New-Object Drawing.Point(460, 142)
$showPassword.Size = New-Object Drawing.Size(110, 24)
$showPassword.Text = 'Show'
$showPassword.Checked = $false
$showPassword.Add_CheckedChanged({ $password.UseSystemPasswordChar = -not $showPassword.Checked })
$form.Controls.Add($showPassword)

$status = New-Object Windows.Forms.Label
$status.Location = New-Object Drawing.Point(24, 190)
$status.Size = New-Object Drawing.Size(546, 45)
$status.ForeColor = [Drawing.Color]::DarkBlue
$status.Text = 'Codex will configure receiving, reviewed actions, and sending when the provider supports them.'
$form.Controls.Add($status)

$connectButton = New-Object Windows.Forms.Button
$connectButton.Location = New-Object Drawing.Point(372, 250)
$connectButton.Size = New-Object Drawing.Size(110, 32)
$connectButton.Text = 'Connect'
$form.Controls.Add($connectButton)
$form.AcceptButton = $connectButton

$cancelButton = New-Object Windows.Forms.Button
$cancelButton.Location = New-Object Drawing.Point(492, 250)
$cancelButton.Size = New-Object Drawing.Size(78, 32)
$cancelButton.Text = 'Cancel'
$cancelButton.DialogResult = [Windows.Forms.DialogResult]::Cancel
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
