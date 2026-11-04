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

function Levantar-Banco($puerto) {
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
        Verificar-Broker $puerto
        if ($Factor -ne 1) { Write-Host "AVISO: con -Factor distinto de 1 los resultados no sirven para medir." -ForegroundColor Yellow }
        $dirDemo = Levantar-Banco $puerto
        $rc = 1
        try {
            $argsObu = @("scripts\evaluacion\correr_emulada.py", "--trayectoria", (Join-Path $DirRutas "trayectoria_$Ruta.csv"),
                "--dir", $dirDemo, "--repeticiones", $Repeticiones, "--factor", $Factor, "--sigma-pos", $SigmaPos, "--broker-port", $puerto)
            if (-not $SinTls) { $argsObu += @("--pki", $Pki) }
            & $Python @argsObu
            $rc = $LASTEXITCODE
        } finally {
            & $Detener | Out-Null
        }
        if ($rc -ne 0) { Write-Host "AVISO: alguna repeticion fallo; el resumen puede estar incompleto." -ForegroundColor Yellow }
        Archivar-Y-Resumir $dirDemo "emulada" | Out-Null
    }

    "gnss" {
        Preparar-Ruta
        $puerto = if ($SinTls) { 1883 } else { 8883 }
        Verificar-Broker $puerto
        $conf = (Get-Content scripts\evaluacion\rutas.json -Raw | ConvertFrom-Json).$Ruta
        $certs = $null
        if (-not $SinTls) { $certs = & $Python scripts\evaluacion\cert_cliente.py --pki $Pki --tipo obu --id $ObuId }
        $dirDemo = Levantar-Banco $puerto
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
            if ($EsperaS -gt 0) { Start-Sleep -Seconds $EsperaS }
            else { Read-Host "`nPulsa Enter aqui cuando hayas terminado todas las misiones" | Out-Null }
        } finally {
            & $Detener | Out-Null
        }
        $destino = Archivar-Y-Resumir $dirDemo "gnss"
        Write-Host "Si exportaste el CSV de la tablet, guardalo en: $destino\tablet\"
    }
}
