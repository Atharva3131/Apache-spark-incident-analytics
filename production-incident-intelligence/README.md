# Production Incident Detection & Root Cause Analysis System

An enterprise-grade AI-powered production incident investigation system that uses Apache Spark to process distributed logs, detect anomalies, correlate failures across microservices, and generate evidence-backed RCA reports using Sarvam AI.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│         Streamlit Dashboard (UI/UX)                         │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Synthetic Log Generator → Spark Processing → Anomaly Detect │
│                              ↓                                 │
│  Incident Correlator ← Evidence Collection ← Error Samples   │
│                              ↓                                 │
│  RCA Engine (Deterministic) ← Sarvam AI (Optional LLM)       │
│                              ↓                                 │
│           MongoDB Persistence (Optional)                      │
└─────────────────────────────────────────────────────────────┘
```

## Features

### A. Synthetic Log Generation
- Generates realistic microservice logs across 5 services:
  - API Gateway
  - Order Service
  - Payment Service
  - Inventory Service
  - Database Service
- Three incident scenarios:
  1. **Database Connection Pool Exhaustion** – DB overwhelmed, cascade to dependent services
  2. **Payment Service Latency Spike** – External gateway slowdown affecting order processing
  3. **Inventory Service Timeout** – Inventory failures causing order failures and API errors
- Deterministic generation with configurable random seed for reproducibility

### B. Apache Spark Processing
- Real PySpark DataFrames (not Pandas-only)
- Time-windowed aggregations (configurable window size)
- Per-service metrics:
  - Error counts & error rates
  - Average & percentile latency (p95, p99)
  - Health status per time window
- Local mode by default; optional HDFS/S3 path support

### C. Anomaly Detection
- Threshold-based rules (configurable):
  - High error rate detection
  - Latency spike detection (average & p95)
  - Minimum error count enforcement
- Severity classification (LOW, MEDIUM, HIGH, CRITICAL)
- Evidence preservation for every detection

### D. Incident Correlation
- Dependency graph-aware failure propagation
- Temporal correlation of events
- Root cause candidate ranking with confidence scores
- Cascading failure detection
- Clear separation of facts, correlations, and hypotheses
- Scenario hinting (db_exhaustion, payment_latency, inventory_cascade)

### E. Root Cause Analysis
- **Deterministic Engine**: Always available, rule-based
  - Service dependency analysis
  - Severity propagation
  - Actionable recommendations
  - Timeline generation
- **Sarvam AI Integration**: Optional LLM-powered investigation
  - Structured JSON responses
  - Fallback to deterministic when unavailable
  - Graceful error handling

### F. MongoDB Persistence
- Store incident records with full RCA
- Investigation history audit trail
- Query incidents by status/time
- Optional (works without MongoDB)

### G. Streamlit Dashboard
Professional multi-page UI:
- **Overview**: Incident summary, severity, affected services
- **Log Analytics**: Error distribution, latency comparison, volume over time
- **Incident Investigation**: RCA details, evidence, recommendations, timeline
- **Historical Incidents**: Search, filter, view previous investigations
- **Demo Controls**: Generate scenarios, trigger investigations

## Installation

### Prerequisites
- Python 3.11+
- Java 8+ (for Spark)
- MongoDB 4.4+ (optional)

### Local Development Setup

```bash
# Clone repository
cd production-incident-intelligence

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

### Configuration

Edit `.env`:

```bash
# Spark (local by default)
SPARK_MASTER=local[*]
SPARK_DRIVER_MEMORY=2g

# MongoDB (optional)
MONGODB_URI=mongodb://localhost:27017
MONGODB_ENABLED=true

# Sarvam AI (optional)
SARVAM_API_KEY=your_key_here
SARVAM_MODEL=sarvam-m
```

## Running the System

### Start Dashboard

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

Then open http://localhost:8501

### Generate & Investigate Incident

1. Open the dashboard
2. Select scenario from left sidebar:
   - Normal (no incident)
   - db_exhaustion
   - payment_latency
   - inventory_cascade
3. Adjust record counts (normal & incident)
4. Click "Generate & Investigate"
5. View results in tabs

### Run Tests

```bash
pytest tests/ -v --cov=src --cov-report=html
```

### Generate Sample Data Only

```python
from src.generator.log_generator import LogGenerator

gen = LogGenerator(seed=42)
records = gen.generate(scenario="db_exhaustion", n_normal=2000, n_incident=500)
gen.save_csv(records, "data/generated/incident.csv")
```

## MongoDB Setup (Optional)

### Local MongoDB with Docker

```bash
docker run -d \
  -p 27017:27017 \
  -e MONGO_INITDB_ROOT_USERNAME=admin \
  -e MONGO_INITDB_ROOT_PASSWORD=password \
  mongo:latest

# Connect string
mongodb://admin:password@localhost:27017
```

### MongoDB Atlas (Cloud)

1. Create account at https://www.mongodb.com/cloud/atlas
2. Create cluster
3. Copy connection string
4. Add to `.env`:
   ```
   MONGODB_URI=mongodb+srv://user:password@cluster.mongodb.net/incident_intelligence
   ```

