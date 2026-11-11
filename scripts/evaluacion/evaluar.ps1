<#
.SYNOPSIS
Evaluaciones del lazo con OBU emulada o con la tablet (GNSS real).

.DESCRIPTION
Las rutas se editan en scripts\evaluacion\rutas.json. Guia: docs\EVALUACIONES.md.

Acciones:
  rutas     Muestra las rutas disponibles.
  preparar  Genera el registro de RSU y la trayectoria de -Ruta.
  emulada   Corre -Repeticiones misiones con la OBU emulada y resume.
  gnss      Levanta RSU y servidor, y espera la prueba con la tablet.
  resumen   Vuelve a resumir la carpeta -Dir.
  detener   Detiene RSU y servidor de una evaluacion interrumpida.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 emulada -Ruta pucp_mariano_cornejo
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 gnss -Ruta pucp_mariano_cornejo

.EXAMPLE
Prueba con la tablet que se cierra sola (broker incluido) y suspende la laptop:
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 gnss -Ruta ruta_casa_nogales -ConBroker -FinTrasInactividadMin 30 -DuracionMaxMin 240 -Suspender
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("rutas", "preparar", "emulada", "gnss", "resumen", "detener")]
    [string]$Accion = "rutas",
    [string]$Ruta = "",
    [int]$Repeticiones = 3,
    [double]$Factor = 1,            # 1 = tiempo real; otro valor no sirve para medir
    [double]$SigmaPos = 5,          # ruido GNSS de la OBU emulada, en metros
    [string]$ObuId = "obu-tab-01",  # identidad fija de la tablet
    [switch]$SinTls,                # usa el broker de desarrollo (1883), sin cifrar
    [int]$EsperaS = 0,              # gnss: termina solo tras N segundos, sin pulsar Enter
    [int]$FinTrasInactividadMin = 0,# gnss: termina solo cuando las misiones terminaron y el servidor lleva N min sin eventos
    [int]$DuracionMaxMin = 0,       # gnss: tope de duracion total (0 = sin tope)
    [switch]$ConBroker,             # gnss/emulada: abre el broker TLS si no esta abierto, y lo cierra al final
    [switch]$Suspender,             # gnss: al terminar y resumir, suspende la laptop
    [string]$Dir = ""
)

$ErrorActionPreference = "Continue"
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Raiz
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "No existe .venv\Scripts\python.exe (ver docs\GUIA_COMANDOS.md)." }
$Pki = Join-Path $Raiz "deploy\pki"
$DirRutas = Join-Path $Raiz "resultados\evaluacion\rutas"
$Lanzar = Join-Path $Raiz "scripts\demo\lanzar_rsus.ps1"
$Detener = Join-Path $Raiz "scripts\demo\detener_rsus.ps1"
$env:PYTHONIOENCODING = "utf-8"

function Exigir-Ruta {
    if (-not $Ruta) {
        & $Python scripts\evaluacion\preparar_ruta.py --listar
        throw "Falta -Ruta <nombre>. Las rutas estan en scripts\evaluacion\rutas.json."
    }
}

function Preparar-Ruta {
    Exigir-Ruta
    & $Python scripts\evaluacion\preparar_ruta.py --ruta $Ruta
    if ($LASTEXITCODE -ne 0) { throw "No se pudo preparar la ruta '$Ruta' (ver mensaje arriba)." }
}

function Verificar-Broker($puerto) {
    if (Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue) { return }
    if ($puerto -eq 8883) {
        throw "No hay broker TLS en el puerto 8883. En otra terminal:`n  & 'C:\Program Files (x86)\Mosquitto\mosquitto.exe' -c deploy\pki\mosquitto_laptop_tls.conf -v"
    }
    throw "No hay broker en el puerto $puerto. PowerShell como administrador: Start-Service mosquitto"
}

$Mosquitto = "C:\Program Files (x86)\Mosquitto\mosquitto.exe"
$script:BrokerPropio = $null

