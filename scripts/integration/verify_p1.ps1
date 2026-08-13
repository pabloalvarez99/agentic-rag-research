<#
.SYNOPSIS
    Run this agent's opt-in checks against a real production-rag instance, on the free path.

.DESCRIPTION
    Three steps, in order, and the middle one is the only one that touches Docker:

      1. Look for an instance already answering /health at -BaseUrl. If one is
         there, it is used as-is and nothing is started.
      2. Otherwise start production-rag's own documented demo stack by running
         its scripts/demo_setup.ps1 — this repository does not know how to build,
         ingest or configure that service, and a second copy of those steps here
         would be a copy that rots.
      3. Run tests/integration with the opt-in variables set.

    Cleanup is bounded by what this script started: a stack that was already
    running is left running, and a stack this script started is stopped with
    `docker compose down`, which keeps the named Qdrant volume exactly as
    production-rag's own docs describe. Either way the final line says what is
    still running and how to remove it. -KeepStack skips the teardown.

    Every request the tests send pins llm=fake, embedder=fake and rerank=off, so
    no billed provider can be reached even against a deployment that has keys
    configured. No credential is read, written or printed by this script; the
    provider-key probe reports only whether a value is present, never the value.

.PARAMETER BaseUrl
    Address of the instance to test. Default http://127.0.0.1:8000.

.PARAMETER P1Path
    Path to a production-rag checkout, used only if a stack has to be started.
    Defaults to $env:PRODUCTION_RAG_PATH, then to a sibling ../production-rag.

.PARAMETER KeepStack
    Leave a stack this script started running, for a follow-up investigation.

.PARAMETER StartTimeoutSeconds
    How long to wait for a freshly started stack to answer /health. Default 300.

.EXAMPLE
    .\scripts\integration\verify_p1.ps1
    .\scripts\integration\verify_p1.ps1 -BaseUrl http://127.0.0.1:8000 -KeepStack
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [string]$P1Path = $env:PRODUCTION_RAG_PATH,
    [switch]$KeepStack,
    [int]$StartTimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$BaseUrl = $BaseUrl.TrimEnd('/')
$startedStack = $false
$liveRan = $false
$resolvedP1 = ''
$savedOpenAiKey = $env:OPENAI_API_KEY
$savedCohereKey = $env:COHERE_API_KEY

