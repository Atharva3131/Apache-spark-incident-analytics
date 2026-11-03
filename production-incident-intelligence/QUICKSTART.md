# Quick Start Guide

## 5-Minute Setup

### 1. Install Dependencies

```powershell
# Windows PowerShell
cd c:\Users\Atharva\Documents\BigD-Spark\production-incident-intelligence

# Run setup script
.\setup.ps1
```

Or install manually:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install pydantic requests python-dotenv pandas pytest pytest-cov pyspark plotly streamlit pymongo
```

### 2. Start the Dashboard

```powershell
# Activate venv first
.\venv\Scripts\Activate.ps1

# Run Streamlit
streamlit run app.py
```

Then open **http://localhost:8501**

### 3. Generate an Incident

1. In the sidebar, select a scenario:
   - `normal` - No incident (baseline)
   - `db_exhaustion` - Database pool exhaustion
   - `payment_latency` - Payment service slow
   - `inventory_cascade` - Cascading failures

2. Click **"Generate & Investigate"**

3. Wait for processing (takes ~30 seconds first time)

4. View results in the dashboard tabs

## What Happens

```
Logs Generated (1500 normal + 400 incident)
        ↓
Spark Processing (aggregation, metrics)
        ↓
Anomaly Detection (threshold-based rules)
        ↓
Incident Correlation (dependency analysis)
        ↓
RCA Report (with recommendations)
        ↓
MongoDB Storage (optional)
        ↓
Dashboard Visualization
```

## Test It

```powershell
# Activate venv
.\venv\Scripts\Activate.ps1

# Run tests
pytest tests/ -v
```

Expected output: **28 passed**

## Files to Explore

| File | What It Does |
|------|-------------|
| `app.py` | Main dashboard |
| `config/settings.py` | Configuration |
| `src/generator/` | Log generation |
| `src/processing/` | Spark aggregations |
| `src/detection/` | Anomaly detection |
| `src/correlation/` | Incident correlation |
| `src/investigation/` | RCA generation |

## Configuration

Copy `.env.example` to `.env` and edit:

```bash
# Spark
SPARK_MASTER=local[*]
SPARK_DRIVER_MEMORY=2g

# MongoDB (optional)
MONGODB_ENABLED=true
MONGODB_URI=mongodb://localhost:27017

# Sarvam AI (optional)
SARVAM_API_KEY=your_key_here
```

## Troubleshooting

### "No module named 'pyspark'"
```powershell
.\venv\Scripts\python.exe -m pip install pyspark==3.5.0
```

### "Port 8501 already in use"
```powershell
streamlit run app.py --server.port 8502
```

### MongoDB connection fails
- MongoDB is optional - app works without it
- To enable: start local MongoDB or configure Atlas

### Sarvam API fails
- Falls back to deterministic RCA automatically
- Set SARVAM_API_KEY in .env to enable

## Next: Production Deployment

See **README.md** for:
- AWS EC2 setup
- Systemd service configuration
- Nginx reverse proxy
- MongoDB Atlas cloud setup
- Exact installation commands

---

**That's it! You're ready to investigate incidents.** 🚀
