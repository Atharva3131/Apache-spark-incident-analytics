# Test runner script

Write-Host "================================" -ForegroundColor Cyan
Write-Host "Running Production Incident Tests" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan

.\venv\Scripts\python.exe -m pytest tests/test_generator.py -v

Write-Host "`n" -ForegroundColor Green
Write-Host "Running detection tests..." -ForegroundColor Cyan
.\venv\Scripts\python.exe -m pytest tests/test_detection.py -v

Write-Host "`n" -ForegroundColor Green
Write-Host "Running correlation tests..." -ForegroundColor Cyan
.\venv\Scripts\python.exe -m pytest tests/test_correlation.py -v

Write-Host "`n================================" -ForegroundColor Green
Write-Host "✅ Test suite complete!" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green
