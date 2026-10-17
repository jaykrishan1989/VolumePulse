# Starts Volume Pulse if needed, then opens the dashboard in the browser.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$url = "http://127.0.0.1:8080"

function Test-Dashboard {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200
    } catch {
        return $false
    }
}

if (-not (Test-Dashboard)) {
    if (-not (Test-Path $python)) {
        $python = "python"
    }
    Start-Process -FilePath $python -ArgumentList "run.py" -WorkingDirectory $root -WindowStyle Minimized
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Dashboard) { break }
    }
}

Start-Process $url
