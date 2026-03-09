# TranscribeAGENT — GUI launcher
# Opens a file picker, then runs transcription in a new terminal window

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"

# Check venv exists
if (-not (Test-Path $Python)) {
    [System.Windows.Forms.MessageBox]::Show(
        "Виртуальное окружение не найдено.`nЗапусти сначала: setup.ps1",
        "TranscribeAGENT — Ошибка",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
    exit 1
}

Add-Type -AssemblyName System.Windows.Forms

# --- File picker ---
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = "TranscribeAGENT — Выбери аудиофайл(ы)"
$dialog.Filter = "Аудио (*.mp3;*.wav;*.m4a;*.ogg;*.mp4;*.mkv;*.flac)|*.mp3;*.wav;*.m4a;*.ogg;*.mp4;*.mkv;*.flac|Все файлы (*.*)|*.*"
$dialog.Multiselect = $true
$dialog.InitialDirectory = [Environment]::GetFolderPath("MyDocuments")

if ($dialog.ShowDialog() -ne "OK") { exit 0 }

$files = $dialog.FileNames
$fileArgs = ($files | ForEach-Object { "`"$_`"" }) -join " "

# --- Mode picker ---
$form = New-Object System.Windows.Forms.Form
$form.Text = "TranscribeAGENT"
$form.Size = New-Object System.Drawing.Size(340, 200)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$label = New-Object System.Windows.Forms.Label
$label.Text = "Выбери режим транскрибации:"
$label.Location = New-Object System.Drawing.Point(20, 20)
$label.Size = New-Object System.Drawing.Size(290, 20)
$form.Controls.Add($label)

$btnPlain = New-Object System.Windows.Forms.Button
$btnPlain.Text = "Только текст (быстро)"
$btnPlain.Location = New-Object System.Drawing.Point(20, 55)
$btnPlain.Size = New-Object System.Drawing.Size(290, 35)
$btnPlain.Add_Click({ $form.Tag = "plain"; $form.Close() })
$form.Controls.Add($btnPlain)

$btnDiarize = New-Object System.Windows.Forms.Button
$btnDiarize.Text = "Разделить спикеров (--diarize)"
$btnDiarize.Location = New-Object System.Drawing.Point(20, 100)
$btnDiarize.Size = New-Object System.Drawing.Size(290, 35)
$btnDiarize.Add_Click({ $form.Tag = "diarize"; $form.Close() })
$form.Controls.Add($btnDiarize)

$form.ShowDialog() | Out-Null
$mode = $form.Tag

if (-not $mode) { exit 0 }

# --- Build command ---
$transcribePy = Join-Path $ProjectDir "transcribe.py"
if ($mode -eq "diarize") {
    $cmd = "& `"$Python`" `"$transcribePy`" $fileArgs --diarize"
} else {
    $cmd = "& `"$Python`" `"$transcribePy`" $fileArgs"
}

# --- Run in new terminal, stay open after finish ---
$runScript = @"
Set-Location '$ProjectDir'
Write-Host ""
$cmd
Write-Host ""
Write-Host "=== Готово! Нажми Enter чтобы закрыть ===" -ForegroundColor Green
Read-Host
"@

$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($runScript))
Start-Process powershell.exe -ArgumentList "-NoExit", "-EncodedCommand", $encoded
