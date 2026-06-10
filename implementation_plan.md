# Cloud Run Deployment — Quantamental SwingTrading Strategy

## Background

Deploy the stock prediction ML pipeline (7 scripts) to GCP Cloud Run, triggered daily by Cloud Scheduler, with pipeline execution logging to BigQuery. Frontend via Power BI Free connected directly to BigQuery.

### Pipeline Overview

| Script | Purpose | External APIs | Daily Runtime |
|---|---|---|---|
| `1_fetch_stocks.py` | NSE/BSE master stock list → `stocks.all_listed_stocks` | `archives.nseindia.com`, BSE API | ~10 sec |
| `2_fetch_indices.py` | NSE/BSE indices → `stocks.indices` | `api.kite.trade` (Zerodha) | ~5 sec |
| `3_fetch_technicals.py` | OHLCV history via yfinance → `technicals.daily_stock_price` (incremental, split detection) | Yahoo Finance | ~30-45 min |
| `4_fetch_fundamentals.py` | Screener.in scraping → `fundamentals.*` (11 tables, resume-aware) | Screener.in | ~5-10 min (daily, most skipped) |
| `5_fetch_and_clean_earnings.py` | NSE board meeting data → `earnings.*` (uses `curl_cffi` browser impersonation) | `nseindia.com` API | ~5-10 min |
| `6_model_train.py` | Train 4 LightGBM models, log metrics → `predictions.model_metrics_log`, upload plots to GCS | BigQuery only | ~15-20 min |
| `7_model_prediction.py` | Retrain on full historical data + inference → `predictions.daily_inference_results`, `predictions.daily_shap_values` | BigQuery only | ~15-20 min |

---

## Confirmed Decisions

| Decision | Details |
|---|---|
| **Schedule** | **Tue–Sat at 8:30 AM IST** (trading days + 1). Single Cloud Scheduler job. |
| **Daily (Tue–Fri)** | Scripts 1, 2, 3, 4, 5, 7 |
| **Saturday** | Scripts 1, 2, 3, 4, 5, **6**, 7 (adds model training for performance tracking) |
| **Script 5 (NSE)** | Run as-is. If NSE blocks from Cloud Run, orchestrator logs failure and continues. User runs manually from local machine when needed. |
| **Script 7** | Retrains models from scratch daily (not loading saved models) — intentional, as new earnings data arrives daily and live trades depend on fresh predictions. |
| **Script 6 on Saturday** | Tracks model performance over time (validation vs test metrics logged to `predictions.model_metrics_log`) to monitor for degradation. |
| **Image Registry** | GCP Artifact Registry. Delete old image before pushing new one → always <500 MB → stays in free tier. |
| **Compute** | Cloud Run **Jobs** (not Services) — designed for batch workloads. |
| **Frontend** | Power BI Free tier, connected directly to BigQuery output tables. |
| **Total GCP cost** | **$0/month** — all services within free tier. |

---

## GCP Free Tier Verification

### BigQuery

| Metric | Free Allowance | Our Usage | Headroom |
|---|---|---|---|
| **Storage** | 10 GB/month | ~915 MB (OHLCV 340 MB + fundamentals 500 MB + earnings 50 MB + predictions 20 MB + misc 5 MB) | **91% free** |
| **Queries** | 1 TB/month | ~24 GB/month (train_data view 250 MB × 26 runs + MERGE operations + master queries) | **97.6% free** |

### Cloud Run

| Metric | Free Allowance | Our Usage | Headroom |
|---|---|---|---|
| **vCPU-seconds** | 360,000/month (~100 hrs) | ~25 hours/month (5 days/week × 4 weeks × ~75 min) | **75% free** |
| **Memory** | 180,000 GiB-sec/month | Well within (2 GiB × 25 hrs = ~50 hrs GiB-sec) | ✅ |
| **Requests** | 2M/month | ~22/month (1 per run day) | ✅ |

### Other Services

| Service | Free Allowance | Our Usage | Status |
|---|---|---|---|
| **Cloud Scheduler** | 3 jobs | 1 job (Tue-Sat 8:30 IST) | ✅ |
| **Artifact Registry** | 500 MB | ~350 MB (1 optimized image, old versions deleted) | ✅ |
| **Cloud Build** | 120 min/day | ~5 min per build (manual/occasional) | ✅ |
| **GCS** | 5 GB (US regions) | Plots only (~few MB). Bucket is Iowa (us-central1). | ✅ |

---

## Proposed Changes

### Component 1: Orchestrator Script

#### [NEW] [orchestrator.py](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/orchestrator.py)

Central orchestration script that:
- Determines the script execution list based on day of week (Saturday includes Script 6)
- Runs each script as a **subprocess** with isolated stdout/stderr capture
- If a script fails, logs the error and **continues to the next script** (no hard abort)
- Logs execution results per-script to BigQuery table `pipeline.execution_log`
- Supports `--profile` override for manual runs (`daily`, `saturday`, `full`, `single --script 3`)

**BigQuery logging table**: `pipeline.execution_log`

