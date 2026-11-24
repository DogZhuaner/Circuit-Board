param([switch]$ResetKey)
$ErrorActionPreference = 'Stop'
$secretFile = Join-Path $env:LOCALAPPDATA 'Circuit-Board\bailian-beijing.dpapi'
$key = ''
function Read-KeyText($secret) {
    return ([Net.NetworkCredential]::new('', $secret).Password).Trim()
}
if (!$ResetKey -and (Test-Path -LiteralPath $secretFile)) {
    try {
        $secret = ConvertTo-SecureString ((Get-Content -Raw -LiteralPath $secretFile).Trim())
        $key = Read-KeyText $secret
    } catch {
        Write-Host 'Saved credential could not be decrypted. Please enter the Beijing Bailian key again.'
    }
}
if ($key -notmatch '^sk-[A-Za-z0-9_-]{12,}$') {
    $secret = Read-Host 'Paste the complete Beijing Bailian API key (sk-...) and press Enter' -AsSecureString
    $key = Read-KeyText $secret
    if ($key -notmatch '^sk-[A-Za-z0-9_-]{12,}$') {
        throw 'Incomplete API key. Copy the entire sk-... value from Bailian and try again.'
    }
    $encrypted = ConvertFrom-SecureString $secret
    [IO.Directory]::CreateDirectory((Split-Path -Parent $secretFile)) | Out-Null
    [IO.File]::WriteAllText($secretFile, $encrypted, [Text.Encoding]::ASCII)
}
$env:CIRCUIT_VLM_API_KEY = $key
$env:CIRCUIT_VLM_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
$env:CIRCUIT_VLM_MODEL = 'qwen4-max'
$env:CIRCUIT_VLM_PROTOCOL = 'openai'
$env:CIRCUIT_VLM_QWEN_DIRECT = '1'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    @"
from pathlib import Path
import json
from flask import Flask
from teacher_webui.vision_panel import bp
app = Flask(__name__)
app.register_blueprint(bp)
p = Path('teacher_webui/static/vision/example.png')
with p.open('rb') as f:
    r = app.test_client().post('/api/vision-panel/analyze', data={'image': (f, p.name)})
if r.status_code != 200:
    raise SystemExit(r.get_json().get('error', str(r.status_code)))
def edges(rows):
    return {tuple(sorted((w['from'], w['to']))) for w in rows}
expected = edges(json.loads(p.with_suffix('.json').read_text(encoding='utf8'))['wires'])
for i, panel in enumerate(r.get_json()['panels'], 1):
    actual = edges(panel['wires'])
    print('Solution', i, 'expected', len(expected), 'returned', len(actual), 'matched', len(actual & expected))
    print('Missing:', sorted(expected - actual))
    print('Extra:', sorted(actual - expected))
"@ | python -
    if ($LASTEXITCODE) { throw 'Inference did not complete.' }
} finally {
    Remove-Item Env:CIRCUIT_VLM_API_KEY
    Pop-Location
}
