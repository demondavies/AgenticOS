$ErrorActionPreference = "Stop"

# ============================================================
# ARNIE — THE OAK VOICE LAB
# Generates a controlled audition set using the Kokoro CLI.
# Everything stays under G:\AgenticOS\models\kokoro
# ============================================================

$KokoroDir = "G:\AgenticOS\models\kokoro"
$Model = Join-Path $KokoroDir "kokoro-v1.0.onnx"
$Voices = Join-Path $KokoroDir "voices-v1.0.bin"
$Input = Join-Path $KokoroDir "oak_test.txt"
$OutputDir = Join-Path $KokoroDir "oak_voice_lab"

New-Item -ItemType Directory -Force $OutputDir | Out-Null

if (!(Test-Path $Model)) {
    throw "Missing model: $Model"
}

if (!(Test-Path $Voices)) {
    throw "Missing voices file: $Voices"
}

if (!(Test-Path $Input)) {
    @"
I am ARNIE.

Your local AI operating system is online.

I hear you. I understand you. And I am ready to execute.

Give me the mission.
"@ | Set-Content -Path $Input -Encoding UTF8
}

function Make-Voice {
    param(
        [string]$Name,
        [string]$Voice,
        [string]$Lang = "en-us",
        [double]$Speed = 0.92
    )

    $Output = Join-Path $OutputDir "$Name.wav"

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Generating: $Name" -ForegroundColor Yellow
    Write-Host "Voice:      $Voice" -ForegroundColor Gray
    Write-Host "Speed:      $Speed" -ForegroundColor Gray
    Write-Host "============================================================" -ForegroundColor Cyan

    & kokoro-tts `
        $Input `
        $Output `
        --voice $Voice `
        --lang $Lang `
        --speed $Speed `
        --model $Model `
        --voices $Voices

    if ($LASTEXITCODE -ne 0) {
        throw "Kokoro failed while generating $Name"
    }

    Write-Host "Created: $Output" -ForegroundColor Green
}

# ------------------------------------------------------------
# BASELINES
# ------------------------------------------------------------

Make-Voice "01_George" "bm_george" "en-gb" 0.92
Make-Voice "02_Fenrir" "am_fenrir" "en-us" 0.92
Make-Voice "03_Onyx" "am_onyx" "en-us" 0.92
Make-Voice "04_Adam" "am_adam" "en-us" 0.92

# ------------------------------------------------------------
# THE OAK BLENDS
# George gives us the calm British authority.
# The American male voices push toward a heavier masculine sound.
# ------------------------------------------------------------

Make-Voice "05_Oak_George70_Fenrir30" "bm_george:70,am_fenrir:30" "en-gb" 0.90
Make-Voice "06_Oak_George70_Onyx30"  "bm_george:70,am_onyx:30"  "en-gb" 0.90
Make-Voice "07_Oak_George60_Adam40"   "bm_george:60,am_adam:40"  "en-gb" 0.90

# ------------------------------------------------------------
# DEEPER / SLOWER CHARACTER TESTS
# ------------------------------------------------------------

Make-Voice "08_Oak_Deep_Fenrir" "bm_george:60,am_fenrir:40" "en-gb" 0.84
Make-Voice "09_Oak_Deep_Onyx"  "bm_george:60,am_onyx:40"  "en-gb" 0.84
Make-Voice "10_Oak_Deep_Adam"  "bm_george:60,am_adam:40"  "en-gb" 0.84

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "THE OAK VOICE LAB IS COMPLETE." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Open this folder:" -ForegroundColor Cyan
Write-Host $OutputDir -ForegroundColor White
Write-Host ""
Write-Host "Listen to files 01 through 10 and tell me which number sounds most like THE OAK." -ForegroundColor Yellow
Write-Host ""