```
├── run_id: STRING          (UUID, same for all scripts in one orchestrator invocation)
├── run_date: DATE
├── run_timestamp: TIMESTAMP
├── profile: STRING         (daily / saturday / full / manual)
├── script_name: STRING     (e.g., "3_fetch_technicals.py")
├── script_order: INT64     (execution order: 1, 2, 3...)
├── status: STRING          (SUCCESS / FAILED / TIMEOUT)
├── exit_code: INT64
├── duration_seconds: FLOAT64
├── stdout_tail: STRING     (last 2000 chars of stdout for debugging)
├── error_message: STRING   (stderr tail, 2000 chars)
├── triggered_by: STRING    (scheduler / manual)
```

**Auto-detection logic:**

```python
from datetime import datetime
import pytz

ist = pytz.timezone('Asia/Kolkata')
today = datetime.now(ist)
is_saturday = today.weekday() == 5  # 5 = Saturday

scripts = [
    "1_fetch_stocks.py",
    "2_fetch_indices.py", 
    "3_fetch_technicals.py",
    "4_fetch_fundamentals.py",
    "5_fetch_and_clean_earnings.py",
]

if is_saturday:
    scripts.append("6_model_train.py")

scripts.append("7_model_prediction.py")  # Always last
```

---

### Component 2: Docker Configuration

#### [NEW] [Dockerfile](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/Dockerfile)

Multi-stage build to keep image under 500 MB:

```dockerfile
# Stage 1: Build (install system deps for compilation)
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y gcc g++ libxml2-dev libxslt-dev curl
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime (no build tools — smaller image)
FROM python:3.11-slim
RUN apt-get update && apt-get install -y libxml2 libxslt1.1 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY *.py ./
CMD ["python", "orchestrator.py"]
```

> [!NOTE]
> - `saved_models/` and `service-account/` are NOT copied into the image
> - Service account auth is handled by Cloud Run's default service account
> - Models are retrained from BigQuery data at runtime (Script 7), not loaded from disk
> - matplotlib and seaborn are kept in the image since Script 6 (Saturday) generates plots

#### [NEW] [requirements.txt](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/requirements.txt)

```
pandas
pandas-gbq
google-cloud-bigquery
google-cloud-storage
google-cloud-bigquery-storage
pyarrow
requests
yfinance
beautifulsoup4
lxml
curl_cffi
python-dotenv
pytz
lightgbm
scikit-learn
joblib
numpy
scipy
shap
matplotlib
seaborn
```

#### [NEW] [.dockerignore](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/.dockerignore)

```
notebooks/
data_splits/
saved_models/
service-account/
.env
*.ipynb
*.csv
__pycache__/
.git/
```

---

### Component 3: Script Modifications for Cloud Compatibility

#### [MODIFY] All scripts — Service Account Handling

