# Cria (ou recria) o atalho "AmpSim" na Área de Trabalho apontando para esta pasta.
# Uso: clique com o botão direito > "Executar com o PowerShell", ou:
#   powershell -ExecutionPolicy Bypass -File criar_atalho.ps1
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $desktop 'AmpSim.lnk'))
$lnk.TargetPath = Join-Path $env:SystemRoot 'System32\cmd.exe'
$lnk.Arguments = '/c "' + (Join-Path $root 'run.bat') + '"'
$lnk.WorkingDirectory = $root
$lnk.IconLocation = (Join-Path $root 'assets\ampsim.ico') + ',0'
$lnk.WindowStyle = 7          # minimizado: o console só aparece na barra durante a 1a instalação
$lnk.Description = 'AmpSim - simulador de amp para guitarra, baixo e pads'
$lnk.Save()
Write-Host "Atalho criado em $(Join-Path $desktop 'AmpSim.lnk')"
