# Creates "GTA Clipper" shortcuts on the Desktop and in the Start menu
$app = Split-Path -Parent $PSScriptRoot
$shell = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))
foreach ($p in $places) {
  $l = $shell.CreateShortcut((Join-Path $p 'GTA Clipper.lnk'))
  $l.TargetPath = Join-Path $app '.venv\Scripts\pythonw.exe'
  $l.Arguments = '"' + (Join-Path $app 'desktop.py') + '"'
  $l.WorkingDirectory = $app
  $l.IconLocation = Join-Path $app 'assets\icon.ico'
  $l.Description = 'Turn GTA streams into short clips'
  $l.Save()
}
