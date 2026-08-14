<# Run one deterministic research question from a fresh-or-existing local venv. #>
[CmdletBinding()]
param(
    [string]$Question = 'What does hybrid retrieval buy over dense retrieval alone?'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

Push-Location $repoRoot
try {
    if (-not (Test-Path $venvPython)) {
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv.' }
    }

    & $venvPython -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Could not install development dependencies.' }

    $env:OPENAI_API_KEY = ''
    $env:COHERE_API_KEY = ''
    $env:PRODUCTION_RAG_URL = ''

    $result = & $venvPython -m agentic_rag.research `
        --question $Question `
        --retriever fake `
        --quiet
    if ($LASTEXITCODE -ne 0) { throw "Research command exited with code $LASTEXITCODE." }

    $payload = $result | ConvertFrom-Json
    [ordered]@{
        status = $payload.status
        steps_used = $payload.steps_used
        citations = @($payload.citations).Count
        request_id = $payload.request_id
    } | ConvertTo-Json -Compress
}
finally {
    Pop-Location
}
