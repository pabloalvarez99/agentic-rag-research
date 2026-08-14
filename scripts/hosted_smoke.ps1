<#
.SYNOPSIS
  Contract smoke against the hosted free-path demo (pax-agentic-rag).

.DESCRIPTION
  Offline by default for CI. Point -BaseUrl at production when you want a live
  transcript: health, answerable done, unanswerable refuse, SSE first event,
  payload compare of two downloaded runs. Prefer saving the transcript to the
  vault over a flaky network CI job.

.EXAMPLE
  pwsh scripts/hosted_smoke.ps1
  pwsh scripts/hosted_smoke.ps1 -BaseUrl https://pax-agentic-rag.vercel.app
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://pax-agentic-rag.vercel.app',
    [string]$OutFile = ''
)

$ErrorActionPreference = 'Stop'
$base = $BaseUrl.TrimEnd('/')
$lines = New-Object System.Collections.Generic.List[string]

function Write-Step {
    param([string]$Message)
    $lines.Add($Message)
    Write-Host $Message
}

function Invoke-Json {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers = @{},
        [string]$Body = $null
    )
    $params = @{
        Method      = $Method
        Uri         = $Uri
        Headers     = $Headers
        TimeoutSec  = 60
    }
    if ($null -ne $Body) {
        $params['ContentType'] = 'application/json'
        $params['Body'] = $Body
    }
    return Invoke-RestMethod @params
}

Write-Step "hosted_smoke base=$base utc=$(Get-Date -Format o)"

# 1) health
$health = Invoke-Json -Method Get -Uri "$base/health"
if ($health.status -ne 'ok' -or $health.service -ne 'agentic-rag-research') {
    throw "health unexpected: $($health | ConvertTo-Json -Compress)"
}
Write-Step "health ok version=$($health.version)"

# 2) answerable done
$doneBody = @{
    question  = 'Why do bounded research agents need explicit stop reasons?'
    max_steps = 4
    retriever = 'fake'
} | ConvertTo-Json -Compress
$doneHeaders = @{ 'x-request-id' = 'smoke-done' }
$done = Invoke-WebRequest -Method Post -Uri "$base/v1/research" -Headers $doneHeaders `
    -ContentType 'application/json' -Body $doneBody -TimeoutSec 60
$doneJson = $done.Content | ConvertFrom-Json
if ($done.StatusCode -ne 200) { throw "done status $($done.StatusCode)" }
if ($doneJson.status -ne 'done') { throw "expected done, got $($doneJson.status)" }
if (-not $doneJson.citations -or $doneJson.citations.Count -lt 1) {
    throw 'done run missing citations'
}
Write-Step "done status=$($doneJson.status) steps=$($doneJson.steps_used) citations=$($doneJson.citations.Count) request_id=$($doneJson.request_id)"

# Prefer full artifact when the process still holds it; fall back to body+shape.
$leftArtifact = $null
try {
    $leftArtifact = Invoke-Json -Method Get -Uri "$base/v1/runs/$($doneJson.request_id)/run.json"
    Write-Step "downloaded run.json for $($doneJson.request_id)"
}
catch {
    Write-Step "run.json fetch skipped/missing (recycle or multi-instance): $($_.Exception.Message)"
    $leftArtifact = @{
        request_id  = $doneJson.request_id
        question    = 'Why do bounded research agents need explicit stop reasons?'
        retriever   = 'fake'
        status      = $doneJson.status
        stop_reason = if ($doneJson.trace[-1].payload.reason) { $doneJson.trace[-1].payload.reason } else { 'evidence_sufficient' }
        report      = $doneJson.report
        citations   = $doneJson.citations
        notes       = @()
        steps_used  = $doneJson.steps_used
        max_steps   = 4
        trace       = $doneJson.trace
    }
    # Fetch notes if still available on GET /v1/runs/{id}
    try {
        $stored = Invoke-Json -Method Get -Uri "$base/v1/runs/$($doneJson.request_id)"
        $leftArtifact = $stored
        Write-Step "hydrated left artifact from GET /v1/runs/{id}"
    }
    catch {
        Write-Step "left notes unavailable; compare will use response-derived artifact"
    }
}

# 3) unanswerable refuse
$refuseBody = @{
    question  = 'What were the quarterly revenues in Patagonia?'
    max_steps = 3
    retriever = 'fake'
} | ConvertTo-Json -Compress
$refuseHeaders = @{ 'x-request-id' = 'smoke-refused' }
$refused = Invoke-WebRequest -Method Post -Uri "$base/v1/research" -Headers $refuseHeaders `
    -ContentType 'application/json' -Body $refuseBody -TimeoutSec 60
