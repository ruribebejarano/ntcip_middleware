<#
.SYNOPSIS
Levanta, SIN VENTANAS, un controlador emulado + una RSU (agent/rsu_middleware.py)
por cada interseccion de un registro de RSU, con puertos asignados
automaticamente y logs a archivo. Opcionalmente tambien el servidor central
(con ese mismo registro) y la consola web.

.DESCRIPTION
Reemplaza las "una ventana por proceso" de los scripts de escenario (p. ej.
app_obu/pruebas/demo_hospital_nino.ps1 de la rama app-obu): aqui todo corre
oculto en segundo plano y se supervisa desde la consola del centro de
control (docs/CONSOLA.md, seccion "Demo con varias RSU").

No cambia nada de agent/, controller/ ni servidor/: solo los arranca con las
mismas variables de entorno que ya leen (RSU_ID, SNMP_PORT, CONTROLLER_PORT,
MQTT_BROKER_HOST/PORT, RSU_EVENTOS_DIR, REGISTRO_RSU_PATH).

Escribe:
  resultados/demo/<fecha>/estado.json   puertos, PID y logs de esta corrida
  resultados/demo/<fecha>/*.log         stdout/stderr de cada proceso
  resultados/demo/<fecha>/rsu<id>/      eventos_rsu_<id>.csv / eventos_ctrl_<id>.csv
  resultados/demo/<fecha>/servidor/     eventos del servidor central
  resultados/demo/actual.json           copia de estado.json de la ultima corrida
                                        (la consola lo lee por defecto)

Verificacion de RSU_ID repetidos, antes de lanzar nada:
  1. el propio registro no repite rsu_id;
  2. ninguna corrida anterior de este lanzador (resultados/demo/*/estado.json)
     tiene vivo un middleware con alguno de esos RSU_ID;
  3. ningun OTRO agent/rsu_middleware.py de esta maquina (lanzado a mano o
     por otro script) usa esos RSU_ID. El entorno de otro proceso no se
     puede leer desde fuera; se busca "RSU_ID=..." en la linea de comandos
     del proceso y de sus padres (asi lo dejan las ventanas de
     app_obu/pruebas/demo_*.ps1). Si no aparece, el RSU_ID es desconocido y
     se aborta salvo -Forzar.
Mismo RSU_ID contra el mismo broker = mismo client_id MQTT
(rsu-middleware-<RSU_ID>) y Mosquitto expulsa a uno de los dos en bucle.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\demo\lanzar_rsus.ps1 `
    -Registro E:\Tesis\ntcip_app\app_obu\pruebas\registro_rsu_hospital_nino.json -ConServidor -ConConsola
#>

param(
    [Parameter(Mandatory = $true)][string]$Registro,
    [string[]]$Rsus = @(),            # filtrar por rsu_id (por defecto: todas las del registro)
    [int]$SnmpBase = 1170,            # primer puerto UDP SNMP a probar
    [int]$CtrlBase = 9100,            # primer puerto TCP de controlador a probar
    [string]$Broker = "127.0.0.1",
    [int]$BrokerPort = 1883,
    [string]$TlsPki = "",           # carpeta de la PKI: RSU y servidor usan mTLS
    [string]$Python = "",
    [switch]$ConServidor,
    [switch]$ConConsola,
    [switch]$SinNavegador,            # con -ConConsola: no abrir el navegador
    [switch]$Forzar
)

$ErrorActionPreference = "Stop"
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $Python) { $Python = Join-Path $Raiz ".venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) { throw "No se encuentra el interprete '$Python' (usar -Python)." }
$DirDemo = Join-Path $Raiz "resultados\demo"
$Utf8SinBom = New-Object System.Text.UTF8Encoding($false)

function Escribir-Json($ruta, $objeto) {
    [System.IO.File]::WriteAllText($ruta, ($objeto | ConvertTo-Json -Depth 6), $Utf8SinBom)
}

function Procesos-Python {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue
}

# El python.exe de un venv en Windows es un lanzador que crea el interprete
# real como proceso hijo: un PID "conocido" cubre tambien a sus hijos.
function Es-Conocido($proc, $pidsConocidos) {
    return ($pidsConocidos -contains [int]$proc.ProcessId) -or ($pidsConocidos -contains [int]$proc.ParentProcessId)
}

# RSU_ID de un proceso ajeno, si figura en su linea de comandos o en la de
# hasta 3 procesos padre (p. ej. powershell -Command "$env:RSU_ID='4'; ...").
function RsuId-De($proc) {
    $p = $proc
    for ($i = 0; $i -lt 4 -and $p; $i++) {
        if ($p.CommandLine -match "RSU_ID\W{0,3}=\W{0,2}'?([A-Za-z0-9_-]+)") { return $Matches[1] }
        $p = Get-CimInstance Win32_Process -Filter "ProcessId = $($p.ParentProcessId)" -ErrorAction SilentlyContinue
    }
    return $null
}

Write-Host "=== Lanzador de RSU (sin ventanas) ===" -ForegroundColor Cyan

# --- Registro ---------------------------------------------------------------
$RegistroAbs = (Resolve-Path $Registro).Path
$reg = [System.IO.File]::ReadAllText($RegistroAbs) | ConvertFrom-Json
$lista = @($reg.rsu)
if ($Rsus.Count -gt 0) { $lista = @($lista | Where-Object { $Rsus -contains [string]$_.rsu_id }) }
if ($lista.Count -eq 0) { throw "El registro no tiene RSU (o el filtro -Rsus no coincide con ninguna)." }
$ids = @($lista | ForEach-Object { [string]$_.rsu_id })
$repetidos = @($ids | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name })
if ($repetidos.Count -gt 0) { throw "El registro repite rsu_id: $($repetidos -join ', ')" }
Write-Host "Registro: $RegistroAbs"
Write-Host "RSU a levantar: $($ids -join ', ')"

# --- Broker -----------------------------------------------------------------
$tcp = New-Object System.Net.Sockets.TcpClient
try {
    $iar = $tcp.BeginConnect($Broker, $BrokerPort, $null, $null)
    if (-not $iar.AsyncWaitHandle.WaitOne(1500) -or -not $tcp.Connected) { throw "sin respuesta" }
} catch {
    throw "El broker MQTT $Broker`:$BrokerPort no responde. Arrancarlo primero (docs/ARRANQUE_BROKER_LAPTOP.md)."
} finally { $tcp.Close() }
Write-Host "Broker MQTT $Broker`:$BrokerPort responde." -ForegroundColor Green

