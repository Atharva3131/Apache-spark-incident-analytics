# Setup script for Production Incident Intelligence System

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Production Incident Intelligence Setup" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

# Check if venv exists
if (-not (Test-Path ".\venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
}

Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1

Write-Host "Installing dependencies..." -ForegroundColor Yellow
Write-Host "This may take several minutes..." -ForegroundColor Gray

# Install in stages to avoid timeouts
Write-Host "- Installing core packages..." -ForegroundColor Cyan
pip install pydantic requests python-dotenv

Write-Host "- Installing data processing packages..." -ForegroundColor Cyan
pip install pandas numpy

Write-Host "- Installing Spark..." -ForegroundColor Cyan
pip install pyspark==3.5.0

Write-Host "- Installing visualization packages..." -ForegroundColor Cyan
pip install plotly streamlit

Write-Host "- Installing database driver..." -ForegroundColor Cyan
pip install pymongo

Write-Host "- Installing testing packages..." -ForegroundColor Cyan
pip install pytest pytest-cov

Write-Host ""
Write-Host "✅ Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To run the system:" -ForegroundColor Cyan
Write-Host "  1. Activate venv: .\venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host "  2. Copy config: cp .env.example .env" -ForegroundColor Gray
Write-Host "  3. Start dashboard: streamlit run app.py" -ForegroundColor Gray
Write-Host ""
Write-Host "To run tests:" -ForegroundColor Cyan
Write-Host "  pytest tests/ -v" -ForegroundColor Gray
Write-Host ""
