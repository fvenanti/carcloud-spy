# Launcher diario del scraper de promos IG.
#
# Lanza Chrome real off-screen reusando el perfil $LocalAppData\CarCloudSPY\chrome_profile
# (donde tu sesion de IG quedo cacheada en la primera corrida manual), corre
# scrape_ig.py por CDP y mata el Chrome al terminar.
#
# Pensado para correr como Tarea Programada de Windows (1 vez por dia).
# Logea a $LocalAppData\CarCloudSPY\logs\ig-YYYYMMDD.log
#
# === Config requerida (env vars de la maquina o de la Tarea Programada) ===
#   CARCLOUDSPY_BASE_URL     ej. https://spy.aba.benvert.com.ar
#   CARCLOUDSPY_PROMO_TOKEN  igual al PROMO_INGEST_TOKEN del .env del server

$ErrorActionPreference = "Stop"

# --- Paths ---
$Root          = "$env:LOCALAPPDATA\CarCloudSPY"
$ProfileDir    = Join-Path $Root "chrome_profile"
$LogDir        = Join-Path $Root "logs"
$ChromeExe     = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$Port          = 9223                # distinto al puerto de pruebas (9222)
$ScriptDir     = $PSScriptRoot
$PythonScript  = Join-Path $ScriptDir "scrape_ig.py"

# Permite override por env (si moves Chrome o usas otra carpeta)
if ($env:CARCLOUDSPY_CHROME_EXE)     { $ChromeExe  = $env:CARCLOUDSPY_CHROME_EXE }
if ($env:CARCLOUDSPY_CHROME_PROFILE) { $ProfileDir = $env:CARCLOUDSPY_CHROME_PROFILE }
if ($env:CARCLOUDSPY_CDP_PORT)       { $Port       = [int]$env:CARCLOUDSPY_CDP_PORT }

# --- Setup carpetas y log ---
if (-not (Test-Path $Root))       { New-Item -ItemType Directory -Path $Root       | Out-Null }
if (-not (Test-Path $ProfileDir)) { New-Item -ItemType Directory -Path $ProfileDir | Out-Null }
if (-not (Test-Path $LogDir))     { New-Item -ItemType Directory -Path $LogDir     | Out-Null }

$LogFile = Join-Path $LogDir ("ig-" + (Get-Date -Format "yyyyMMdd") + ".log")
function Log($msg) {
  $line = "[" + (Get-Date -Format "HH:mm:ss") + "] " + $msg
  Add-Content -Path $LogFile -Value $line -Encoding utf8
  Write-Output $line
}

Log "=== run.ps1 START ==="
Log ("PROFILE=" + $ProfileDir)
Log ("PORT=" + $Port)

# --- Sanity check de env requeridas ---
if (-not $env:CARCLOUDSPY_BASE_URL -or -not $env:CARCLOUDSPY_PROMO_TOKEN) {
  Log "ERROR: faltan env vars CARCLOUDSPY_BASE_URL / CARCLOUDSPY_PROMO_TOKEN"
  exit 2
}

# --- Lanzar Chrome off-screen ---
$ChromeArgs = @(
  "--remote-debugging-port=$Port",
  "--user-data-dir=$ProfileDir",
  "--no-first-run",
  "--no-default-browser-check",
  "--disable-features=Translate,PrivacySandboxSettings4",
  "--window-position=-2400,-2400",
  "--window-size=1280,900",
  "about:blank"
)
$chromeProc = Start-Process -FilePath $ChromeExe -ArgumentList $ChromeArgs -PassThru
Log ("Chrome PID " + $chromeProc.Id + " lanzado off-screen")

# --- Esperar a que CDP responda (max 15s) ---
$cdpOk = $false
for ($i = 0; $i -lt 15; $i++) {
  Start-Sleep -Seconds 1
  try {
    $r = Invoke-WebRequest -Uri "http://localhost:$Port/json/version" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $cdpOk = $true; break }
  } catch {}
}
if (-not $cdpOk) {
  Log "ERROR: CDP no respondio en 15s"
  try { Stop-Process -Id $chromeProc.Id -Force } catch {}
  exit 3
}
Log "CDP listo"

# --- Correr el scraper ---
$env:CARCLOUDSPY_CDP_URL = "http://localhost:$Port"
try {
  $output = & python $PythonScript 2>&1
  $output | ForEach-Object { Log $_ }
  $exitCode = $LASTEXITCODE
  Log ("python exit=" + $exitCode)
} catch {
  Log ("python excepcion: " + $_.Exception.Message)
  $exitCode = 1
}

# --- Cerrar Chrome ---
try {
  Stop-Process -Id $chromeProc.Id -Force
  Log ("Chrome PID " + $chromeProc.Id + " cerrado")
} catch {
  Log ("no pude cerrar Chrome PID " + $chromeProc.Id + ": " + $_.Exception.Message)
}

Log "=== run.ps1 END ==="
exit $exitCode