# --- RSU_ID repetidos ya corriendo -----------------------------------------
# Windows reutiliza los PID: el de una corrida vieja puede ser hoy otro
# programa (visto el 2026-11-11: una pestaña de Chrome bloqueaba el arranque
# con "RSU_ID ya corre"). Solo cuenta si es Python ejecutando ese script.
function Vive-Script([object]$id, [string]$patron) {
    if (-not $id) { return $false }
    $p = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$id)" -ErrorAction SilentlyContinue
    return ($p -and $p.Name -match '^pythonw?\.exe$' -and $p.CommandLine -match $patron)
}
$pidsConocidos = @()
$choques = @()
if (Test-Path $DirDemo) {
    foreach ($f in Get-ChildItem $DirDemo -Directory | ForEach-Object { Join-Path $_.FullName "estado.json" } | Where-Object { Test-Path $_ }) {
        $prev = [System.IO.File]::ReadAllText($f) | ConvertFrom-Json
        foreach ($r in @($prev.rsu)) {
            if (Vive-Script $r.pid_middleware "rsu_middleware\.py") {
                $pidsConocidos += [int]$r.pid_middleware
                if ($ids -contains [string]$r.rsu_id) { $choques += "RSU_ID=$($r.rsu_id) ya corre (PID $($r.pid_middleware), $f)" }
            }
            if (Vive-Script $r.pid_controlador "controller_emulator\.py") { $pidsConocidos += [int]$r.pid_controlador }
        }
        if (Vive-Script $prev.servidor.pid "servidor[\\/]main\.py") { $pidsConocidos += [int]$prev.servidor.pid }
        if (Vive-Script $prev.consola.pid "consola") { $pidsConocidos += [int]$prev.consola.pid }
    }
}
if ($choques.Count -gt 0) {
    $choques | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    throw "Hay RSU_ID repetidos ya corriendo. Detenerlos antes: scripts\demo\detener_rsus.ps1 -Todas"
}
$ajenos = @(Procesos-Python | Where-Object { $_.CommandLine -match "rsu_middleware\.py" -and -not (Es-Conocido $_ $pidsConocidos) })
# Solo el interprete "de arriba" (el hijo de un lanzador de venv repite la misma linea de comandos).
$pidsAjenos = @($ajenos | ForEach-Object { [int]$_.ProcessId })
$ajenos = @($ajenos | Where-Object { $pidsAjenos -notcontains [int]$_.ParentProcessId })
$problemas = @()
foreach ($a in $ajenos) {
    $idAjeno = RsuId-De $a
    if ($null -eq $idAjeno) { $problemas += "PID $($a.ProcessId): rsu_middleware.py con RSU_ID desconocido" }
    elseif ($ids -contains $idAjeno) { $problemas += "PID $($a.ProcessId): rsu_middleware.py con RSU_ID=$idAjeno, lanzado fuera de este script" }
    else { Write-Host "  PID $($a.ProcessId): otra RSU (RSU_ID=$idAjeno), no choca." -ForegroundColor DarkGray }
}
if ($ConServidor) {
    $srv = @(Procesos-Python | Where-Object { $_.CommandLine -match "servidor[\\/]main\.py" -and -not (Es-Conocido $_ $pidsConocidos) })
    if ($srv.Count -gt 0) { $problemas += "PID $($srv[0].ProcessId): ya hay un servidor/main.py corriendo (dos servidores decidirian por duplicado)" }
}
if ($problemas.Count -gt 0) {
    $problemas | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    if (-not $Forzar) {
        throw "Detener esos procesos antes de lanzar. -Forzar solo si corren contra OTRO broker (el choque es por broker: mismo client_id MQTT rsu-middleware-<RSU_ID>)."
    }
    Write-Host "  -Forzar: se continua igual (deben estar en otro broker que $Broker`:$BrokerPort)." -ForegroundColor Yellow
}
Write-Host "Sin RSU_ID repetidos corriendo." -ForegroundColor Green