function Test-Health {
    param([string]$Url, [int]$TimeoutSec = 3)
    try {
        return (Invoke-WebRequest "$Url/health" -UseBasicParsing -TimeoutSec $TimeoutSec).StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Resolve-P1Path {
    param([string]$Candidate)
    if ($Candidate) { $paths = @($Candidate) }
    else { $paths = @((Join-Path (Split-Path -Parent $repoRoot) 'production-rag')) }
    foreach ($path in $paths) {
        if ((Test-Path (Join-Path $path 'docker-compose.yml')) -and
            (Test-Path (Join-Path $path 'scripts/demo_setup.ps1'))) {
            return (Resolve-Path $path).Path
        }
    }
    throw @"
No production-rag checkout found (looked in: $($paths -join ', ')).

Point at one and re-run, or start the stack yourself and pass its address:
  .\scripts\integration\verify_p1.ps1 -P1Path C:\path\to\production-rag
  `$env:PRODUCTION_RAG_PATH = 'C:\path\to\production-rag'
"@
}

try {
    Write-Host "== production-rag live verification ==" -ForegroundColor Cyan
    Write-Host "target: $BaseUrl"

    if (Test-Health -Url $BaseUrl) {
        Write-Host "found an instance already answering /health; this script will not start or stop anything." -ForegroundColor Green
    }
    else {
        Write-Host "no instance at $BaseUrl; starting production-rag's documented demo stack."
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            throw "docker is required to start the demo stack, and none is installed. Start production-rag elsewhere and pass -BaseUrl."
        }
        $resolvedP1 = Resolve-P1Path -Candidate $P1Path
        Write-Host "using checkout: $resolvedP1"

        # The demo stack must not be able to place a billed call, whatever this
        # shell happens to have exported. Compose still reads production-rag's
        # own .env if it has one; that is its configuration, not this lane's, and
        # the probe below reports it without failing.
        $env:OPENAI_API_KEY = ''
        $env:COHERE_API_KEY = ''

        Push-Location $resolvedP1
        try {
            & (Join-Path $resolvedP1 'scripts/demo_setup.ps1')
            if ($LASTEXITCODE -ne 0) { throw "production-rag's demo_setup.ps1 failed with exit code $LASTEXITCODE." }
        }
        finally {
            Pop-Location
        }
        $startedStack = $true

        $deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
        while (-not (Test-Health -Url $BaseUrl) -and (Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 3
        }
        if (-not (Test-Health -Url $BaseUrl)) {
            throw "the stack started but $BaseUrl/health did not answer within $StartTimeoutSeconds seconds."
        }
        Write-Host "stack is up." -ForegroundColor Green
    }

    # Evidence, not a gate: a key present in the service's environment is the
    # operator's business. What matters for this lane is that every request it
    # sends pins the free providers, which tests/integration asserts per request.
    if ($startedStack) {
        Push-Location $resolvedP1
        try {
            $probe = & docker compose exec -T api python -c "import os; print(int(bool(os.environ.get('OPENAI_API_KEY'))), int(bool(os.environ.get('COHERE_API_KEY'))))" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "provider keys present in the API container (openai, cohere): $probe  [1 = a value is set; the value itself is never read or printed]"
            }
        }
        finally {
            Pop-Location
        }
    }

    $version = (Invoke-WebRequest "$BaseUrl/health" -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
    Write-Host "instance reports: $($version.service) $($version.version) ($($version.environment))"

    $python = Join-Path $repoRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path $python)) { $python = 'python' }

    $env:RUN_P1_INTEGRATION = '1'
    $env:PRODUCTION_RAG_URL = $BaseUrl
    Write-Host ''
    Write-Host "== tests/integration ==" -ForegroundColor Cyan
    Push-Location $repoRoot
    try {
        & $python -m pytest tests/integration -v
        $testExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $liveRan = $true
    if ($testExit -ne 0) { throw "tests/integration failed with exit code $testExit." }
    Write-Host ''
    Write-Host "live free-path E2E: PASSED against $BaseUrl" -ForegroundColor Green
}
finally {
    $env:OPENAI_API_KEY = $savedOpenAiKey
    $env:COHERE_API_KEY = $savedCohereKey
    Remove-Item Env:RUN_P1_INTEGRATION -ErrorAction SilentlyContinue
    Remove-Item Env:PRODUCTION_RAG_URL -ErrorAction SilentlyContinue

    Write-Host ''
    Write-Host "== cleanup ==" -ForegroundColor Cyan
    if (-not $startedStack) {
        Write-Host "nothing to clean up: this script did not start the instance at $BaseUrl, so it left it alone."
    }
    elseif ($KeepStack) {
        Write-Host "-KeepStack: the demo stack this script started is still running."
        Write-Host "  stop it with:  docker compose down          (in the production-rag checkout; keeps the vector index)"
        Write-Host "  and with:      docker compose down -v        (also drops the production-rag-qdrant-storage volume)"
    }
    else {
        Write-Host "stopping the demo stack this script started (the named Qdrant volume is kept, as production-rag's docs describe)."
        Push-Location $resolvedP1
        try {
            & docker compose down | Out-Host
        }
        finally {
            Pop-Location
        }
        Write-Host "removed: containers production-rag-api and production-rag-qdrant, network production-rag-net."
        Write-Host "kept:    volume production-rag-qdrant-storage and image production-rag-api:local. Remove them with 'docker compose down -v' and 'docker image rm production-rag-api:local'."
    }
    Write-Host ("live E2E actually ran: {0}" -f $(if ($liveRan) { 'yes' } else { 'no' }))
}