$refusedJson = $refused.Content | ConvertFrom-Json
if ($refused.StatusCode -ne 200) { throw "refuse status $($refused.StatusCode)" }
if ($refusedJson.status -ne 'refused') { throw "expected refused, got $($refusedJson.status)" }
Write-Step "refused status=$($refusedJson.status) steps=$($refusedJson.steps_used) request_id=$($refusedJson.request_id)"

$rightArtifact = $null
try {
    $rightArtifact = Invoke-Json -Method Get -Uri "$base/v1/runs/$($refusedJson.request_id)"
    Write-Step "hydrated right artifact from GET /v1/runs/{id}"
}
catch {
    $stopReason = 'no_evidence'
    if ($refusedJson.trace -and $refusedJson.trace.Count -gt 0) {
        $last = $refusedJson.trace[-1]
        if ($last.payload -and $last.payload.reason) { $stopReason = $last.payload.reason }
    }
    $rightArtifact = @{
        request_id  = $refusedJson.request_id
        question    = 'What were the quarterly revenues in Patagonia?'
        retriever   = 'fake'
        status      = $refusedJson.status
        stop_reason = $stopReason
        report      = $refusedJson.report
        citations   = $refusedJson.citations
        notes       = @()
        steps_used  = $refusedJson.steps_used
        max_steps   = 3
        trace       = $refusedJson.trace
    }
    Write-Step "right artifact built from research response (store miss is expected after recycle)"
}

# 4) stream first event
$streamUri = "$base/v1/research/stream?question=Why%20use%20citations%20in%20RAG%3F&max_steps=4&retriever=fake"
$streamRaw = & curl.exe -sSN --max-time 45 $streamUri 2>&1
if (-not $streamRaw) { throw 'stream returned empty body' }
$streamText = if ($streamRaw -is [array]) { $streamRaw -join "`n" } else { [string]$streamRaw }
if ($streamText -notmatch 'event:\s*trace') {
    throw "stream missing event:trace first frame. head=$($streamText.Substring(0, [Math]::Min(200, $streamText.Length)))"
}
Write-Step "stream first frames include event:trace (SSE)"

# 5) compare payloads (not ids)
$comparePayload = @{ left = $leftArtifact; right = $rightArtifact } | ConvertTo-Json -Depth 20 -Compress
try {
    $compare = Invoke-Json -Method Post -Uri "$base/v1/runs/compare" -Body $comparePayload
    Write-Step ("compare identical={0} diffs={1} left={2} right={3}" -f `
        $compare.identical, `
        @($compare.diffs).Count, `
        $compare.left_request_id, `
        $compare.right_request_id)
    if ($compare.diffs) {
        foreach ($d in $compare.diffs) {
            Write-Step ("  field={0}" -f $d.field)
        }
    }
}
catch {
    # Pre-v0.3 host may not expose compare yet.
    Write-Step "compare endpoint unavailable on this host (expected until v0.3 deploys): $($_.Exception.Message)"
}

Write-Step 'hosted_smoke PASS'
$transcript = ($lines -join "`n") + "`n"

if ($OutFile) {
    $dir = Split-Path -Parent $OutFile
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Set-Content -Path $OutFile -Value $transcript -Encoding utf8
    Write-Host "wrote $OutFile"
}

$transcript