# --- Puertos ----------------------------------------------------------------
$udpOcupados = @(Get-NetUDPEndpoint -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.LocalPort })
$tcpOcupados = @(Get-NetTCPConnection -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.LocalPort })
$puertoSnmp = $SnmpBase
$puertoCtrl = $CtrlBase
$plan = @()
foreach ($r in $lista) {
    while ($udpOcupados -contains $puertoSnmp) { $puertoSnmp++ }
    while ($tcpOcupados -contains $puertoCtrl) { $puertoCtrl++ }
    $plan += [ordered]@{ rsu_id = [string]$r.rsu_id; interseccion_id = [string]$r.interseccion_id;
                         snmp_host = "127.0.0.1"; snmp_port = $puertoSnmp; ctrl_port = $puertoCtrl }
    $puertoSnmp++; $puertoCtrl++
}

# --- Carpeta de la corrida --------------------------------------------------
$fecha = Get-Date -Format "yyyy-MM-ddTHHmmss"
$DirCorrida = Join-Path $DirDemo $fecha
New-Item -ItemType Directory -Force $DirCorrida | Out-Null

$VarsLimpias = "RSU_ID", "SNMP_PORT", "CONTROLLER_PORT", "RSU_EVENTOS_DIR", "REGISTRO_RSU_PATH", "RSU_TLS_CA", "RSU_TLS_CERT", "RSU_TLS_KEY", "SERVIDOR_TLS_CA", "SERVIDOR_TLS_CERT", "SERVIDOR_TLS_KEY"

