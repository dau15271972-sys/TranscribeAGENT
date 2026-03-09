# TranscribeAGENT setup
Write-Host "========================================"
Write-Host "  TranscribeAGENT Setup"
Write-Host "========================================"
Write-Host ""

# Check Python
python --version
if ($?) {
    Write-Host "Python OK" -ForegroundColor Green
} else {
    Write-Host "Python not found" -ForegroundColor Red
    exit 1
}

# Create virtual environment
Write-Host ""
Write-Host "Creating virtual environment..." -ForegroundColor Cyan
python -m venv .venv

# Upgrade pip
Write-Host ""
Write-Host "Upgrading pip..." -ForegroundColor Cyan
.\.venv\Scripts\python -m pip install --upgrade pip

# Install requirements
Write-Host ""
Write-Host "Installing requirements..." -ForegroundColor Cyan
.\.venv\Scripts\pip install -r requirements.txt

# Check ffmpeg
Write-Host ""
Write-Host "Checking ffmpeg..." -ForegroundColor Cyan
ffmpeg -version
if ($?) {
    Write-Host "FFmpeg OK" -ForegroundColor Green
} else {
    Write-Host "FFmpeg not found. Install: winget install Gyan.FFmpeg" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================"
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "========================================"
Write-Host ""
Write-Host "Next: .venv\Scripts\activate"
Write-Host ""