## Sarvam AI Integration (Optional)

1. Get API key from https://www.sarvam.ai
2. Add to `.env`:
   ```
   SARVAM_API_KEY=your_api_key
   SARVAM_MODEL=sarvam-m
   ```
3. System will use it automatically if configured
4. Falls back to deterministic engine if unavailable

## AWS EC2 Deployment

### Setup Ubuntu 22.04 Instance

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip

# Install Java (required for Spark)
sudo apt install -y openjdk-11-jdk

# Install Git
sudo apt install -y git

# Clone repository
git clone https://github.com/your-org/production-incident-intelligence.git
cd production-incident-intelligence

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment
cp .env.example .env
# Edit .env with your configuration
nano .env
```

### Start Streamlit Service

```bash
# Create systemd service
sudo tee /etc/systemd/system/incident-intelligence.service > /dev/null <<EOF
[Unit]
Description=Production Incident Intelligence
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/production-incident-intelligence
Environment="PATH=/home/ubuntu/production-incident-intelligence/venv/bin"
ExecStart=/home/ubuntu/production-incident-intelligence/venv/bin/streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable & start service
sudo systemctl enable incident-intelligence
sudo systemctl start incident-intelligence

# View logs
sudo journalctl -u incident-intelligence -f
```

### Configure Nginx Reverse Proxy

```bash
# Install Nginx
sudo apt install -y nginx

# Create config
sudo tee /etc/nginx/sites-available/incident-intelligence > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/incident-intelligence /etc/nginx/sites-enabled/
sudo systemctl restart nginx
```

## Project Structure

```
production-incident-intelligence/
├── app.py                          # Streamlit main entry
├── requirements.txt                # Dependencies
├── .env.example                    # Configuration template
├── .gitignore
├── README.md
├── config/
│   └── settings.py                # Centralized config
├── data/
│   └── generated/                 # Output logs
├── src/
│   ├── generator/
│   │   └── log_generator.py        # Synthetic log generation
│   ├── ingestion/
│   │   └── log_ingestion.py        # CSV/JSON/in-memory ingestion
│   ├── processing/
│   │   └── spark_processor.py      # Spark aggregations
│   ├── detection/
│   │   └── anomaly_detector.py     # Threshold-based anomaly detection
│   ├── correlation/
│   │   └── incident_correlator.py  # Dependency graph correlation
│   ├── investigation/
│   │   ├── rca_engine.py           # Deterministic RCA
│   │   └── sarvam_client.py        # Sarvam AI integration
│   ├── storage/
│   │   └── mongodb_store.py        # MongoDB persistence
│   └── models/
│       └── incident.py             # Pydantic models
└── tests/
    ├── test_generator.py           # Generator tests
    ├── test_detection.py           # Anomaly detection tests
    └── test_correlation.py         # Correlation tests
```

## Engineering Decisions

### Why Spark?
- Handles large log volumes efficiently
- Distributable (scales from local → multi-node)
- Native DataFrame API for aggregations
- Better than Pandas for production workloads

### Why Threshold-Based Anomaly Detection?
- Deterministic and explainable
- No model training required
- Configurable per environment
- Clear cause-and-effect

### Why Deterministic RCA as Fallback?
- Never breaks when external APIs fail
- Consistent output schema
- Domain rules are transparent
- Easier to debug and audit

### Why Streamlit?
- Fast MVP development
- Interactive widgets for demo controls
- Great for data visualization
- Deploys easily to cloud

### Why MongoDB Optional?
- MVP doesn't require persistence
- Easy to add later
- Graceful operation without it
- Cloud-friendly (Atlas)

## Limitations & Future Work

### Current MVP
- Local Spark mode only (not distributed)
- No real-time streaming (batch processing only)
- Deterministic thresholds (no ML models)
- No distributed tracing integration (could add Jaeger later)

### Future Enhancements
1. Kafka/Kinesis streaming ingestion
2. Structured query API (SQL-like interface)
3. Custom ML-based anomaly detection
4. Integration with monitoring systems (Prometheus, DataDog)
5. Distributed Spark cluster support
6. Slack/PagerDuty alerting
7. Historical trending and pattern learning
8. Multi-incident correlation

## Troubleshooting

### Java/Spark errors
```bash
# Verify Java installation
java -version

# Set JAVA_HOME if needed
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
```

### MongoDB connection timeout
```bash
# Verify MongoDB is running
mongosh "mongodb://localhost:27017"

# Check MongoDB logs
sudo journalctl -u mongod -f
```

### Streamlit port already in use
```bash
# Use different port
streamlit run app.py --server.port 8502
```

### Out of memory errors
```bash
# Increase Spark driver memory
export SPARK_DRIVER_MEMORY=4g
streamlit run app.py
```

## Contributing

1. Fork repository
2. Create feature branch (`git checkout -b feature/amazing-thing`)
3. Write tests for new code
4. Run pytest before committing
5. Submit pull request

## License

MIT License – see LICENSE file

## Support

- Issues: GitHub Issues
- Documentation: See README.md
- Questions: Open a discussion

---

**Built with ❤️ for reliable production systems**
