# Instalador do AmpSim (Windows 10/11).
# Uso: dê duplo-clique em instalar.bat (ou: powershell -ExecutionPolicy Bypass -File instalar.ps1)
#
# O que ele faz, nesta ordem:
#   1. Instala o Python 3.13 pelo winget, se não houver Python 3.11+ no computador
#   2. Cria o ambiente .venv e instala as bibliotecas (requirements.txt)
#   3. Baixa os timbres e motores gratuitos (FluidSynth, GeneralUser GS, capturas NAM)
#   4. Oferece instalar um driver ASIO gratuito (ASIO4ALL ou FlexASIO), pelo winget
#   5. Compila o DSP uma vez (deixa a primeira abertura rápida) e cria o atalho na Área de Trabalho
#
# Python e drivers vêm das fontes oficiais (winget); timbres e motores vêm da cópia do AmpSim no
# GitHub (release extras-1, conferida por SHA-256), com as fontes oficiais como reserva.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Passo($n, $texto) { Write-Host ""; Write-Host "[$n/5] $texto" -ForegroundColor Cyan }
function Ok($texto) { Write-Host "      $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "      $texto" -ForegroundColor Yellow }

function Invoke-Py($parts, [string[]]$arguments) {
    $exe = $parts[0]
    $pre = @()
    if ($parts.Length -gt 1) { $pre = $parts[1..($parts.Length - 1)] }
    & $exe @pre @arguments
}

function Find-Python {
    foreach ($cmd in @("py -3.13", "py -3.12", "py -3.11", "python")) {
        $parts = $cmd.Split(" ")
        try {
            $v = Invoke-Py $parts @("-c", "import sys; print('%d.%d' % sys.version_info[:2])") 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $mm = $v.Trim().Split(".")
                if ([int]$mm[0] -eq 3 -and [int]$mm[1] -ge 11) { return $parts }
            }
        } catch { }
    }
    return $null
}

Write-Host "=== AmpSim — instalação ===" -ForegroundColor White
Write-Host "Pasta: $root"
if ($root.Length -gt 60) {
    Aviso "A pasta está num caminho longo. Se a instalação falhar com 'nome do arquivo muito grande',"
    Aviso "mova o projeto para um caminho curto (ex.: C:\AmpSim) e rode de novo."
}

# ------------------------------------------------------------------ 1. Python
Passo 1 "Python 3.11 ou mais novo"
$py = Find-Python
if (-not $py) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python não encontrado e o winget não está disponível. Instale o Python 3.13 em https://www.python.org/downloads/ (marque 'Add python.exe to PATH') e rode de novo."
    }
    Aviso "Python não encontrado. Instalando o Python 3.13 pelo winget (fonte oficial)..."
    winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = Find-Python
    if (-not $py) { throw "O Python foi instalado, mas ainda não aparece no PATH. Feche esta janela e rode o instalador de novo." }
}
Ok ("Usando: " + ($py -join " "))

# ------------------------------------------------------------------ 2. ambiente e bibliotecas
Passo 2 "Ambiente .venv e bibliotecas (numpy, numba, sounddevice, PySide6, scipy, pedalboard)"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Invoke-Py $py @("-m", "venv", ".venv")
}
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as bibliotecas (veja a mensagem acima)." }
Ok "Bibliotecas instaladas."

# ------------------------------------------------------------------ 3. timbres gratuitos
Passo 3 "Timbres e motores gratuitos (FluidSynth, GeneralUser GS, capturas NAM) ~33 MB"
& $venvPy tools\baixar_extras.py
if ($LASTEXITCODE -ne 0) { Aviso "Não foi possível baixar tudo agora (sem internet?). Rode 'tools\baixar_extras.py' depois." }
else { Ok "Timbres prontos em third_party\" }

# ------------------------------------------------------------------ 4. driver ASIO
Passo 4 "Driver ASIO (menor latência)"
Write-Host "      Se a sua placa/interface de áudio tem driver ASIO próprio (Focusrite, Behringer, etc.),"
Write-Host "      use o driver do fabricante e pule este passo."
Write-Host "      [1] ASIO4ALL  - funciona com placas comuns e USB simples (recomendado)"
Write-Host "      [2] FlexASIO  - alternativa moderna baseada em WASAPI"
Write-Host "      [0] Pular"
$choice = Read-Host "      Escolha"
if ($choice -eq "1" -or $choice -eq "2") {
    $id = if ($choice -eq "1") { "MichaelTippach.ASIO4ALL" } else { "dechamps.FlexASIO" }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Aviso "Instalando $id pelo winget (o Windows vai pedir permissão de administrador)..."
        winget install -e --id $id --accept-package-agreements --accept-source-agreements
    } else {
        Aviso "winget indisponível. Baixe o ASIO4ALL em https://asio4all.org ou o FlexASIO em https://github.com/dechamps/FlexASIO"
    }
} else { Ok "Pulado." }

# ------------------------------------------------------------------ 5. DSP e atalho
Passo 5 "Preparando o DSP (só na primeira vez, ~30 s) e o atalho"
$env:OPENBLAS_NUM_THREADS = "1"
& $venvPy -c "from ampsim.dsp.kernels import warmup; warmup(); print('DSP pronto')"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "criar_atalho.ps1")

Write-Host ""
Write-Host "Instalação concluída!" -ForegroundColor Green
Write-Host "Abra pelo atalho 'AmpSim' na Área de Trabalho (ou rode run.bat)."
Write-Host "No app: clique em 'Áudio...' e escolha ASIO (ou WASAPI) e a sua placa."
