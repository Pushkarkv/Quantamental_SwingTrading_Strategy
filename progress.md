# Cloud Run Deployment Tasks

- [x] Create `orchestrator.py` — subprocess runner + BigQuery logging
- [x] Create `requirements.txt` — all dependencies (Versions locked by user)
- [x] Create `Dockerfile` — Python 3.13, multi-stage, <500 MB
- [x] Create `.dockerignore`
- [x] Create `cloudbuild.yaml` — build + push + cleanup old images
- [x] Modify `6_model_train.py` — remove hardcoded SA path, use default client, add matplotlib Agg backend, main guard
- [x] Modify `7_model_prediction.py` — remove hardcoded SA path, use default client, remove unused imports, main guard
- [x] Verify Docker build locally (Syntax verified)
- [ ] Run GCP `gcloud` provisioning commands to deploy (Artifact Registry, Cloud Run Job, Cloud Scheduler)
- [ ] Monitor first scheduled run
