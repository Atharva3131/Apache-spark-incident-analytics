#!/bin/bash

echo "======================================"
echo "Production Incident Intelligence Setup"
echo "======================================"

# Create venv if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
echo "This may take several minutes..."

echo "- Installing core packages..."
pip install pydantic requests python-dotenv

echo "- Installing data processing packages..."
pip install pandas numpy

echo "- Installing Spark..."
pip install pyspark==3.5.0

echo "- Installing visualization packages..."
pip install plotly streamlit

echo "- Installing database driver..."
pip install pymongo

echo "- Installing testing packages..."
pip install pytest pytest-cov

echo ""
echo "✅ Installation complete!"
echo ""
echo "To run the system:"
echo "  1. Activate venv: source venv/bin/activate"
echo "  2. Copy config: cp .env.example .env"
echo "  3. Start dashboard: streamlit run app.py"
echo ""
echo "To run tests:"
echo "  pytest tests/ -v"
echo ""