# Abre el broker TLS oculto si nadie lo tiene abierto (-ConBroker). Solo se
# cierra al final el que abrio este script, nunca uno que ya estaba corriendo.
function Abrir-Broker($puerto) {
    if ($puerto -ne 8883) { return }
    if (Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue) { return }
    if (-not (Test-Path $Mosquitto)) { throw "No se encuentra $Mosquitto." }
    $dirLog = Join-Path $Raiz "resultados\evaluacion\_broker"
    New-Item -ItemType Directory -Force $dirLog | Out-Null
    $log = Join-Path $dirLog ("mosquitto_{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
    $script:BrokerPropio = Start-Process -FilePath $Mosquitto -ArgumentList @("-c", "deploy\pki\mosquitto_laptop_tls.conf", "-v") `
        -WorkingDirectory $Raiz -WindowStyle Hidden -RedirectStandardError $log `
        -RedirectStandardOutput ($log -replace '\.log$', '.out.log') -PassThru
    for ($i = 0; $i -lt 20; $i++) {
        if (Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue) {
            Write-Host "Broker TLS abierto en el puerto $puerto (log: $log)."
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "El broker no abrio el puerto $puerto (ver $log)."
}

function Cerrar-Broker {
    if ($script:BrokerPropio -and -not $script:BrokerPropio.HasExited) {
        Stop-Process -Id $script:BrokerPropio.Id -ErrorAction SilentlyContinue
        Write-Host "Broker TLS cerrado."
    }
}

# Mantiene la laptop despierta solo mientras corre la prueba, sin cambiar la
# configuracion de energia de Windows: al soltarlo, vuelve a su comportamiento
# normal (y puede suspenderse sola). La tapa cerrada puede suspenderla igual.
Add-Type -Namespace Evaluacion -Name Energia -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
'@
function Mantener-Despierta([bool]$si) {
    $ES_CONTINUOUS = [uint32]"0x80000000"; $ES_SYSTEM_REQUIRED = [uint32]1
    if ($si) { [Evaluacion.Energia]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED) | Out-Null }
    else { [Evaluacion.Energia]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null }
}

# Espera el fin de la prueba con la tablet. Termina con Enter o, con
# -FinTrasInactividadMin, cuando todas las misiones iniciadas ya terminaron y
# el servidor lleva ese tiempo sin registrar nada (si alguna quedo abierta,
# espera el doble). -DuracionMaxMin pone un tope. Devuelve el motivo.
function Esperar-Fin($dirDemo) {
    $eventosSrv = Join-Path $dirDemo "servidor\eventos_servidor.csv"
    $inicio = Get-Date
    $teclado = $true
    try { $null = [Console]::KeyAvailable } catch { $teclado = $false }
    $ultimoAviso = [datetime]::MinValue
    while ($true) {
        if ($teclado) {
            try {
                while ([Console]::KeyAvailable) { if ([Console]::ReadKey($true).Key -eq "Enter") { return "Enter" } }
            } catch { $teclado = $false }
        }
        $ahora = Get-Date
        if ($DuracionMaxMin -gt 0 -and ($ahora - $inicio).TotalMinutes -ge $DuracionMaxMin) {
            return "tope de $DuracionMaxMin min"
        }
        if ($FinTrasInactividadMin -gt 0 -and (Test-Path $eventosSrv)) {
            $texto = Get-Content $eventosSrv -Raw
            $armadas = ([regex]::Matches($texto, ",mision_armada,")).Count
            $desarmadas = ([regex]::Matches($texto, ",mision_desarmada,")).Count
            $quieto = ($ahora - (Get-Item $eventosSrv).LastWriteTime).TotalMinutes
            $limite = if ($desarmadas -ge $armadas) { $FinTrasInactividadMin } else { 2 * $FinTrasInactividadMin }
            if (($ahora - $ultimoAviso).TotalMinutes -ge 5) {
                Write-Host ("[{0:HH:mm}] misiones iniciadas {1}, terminadas {2}; sin eventos hace {3:N0} min (cierre automatico a los {4} min)" -f $ahora, $armadas, $desarmadas, $quieto, $limite)
                $ultimoAviso = $ahora
            }
            if ($armadas -gt 0 -and $quieto -ge $limite) {
                return "sin eventos durante $limite min (misiones iniciadas $armadas, terminadas $desarmadas)"
            }
        }
        Start-Sleep -Seconds 5
    }
}

function Levantar-Banco($puerto) {
    # Grafo propio de la ruta (campo "grafo" de rutas.json): el servidor lo lee de GRAFO_PATH.
    $grafo = (Get-Content (Join-Path $Raiz "scripts\evaluacion\rutas.json") -Raw -Encoding UTF8 | ConvertFrom-Json).$Ruta.grafo
    if ($grafo) { $env:GRAFO_PATH = (Join-Path $Raiz $grafo) } else { Remove-Item Env:GRAFO_PATH -ErrorAction SilentlyContinue }
    $argumentos = @{ Registro = (Join-Path $DirRutas "registro_rsu_$Ruta.json"); ConServidor = $true; Broker = "127.0.0.1"; BrokerPort = $puerto }
    if (-not $SinTls) { $argumentos.TlsPki = $Pki }
    & $Lanzar @argumentos | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron levantar las RSU o el servidor (ver mensaje arriba)." }
    return (Get-Content (Join-Path $Raiz "resultados\demo\actual.json") -Raw | ConvertFrom-Json).dir
}

function Archivar-Y-Resumir($dirDemo, $modo) {
    $destino = Join-Path $Raiz ("resultados\evaluacion\{0}_{1}_{2}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $Ruta, $modo)
    Copy-Item -Recurse $dirDemo $destino
    & $Python scripts\evaluacion\resumen.py --dir $destino | Out-Host
    return $destino
}

switch ($Accion) {
    "rutas" { & $Python scripts\evaluacion\preparar_ruta.py --listar }

    "preparar" { Preparar-Ruta }

    "resumen" {
        if (-not $Dir) { throw "Falta -Dir <carpeta de la evaluacion>." }
        & $Python scripts\evaluacion\resumen.py --dir $Dir
    }

    "detener" { & $Detener }

    "emulada" {
        Preparar-Ruta
        $puerto = if ($SinTls) { 1883 } else { 8883 }
        if ($ConBroker) { Abrir-Broker $puerto }
        Verificar-Broker $puerto
        if ($Factor -ne 1) { Write-Host "AVISO: con -Factor distinto de 1 los resultados no sirven para medir." -ForegroundColor Yellow }
        try { $dirDemo = Levantar-Banco $puerto } catch { Cerrar-Broker; throw }
        $rc = 1
        try {
            $argsObu = @("scripts\evaluacion\correr_emulada.py", "--trayectoria", (Join-Path $DirRutas "trayectoria_$Ruta.csv"),
                "--dir", $dirDemo, "--repeticiones", $Repeticiones, "--factor", $Factor, "--sigma-pos", $SigmaPos, "--broker-port", $puerto)
            if (-not $SinTls) { $argsObu += @("--pki", $Pki) }
            & $Python @argsObu
            $rc = $LASTEXITCODE
        } finally {
            & $Detener | Out-Null
            Cerrar-Broker
        }
        if ($rc -ne 0) { Write-Host "AVISO: alguna repeticion fallo; el resumen puede estar incompleto." -ForegroundColor Yellow }
        Archivar-Y-Resumir $dirDemo "emulada" | Out-Null
    }

    "gnss" {
        Preparar-Ruta
        $puerto = if ($SinTls) { 1883 } else { 8883 }
        if ($ConBroker) { Abrir-Broker $puerto }
        Verificar-Broker $puerto
        $conf = (Get-Content scripts\evaluacion\rutas.json -Raw | ConvertFrom-Json).$Ruta
        $certs = $null
        if (-not $SinTls) { $certs = & $Python scripts\evaluacion\cert_cliente.py --pki $Pki --tipo obu --id $ObuId }
        try { $dirDemo = Levantar-Banco $puerto } catch { Cerrar-Broker; throw }
        try {
            $ip = (& tailscale ip -4 2>$null | Select-Object -First 1)
            Write-Host "`n=== Prueba con la tablet ===" -ForegroundColor Cyan
            Write-Host "Ajustes de la app:"
            Write-Host "  Host del broker: $ip (Tailscale)   Puerto: $puerto"
            if ($certs) {
                Write-Host "  TLS/mTLS activado, con estos archivos copiados a la tablet:"
                $certs | ForEach-Object { Write-Host "    $_" }
            } else { Write-Host "  TLS/mTLS desactivado." }
            Write-Host "En la pantalla principal:"
            Write-Host "  1. Posicion: GPS real. Espera 'GNSS listo' en verde (al aire libre)."
            Write-Host ("  2. Ve al origen: {0}, {1}" -f $conf.origen[0], $conf.origen[1])
            Write-Host ("  3. Elige el destino en el mapa: {0}, {1}" -f $conf.destino[0], $conf.destino[1])
            Write-Host "  4. Iniciar emergencia y recorre la ruta que muestra la app."
            Write-Host "     A mas de 60 m de esa ruta, el servidor la recalcula."
            Write-Host "  5. Al terminar, finaliza la mision y exporta el CSV de eventos."
            Mantener-Despierta $true
            $motivo = "Enter"
            if ($EsperaS -gt 0) { Start-Sleep -Seconds $EsperaS; $motivo = "$EsperaS s" }
            elseif ($FinTrasInactividadMin -gt 0 -or $DuracionMaxMin -gt 0) {
                Write-Host "`nCierre automatico activado: pulsa Enter para terminar antes." -ForegroundColor Cyan
                $motivo = Esperar-Fin $dirDemo
            }
            else { Read-Host "`nPulsa Enter aqui cuando hayas terminado todas las misiones" | Out-Null }
            Write-Host "`nFin de la prueba ($motivo). Deteniendo RSU y servidor..." -ForegroundColor Cyan
        } finally {
            & $Detener | Out-Null
            Cerrar-Broker
            Mantener-Despierta $false
        }
        $destino = Archivar-Y-Resumir $dirDemo "gnss"
        "Fin: $motivo`r`nHora: $(Get-Date -Format s)" | Set-Content -Encoding UTF8 (Join-Path $destino "fin.txt")
        New-Item -ItemType Directory -Force (Join-Path $destino "tablet") | Out-Null
        Write-Host "Si exportaste el CSV de la tablet, guardalo en: $destino\tablet\"
        if ($Suspender) {
            Write-Host "Suspendiendo la laptop en 30 s (Ctrl+C para cancelar)..." -ForegroundColor Yellow
            Start-Sleep -Seconds 30
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, $false, $false) | Out-Null
        }
    }
}
