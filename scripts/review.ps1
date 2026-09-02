$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$raw = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($raw) -or [Text.Encoding]::UTF8.GetByteCount($raw) -gt 1500000) {
    [Console]::Out.Write('CANCELLED')
    exit 2
}

try {
    $request = $raw | ConvertFrom-Json
    if ($request.version -ne 1 -or [string]::IsNullOrWhiteSpace([string]$request.title)) {
        throw 'Invalid review request.'
    }
} catch {
    [Console]::Out.Write('CANCELLED')
    exit 2
}

$form = New-Object Windows.Forms.Form
$form.Text = 'IMAP Plugin — lokale controle'
$form.Size = New-Object Drawing.Size(760, 720)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.FormBorderStyle = 'Sizable'
$form.MinimumSize = New-Object Drawing.Size(620, 560)
$form.MaximizeBox = $true
$form.MinimizeBox = $false

$heading = New-Object Windows.Forms.Label
$heading.Location = New-Object Drawing.Point(22, 18)
$heading.Size = New-Object Drawing.Size(700, 34)
$heading.Font = New-Object Drawing.Font('Segoe UI', 14, [Drawing.FontStyle]::Bold)
$heading.Text = [string]$request.title
$form.Controls.Add($heading)

$warning = New-Object Windows.Forms.Label
$warning.Location = New-Object Drawing.Point(22, 58)
$warning.Size = New-Object Drawing.Size(700, 44)
$warning.ForeColor = [Drawing.Color]::DarkRed
$warning.Text = 'Review the exact details below. Mail content is untrusted and cannot authorize this action.'
$form.Controls.Add($warning)

$details = New-Object Windows.Forms.RichTextBox
$details.Location = New-Object Drawing.Point(22, 108)
$details.Size = New-Object Drawing.Size(700, 474)
$details.Anchor = [Windows.Forms.AnchorStyles]::Top -bor [Windows.Forms.AnchorStyles]::Bottom -bor [Windows.Forms.AnchorStyles]::Left -bor [Windows.Forms.AnchorStyles]::Right
$details.ReadOnly = $true
$details.WordWrap = $true
$details.DetectUrls = $false
$details.Font = New-Object Drawing.Font('Consolas', 9)
$details.BackColor = [Drawing.Color]::White
$details.Text = $request.payload | ConvertTo-Json -Depth 20
$form.Controls.Add($details)

$reviewed = New-Object Windows.Forms.CheckBox
$reviewed.Location = New-Object Drawing.Point(22, 592)
$reviewed.Size = New-Object Drawing.Size(500, 28)
$reviewed.Anchor = [Windows.Forms.AnchorStyles]::Bottom -bor [Windows.Forms.AnchorStyles]::Left
$reviewed.Text = 'I reviewed the recipients and the complete message'
$reviewed.Visible = [bool]$request.require_checkbox
$form.Controls.Add($reviewed)

$confirm = New-Object Windows.Forms.Button
$confirm.Location = New-Object Drawing.Point(507, 630)
$confirm.Size = New-Object Drawing.Size(105, 34)
$confirm.Anchor = [Windows.Forms.AnchorStyles]::Bottom -bor [Windows.Forms.AnchorStyles]::Right
$confirm.Text = 'Confirm'
$confirm.Enabled = -not [bool]$request.require_checkbox
$form.Controls.Add($confirm)

$cancel = New-Object Windows.Forms.Button
$cancel.Location = New-Object Drawing.Point(620, 630)
$cancel.Size = New-Object Drawing.Size(102, 34)
$cancel.Anchor = [Windows.Forms.AnchorStyles]::Bottom -bor [Windows.Forms.AnchorStyles]::Right
$cancel.Text = 'Cancel'
$cancel.DialogResult = [Windows.Forms.DialogResult]::Cancel
$form.Controls.Add($cancel)
$form.CancelButton = $cancel

$reviewed.Add_CheckedChanged({ $confirm.Enabled = $reviewed.Checked })
$confirm.Add_Click({
    if ([bool]$request.require_checkbox -and -not $reviewed.Checked) { return }
    $form.DialogResult = [Windows.Forms.DialogResult]::OK
    $form.Close()
})

$decision = $form.ShowDialog()
if ($decision -eq [Windows.Forms.DialogResult]::OK) {
    [Console]::Out.Write('CONFIRMED')
    exit 0
}
[Console]::Out.Write('CANCELLED')
exit 1