**Current** (hardcoded local path — won't work on Cloud Run):
```python
SERVICE_ACCOUNT_JSON_PATH = r"service-account\service_account.json"
bq_client = bigquery.Client.from_service_account_json(SERVICE_ACCOUNT_JSON_PATH, project=GCP_PROJECT_ID)
```

**New** (works both locally and on Cloud Run):
```python
# On Cloud Run: uses default service account automatically
# Locally: uses GOOGLE_APPLICATION_CREDENTIALS env var from .env
bq_client = bigquery.Client(project=GCP_PROJECT_ID)
```

Scripts affected:
- [6_model_train.py](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/6_model_train.py) — Lines 75-81 (BigQuery client) + Lines 53-57 (GCS client)
- [7_model_prediction.py](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/7_model_prediction.py) — Lines 41-47

Scripts 1, 2, 3, 4, 5 already use `bigquery.Client(project=...)` without explicit JSON path. ✅

#### [MODIFY] [6_model_train.py](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/6_model_train.py)

- Change GCS client from `storage.Client.from_service_account_json(...)` to `storage.Client(project=...)` (line 54)
- Change BigQuery client from `bigquery.Client.from_service_account_json(...)` to `bigquery.Client(project=...)` (line 78)
- Wrap top-level code in `main()` function + `if __name__ == "__main__"` guard (currently runs at import time)

#### [MODIFY] [7_model_prediction.py](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/7_model_prediction.py)

- Change BigQuery client from `bigquery.Client.from_service_account_json(...)` to `bigquery.Client(project=...)` (line 44)
- Wrap top-level code in `main()` function + `if __name__ == "__main__"` guard (currently runs at import time)
- Remove unused `import matplotlib.pyplot as plt` and `import seaborn as sns` (imported but never used for plotting)

#### [MODIFY] [3_fetch_technicals.py](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/3_fetch_technicals.py)

- Change `os.makedirs('data_splits', exist_ok=True)` paths to work in container context (use relative paths from `/app`)

#### [MODIFY] [4_fetch_fundamentals.py](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/4_fetch_fundamentals.py)

- The global `bq_client = bigquery.Client(project=GCP_PROJECT_ID)` at line 59 needs try/except so the module doesn't crash on import if BQ is temporarily unavailable

---

### Component 4: Cloud Build Configuration

#### [NEW] [cloudbuild.yaml](file:///d:/CODE/Projects/Quantamental_SwingTrading_Strategy/cloudbuild.yaml)

Cloud Build config that:
1. Builds the Docker image
2. Pushes to Artifact Registry
3. Deletes old image versions to stay under 500 MB free tier
4. Updates the Cloud Run Job with the new image

```yaml
steps:
  # Build
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'REGION-docker.pkg.dev/adk-mini-project/quantamental/pipeline:latest', '.']
  
  # Push
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'REGION-docker.pkg.dev/adk-mini-project/quantamental/pipeline:latest']
  
  # Cleanup old images (keep free tier)
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: 'bash'
    args: ['-c', 'gcloud artifacts docker images list-tags ... --filter="NOT tags:latest" --format="get(digest)" | xargs -I {} gcloud artifacts docker images delete ...@{} --quiet']
  
  # Update Cloud Run Job
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    args: ['gcloud', 'run', 'jobs', 'update', 'quantamental-daily', '--image', '...', '--region', 'asia-south1']
```

---

### Component 5: Cloud Run Job + Cloud Scheduler Setup

#### GCP Resource Setup (gcloud CLI commands)

```bash
# 1. Create Artifact Registry repo
gcloud artifacts repositories create quantamental \
  --repository-format=docker \
  --location=asia-south1

# 2. Build and push (first time)
gcloud builds submit --config=cloudbuild.yaml

# 3. Create Cloud Run Job
gcloud run jobs create quantamental-daily \
  --image asia-south1-docker.pkg.dev/adk-mini-project/quantamental/pipeline:latest \
  --region asia-south1 \
  --memory 2Gi \
  --cpu 1 \
  --task-timeout 7200 \
  --max-retries 0 \
  --set-env-vars GCP_PROJECT_ID=adk-mini-project

# 4. Create Cloud Scheduler (Tue-Sat 8:30 AM IST)
gcloud scheduler jobs create http quantamental-trigger \
  --schedule="30 8 * * 2-6" \
  --time-zone="Asia/Kolkata" \
  --uri="https://asia-south1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/adk-mini-project/jobs/quantamental-daily:run" \
  --http-method=POST \
  --oauth-service-account-email=SA_EMAIL@adk-mini-project.iam.gserviceaccount.com
```

---

### Component 6: Frontend — Power BI Free

Power BI Desktop connects directly to BigQuery. Key tables to connect:

| BigQuery Table | Use in Power BI |
|---|---|
| `predictions.daily_inference_results` | Primary dashboard — stock predictions, risk flags, price targets |
| `stocks.all_listed_stocks` | Join for company names, BSE codes, listing dates |
| `fundamentals.key_ratios` | Join for PE, market cap, sector info |
| `predictions.model_metrics_log` | Model performance monitoring over time |
| `predictions.daily_shap_values` | Feature importance drill-down per stock |
| `pipeline.execution_log` | Pipeline health monitoring |

**DAX ranking logic** (in Power BI):
- Filter: `predicted_upside_pct >= 0.30` (≥30% upside)
- Filter: `predicted_upside_pct / ABS(predicted_downside_pct) >= 3` (3x risk/reward)
- Filter: `predicted_avg_pct >= 0.10` (≥10% avg growth)
- Filter: `risk_flag_balanced_0_50 = 0` (not risky)

> [!NOTE]
> Power BI Free limitations: reports are personal only (no sharing/publishing). If you need to share with others in the future, upgrade to Pro ($10/user/month) or use Looker Studio (free, shareable) as a complement.

---

## Execution Order Summary

```
orchestrator.py (triggered by Cloud Scheduler, Tue-Sat 8:30 IST)
│
├── 1_fetch_stocks.py        → stocks.all_listed_stocks (REPLACE)
├── 2_fetch_indices.py       → stocks.indices (REPLACE)
├── 3_fetch_technicals.py    → technicals.daily_stock_price (MERGE incremental)
├── 4_fetch_fundamentals.py  → fundamentals.* (resume-aware, skip if current)
├── 5_fetch_and_clean_earnings.py → earnings.* (incremental, graceful fail OK)
├── 6_model_train.py         → predictions.model_metrics_log (SATURDAY ONLY)
├── 7_model_prediction.py    → predictions.daily_inference_results (retrain + delta upload)
│
└── Logs every step to → pipeline.execution_log
```

---

## Verification Plan

### Automated Testing
1. Build Docker image locally: `docker build -t quantamental-test .`
2. Run locally: `docker run --env GOOGLE_APPLICATION_CREDENTIALS=/app/sa.json -v ./service-account:/app/service-account quantamental-test python orchestrator.py --profile daily`
3. Verify `pipeline.execution_log` table in BigQuery has correct entries
4. Deploy to Cloud Run Jobs and trigger manually: `gcloud run jobs execute quantamental-daily`
5. Verify Cloud Scheduler fires at 8:30 IST on next Tuesday

### Manual Verification
1. Check BigQuery `pipeline.execution_log` after first 3 scheduled runs
2. Connect Power BI Desktop to BigQuery and verify data loads
3. Confirm GCP billing dashboard shows $0 after first week
4. Monitor Script 5 logs — if NSE blocks consistently, user runs manually