# Rutas CA, certificado y llave de un cliente, emitido si falta.
function Vars-Tls($prefijo, $tipo, $id) {
    if (-not $TlsPki) { return @{} }
    # "Continue": openssl escribe en stderr, y con "Stop" PowerShell 5 lo toma como error.
    $ErrorActionPreference = "Continue"
    $a = @((Join-Path $Raiz "scripts\evaluacion\cert_cliente.py"), "--pki", $TlsPki, "--tipo", $tipo)
    if ($id) { $a += @("--id", $id) }
    $r = @(& $Python @a 2>$null)
    if ($r.Count -ne 3) { throw "No se pudo obtener el certificado de $tipo $id." }
    return @{ "${prefijo}_TLS_CA" = $r[0]; "${prefijo}_TLS_CERT" = $r[1]; "${prefijo}_TLS_KEY" = $r[2] }
}
function Iniciar-Oculto($nombre, $argumentos, $vars) {
    $guardadas = @{}
    foreach ($k in ($VarsLimpias + @($vars.Keys) + "PYTHONUNBUFFERED", "PYTHONIOENCODING", "MQTT_BROKER_HOST", "MQTT_BROKER_PORT" | Select-Object -Unique)) {
        $guardadas[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
        [Environment]::SetEnvironmentVariable($k, $null, "Process")
    }
    try {
        $env:PYTHONUNBUFFERED = "1"
        $env:PYTHONIOENCODING = "utf-8"
        $env:MQTT_BROKER_HOST = $Broker
        $env:MQTT_BROKER_PORT = "$BrokerPort"
        foreach ($k in $vars.Keys) { [Environment]::SetEnvironmentVariable($k, [string]$vars[$k], "Process") }
        $p = Start-Process -FilePath $Python -ArgumentList $argumentos -WorkingDirectory $Raiz -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $DirCorrida "$nombre.log") `
            -RedirectStandardError (Join-Path $DirCorrida "$nombre.err.log") -PassThru
    } finally {
        foreach ($k in $guardadas.Keys) { [Environment]::SetEnvironmentVariable($k, $guardadas[$k], "Process") }
    }
    return $p
}

function Esperar-Puerto($proto, $puerto, $proceso, $segundos) {
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        if ($proceso.HasExited) { return $false }
        if ($proto -eq "udp") { $ok = Get-NetUDPEndpoint -LocalPort $puerto -ErrorAction SilentlyContinue }
        else { $ok = Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue }
        if ($ok) { return $true }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

$estado = [ordered]@{
    creado = (Get-Date).ToString("o"); dir = $DirCorrida; registro = $RegistroAbs
    broker = "$Broker`:$BrokerPort"; rsu = @(); servidor = $null; consola = $null
}
$fallos = @()

Write-Host "`n=== Controlador + RSU por interseccion ===" -ForegroundColor Cyan
foreach ($r in $plan) {
    $id = $r.rsu_id
    $dirEventos = Join-Path $DirCorrida "rsu$id"
    $pc = Iniciar-Oculto "controlador_$id" @("controller\controller_emulator.py", "--port", $r.ctrl_port) @{ RSU_ID = $id; RSU_EVENTOS_DIR = $dirEventos }
    if (-not (Esperar-Puerto "tcp" $r.ctrl_port $pc 15)) { $fallos += "controlador RSU $id (ver controlador_$id.err.log)" }
    $pm = Iniciar-Oculto "rsu_$id" @("agent\rsu_middleware.py") ((Vars-Tls "RSU" "rsu" $id) + @{ RSU_ID = $id; RSU_EVENTOS_DIR = $dirEventos; SNMP_PORT = $r.snmp_port; CONTROLLER_PORT = $r.ctrl_port })
    if (-not (Esperar-Puerto "udp" $r.snmp_port $pm 20)) { $fallos += "middleware RSU $id (ver rsu_$id.err.log)" }
    $r.pid_controlador = $pc.Id
    $r.pid_middleware = $pm.Id
    $r.log_middleware = Join-Path $DirCorrida "rsu_$id.log"
    $r.log_controlador = Join-Path $DirCorrida "controlador_$id.log"
    $r.eventos_dir = $dirEventos
    $estado.rsu += $r
    Write-Host ("  RSU {0,-3} {1,-14} SNMP 127.0.0.1:{2}  controlador :{3}  PID {4}/{5}" -f $id, $r.interseccion_id, $r.snmp_port, $r.ctrl_port, $pc.Id, $pm.Id)
}

if ($ConServidor) {
    Write-Host "`n=== Servidor central ===" -ForegroundColor Cyan
    $ps = Iniciar-Oculto "servidor" @("servidor\main.py") ((Vars-Tls "SERVIDOR" "servidor" $null) + @{ REGISTRO_RSU_PATH = $RegistroAbs; RSU_EVENTOS_DIR = (Join-Path $DirCorrida "servidor") })
    Start-Sleep -Seconds 3
    if ($ps.HasExited) { $fallos += "servidor central (ver servidor.err.log)" }
    $estado.servidor = [ordered]@{ pid = $ps.Id; log = (Join-Path $DirCorrida "servidor.log") }
    Write-Host "  servidor central PID $($ps.Id) (registro $RegistroAbs)"
}

$estadoPath = Join-Path $DirCorrida "estado.json"
Escribir-Json $estadoPath $estado
Escribir-Json (Join-Path $DirDemo "actual.json") $estado

if ($ConConsola) {
    Write-Host "`n=== Consola del centro de control ===" -ForegroundColor Cyan
    $argsConsola = @("consola\servidor.py", "--estado-demo", $estadoPath)
    if ($SinNavegador) { $argsConsola += "--sin-navegador" }
    $pk = Iniciar-Oculto "consola" $argsConsola @{}
    $estado.consola = [ordered]@{ pid = $pk.Id; url = "http://127.0.0.1:8080/"; log = (Join-Path $DirCorrida "consola.log") }
    Escribir-Json $estadoPath $estado
    Escribir-Json (Join-Path $DirDemo "actual.json") $estado
    Write-Host "  consola PID $($pk.Id) -> http://127.0.0.1:8080/"
}

Write-Host ""
if ($fallos.Count -gt 0) {
    $fallos | ForEach-Object { Write-Host "  FALLO: $_" -ForegroundColor Red }
    Write-Host "Logs en $DirCorrida. Detener lo que quedo vivo con scripts\demo\detener_rsus.ps1" -ForegroundColor Red
    exit 1
}
Write-Host "=== Listo === Estado: $estadoPath" -ForegroundColor Green
Write-Host "Detener todo: powershell -ExecutionPolicy Bypass -File scripts\demo\detener_rsus.ps1"
