# Quantamental Swing Trading Terminal

🔗 **[Live Terminal](https://quantamental-swing-trading-private.vercel.app/)**

![Python](https://img.shields.io/badge/python-3.13-blue.svg)
![Next.js](https://img.shields.io/badge/Next.js-16.2-black.svg)
![GCP](https://img.shields.io/badge/Google%20Cloud-BigQuery%20%7C%20Cloud%20Run-1a73e8.svg)

An end-to-end algorithmic and discretionary trading ecosystem that fuses quantitative machine learning models with fundamental data scraping. It consists of an automated Python-based data collection and ML pipeline deployed on Google Cloud Platform (GCP) and a modern Next.js dashboard deployed on Vercel.

---

## 📖 Table of Contents
- [Project Overview](#project-overview)
- [Architecture & Tech Stack](#architecture--tech-stack)
- [Data Collection & ML Pipeline](#data-collection--ml-pipeline)
- [Frontend Terminal](#frontend-terminal)
- [Cloud Deployment (GCP & Vercel)](#cloud-deployment-gcp--vercel)
- [Setup & Installation](#setup--installation)

---

## 🎯 Project Overview

This repository houses two primary systems:
1. **The Engine (Backend):** A 7-stage Python pipeline that fetches live stock data from the NSE/BSE, scrapes deep fundamental metrics from financial portals, cleans the data, trains predictive Machine Learning models on weekends, and generates daily swing trading predictions.
2. **The Terminal (Frontend):** A Next.js web application that connects directly to the resulting BigQuery datasets to provide an interactive dashboard, a real-time fundamental screener, and user-authenticated watchlists.

---

## ⚙️ Architecture & Tech Stack

### Data Pipeline & Machine Learning
* **Language:** Python 3.13
* **Libraries:** `pandas`, `requests`, `beautifulsoup4`, `scikit-learn`
* **Data Storage:** Google Cloud BigQuery 
* **Orchestration:** Custom Python `orchestrator.py`

### Frontend Application
* **Framework:** Next.js (App Router, Server Components)
* **Language:** TypeScript
* **Styling:** CSS Modules / Vanilla CSS
* **Authentication:** NextAuth.js
* **Database Client:** `@google-cloud/bigquery` (Serverless API Routes)

### Infrastructure & DevOps
* **GCP:** Cloud Run Jobs, Cloud Build, Artifact Registry, Cloud Scheduler, Cloud Logging
* **Vercel:** Edge Network Web Hosting

---

## 📊 Data Collection & ML Pipeline

The data ingestion pipeline is managed by `orchestrator.py`, which sequences the following scripts. The orchestrator automatically detects the day of the week to execute the correct profile (daily predictions vs. weekly model retraining).

1. **`1_fetch_stocks.py`**: Fetches the master list of equities directly from the NSE and BSE APIs. Cleans the data to ensure only pure corporate stocks (filtering out ETFs, etc.) are kept and initializes the BigQuery `stocks.all_listed_stocks` table.
2. **`2_fetch_indices.py`**: Gathers broader market index data to be used as macroeconomic features for the ML model.
3. **`3_fetch_technicals.py`**: Downloads historical price and volume data, calculating technical indicators (Moving Averages, RSI, MACD).
4. **`4_fetch_fundamentals.py`**: A highly resilient web scraper fetching fundamentals data from various sources. It pulls down detailed P&L, Balance Sheets, Cash Flows, and Ratios. Features include:
   * **Smart Resumption:** Checks the latest available quarter in BigQuery to avoid redundant scraping.
   * **Dynamic Schemas:** Uses BigQuery's `ALLOW_FIELD_ADDITION` to automatically map new fundamental column headers (e.g., Bank-specific metrics) into the database on the fly.
5. **`5_fetch_and_clean_earnings.py`**: Normalizes and structures quarterly earnings data into standardized ML features.
6. **`6_model_train.py`**: (Runs exclusively on Saturdays). Fetches the aggregated dataset from BigQuery, performs feature engineering, and trains the machine learning models using expanding window validation (train on t=1 to t=k, validate on t=k+1, train on t=1 to t=k+1, validate on t=k+2, and so on..).
7. **`7_model_prediction.py`**: Retrains the model on whole data using the tuned hyperparameters so as to preserve the recency of data and predicting the maximum possible upside, drawdown and average price until the next earnings date

All pipeline executions, including durations, success/failure statuses, and error tracebacks, are persistently logged to a BigQuery table (`pipeline.execution_log`).

---

## 💻 Frontend Terminal

The Next.js frontend (`/frontend`) acts as the user interface for the trading strategy. 

* **Dashboard (`/dashboard`):** Displays the latest ML predictions, risk flags, and potential upside.
* **Screener (`/screener`):** A dynamic query engine allowing users to filter the entire Indian stock market based on the fundamental data collected in step 4 (e.g., P/E Ratios, Market Cap, Debt-to-Equity).
* **Watchlists (`/watchlist`):** Users can authenticate and maintain multiple custom watchlists. Watchlist states are synchronized directly with BigQuery.
* **Monitor (`/monitor`):** Reads the orchestrator logs from BigQuery to display the real-time health and execution status of the background GCP pipeline.

---

## ☁️ Cloud Deployment (GCP & Vercel)

The project leverages a fully serverless cloud architecture.

### 1. GCP Pipeline Deployment
The Python pipeline is containerized and runs on Google Cloud Run Jobs, orchestrated by Cloud Scheduler.

* **Dockerization:** A multi-stage `Dockerfile` is used to keep the runtime image lean. It installs compilation dependencies in the builder stage, but only copies the required binaries and python scripts to the final runtime image.
* **CI/CD (Cloud Build):** The `cloudbuild.yaml` file defines the continuous deployment process:
  1. Builds the Docker image.
  2. Pushes the image to **Artifact Registry** (`asia-south1-docker.pkg.dev`).
  3. Automatically cleans up old, untagged images to optimize storage costs.
  4. Updates the **Cloud Run Job** (`quantamental-daily`) with the newly built `:latest` image.
* **Scheduling:** Google Cloud Scheduler triggers the Cloud Run Job.
  * **Tue-Fri (8:30 IST):** Runs the `daily` profile (Prediction generation).
  * **Saturday (8:30 IST):** Runs the `saturday` profile (Model training + Prediction generation).

### 2. Vercel Frontend Deployment
The `frontend` directory is deployed to Vercel.
* **Root Directory:** Configured to `/frontend` in Vercel settings.
* **API Routing:** Next.js API Routes (`/api/...`) securely utilize the GCP Service Account JSON securely stored as a Vercel Environment Variable to query BigQuery on-demand.
* **Region Mapping:** The BigQuery datasets (e.g., `user_data`, `pipeline`, `stocks`) are strictly localized to `asia-south1` to ensure rapid cross-table queries without data-location mismatch errors.

---

## 🛠️ Setup & Installation

**⚠️ Note on Proprietary Features:** 
We have made the training methodology public with redacted features, so you will only be able to clone those structural files (e.g., `6_model_train_public.py`). 

The full local backend and frontend setup instructions have been removed as this is a private, active algorithmic trading strategy.
