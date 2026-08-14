<# Fail unless a running agentic-rag-research API reports healthy JSON. #>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8010'
)

$ErrorActionPreference = 'Stop'
$uri = $BaseUrl.TrimEnd('/') + '/health'

try {
    $response = Invoke-RestMethod -Uri $uri -Method Get -TimeoutSec 10
}
catch {
    Write-Error "Health probe failed for ${uri}: $($_.Exception.Message)"
    exit 1
}

if ($response.status -ne 'ok' -or $response.service -ne 'agentic-rag-research') {
    Write-Error "Unexpected health response from ${uri}: $($response | ConvertTo-Json -Compress)"
    exit 1
}

$response | ConvertTo-Json -Compress
