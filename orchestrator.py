"""
Pipeline Orchestrator — Runs all scripts in sequence and logs results to BigQuery.

Schedule:
  - Tue–Fri (8:30 IST): Scripts 1,2,3,4,5,7
  - Saturday (8:30 IST): Scripts 1,2,3,4,5,6,7

Usage:
  python orchestrator.py                    # Auto-detect day (daily or saturday)
  python orchestrator.py --profile full     # Force all 7 scripts
  python orchestrator.py --profile train    # Run only script 6
  python orchestrator.py --script 3         # Run a single script by number
"""

import subprocess
import sys
import os
import uuid
import time
import argparse
from datetime import datetime

import pytz
import pandas as pd
from google.cloud import bigquery
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

GCP_PROJECT_ID = "adk-mini-project"
BQ_DATASET = "pipeline"
BQ_LOG_TABLE = f"{GCP_PROJECT_ID}.{BQ_DATASET}.execution_log"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IST = pytz.timezone("Asia/Kolkata")

# Script execution timeout (2 hours per script)
SCRIPT_TIMEOUT = 7200

# --- SCRIPT PROFILES ---
ALL_SCRIPTS = [
    "1_fetch_stocks.py",
    "2_fetch_indices.py",
    "3_fetch_technicals.py",
    "4_fetch_fundamentals.py",
    "5_fetch_and_clean_earnings.py",
    "6_model_train.py",
    "7_model_prediction.py",
]


def get_scripts_for_today():
    """Determines which scripts to run based on the current day (IST)."""
    today = datetime.now(IST)
    is_saturday = today.weekday() == 5

    scripts = [
        "1_fetch_stocks.py",
        "2_fetch_indices.py",
        "3_fetch_technicals.py",
        "4_fetch_fundamentals.py",
        "5_fetch_and_clean_earnings.py",
    ]

    if is_saturday:
        scripts.append("6_model_train.py")

    scripts.append("7_model_prediction.py")

    profile = "saturday" if is_saturday else "daily"
    return scripts, profile


def get_profile_scripts(profile):
    """Returns scripts for a given profile name."""
    if profile == "auto":
        return get_scripts_for_today()
    elif profile == "daily":
        return [s for s in ALL_SCRIPTS if s != "6_model_train.py"], "daily"
    elif profile == "saturday":
        return ALL_SCRIPTS[:], "saturday"
    elif profile == "full":
        return ALL_SCRIPTS[:], "full"
    elif profile == "train":
        return ["6_model_train.py"], "train"
    else:
        raise ValueError(f"Unknown profile: {profile}")


# --- BIGQUERY LOGGING ---

def ensure_log_table(client):
    """Creates the pipeline dataset and execution_log table if they don't exist."""
    # Ensure dataset
    dataset_ref = bigquery.Dataset(f"{GCP_PROJECT_ID}.{BQ_DATASET}")
    dataset_ref.location = "asia-south1"
    client.create_dataset(dataset_ref, exists_ok=True)

    # Ensure table
    client.query(f"""
        CREATE TABLE IF NOT EXISTS `{BQ_LOG_TABLE}` (
            run_id STRING,
            run_date DATE,
            run_timestamp TIMESTAMP,
            profile STRING,
            script_name STRING,
            script_order INT64,
            status STRING,
            exit_code INT64,
            duration_seconds FLOAT64,
            stdout_tail STRING,
            error_message STRING,
            triggered_by STRING
        )
    """).result()


def push_logs_to_bq(client, log_records):
    """Pushes execution log records to BigQuery."""
    if not log_records:
        return

    df = pd.DataFrame(log_records)

    # Ensure timestamp column is timezone-aware for BigQuery
    df["run_timestamp"] = pd.to_datetime(df["run_timestamp"], utc=True)

    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_APPEND",
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )

    try:
        job = client.load_table_from_dataframe(df, BQ_LOG_TABLE, job_config=job_config)
        job.result()
        print(f"\n📋 Logged {len(log_records)} execution records to {BQ_LOG_TABLE}")
    except Exception as e:
        print(f"\n❌ Failed to push logs to BigQuery: {e}")
        # Fallback: print logs to stdout (captured by Cloud Logging)
        for record in log_records:
            print(f"  LOG: {record}")


# --- SCRIPT RUNNER ---

def run_single_script(script, script_dir, timeout=SCRIPT_TIMEOUT):
    """
    Runs a single script as a subprocess.
    - stdout is forwarded to parent (visible in Cloud Run logs in real-time)
    - stderr is captured for error logging to BigQuery
    Returns: (exit_code, stderr_output, timed_out)
    """
    try:
        result = subprocess.run(
            [sys.executable, "-u", os.path.join(script_dir, script)],
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=script_dir,
        )
        return result.returncode, result.stderr or "", False

    except subprocess.TimeoutExpired:
        return -1, f"Script timed out after {timeout} seconds", True

    except Exception as e:
        return -1, str(e), False


# --- MAIN PIPELINE ---

def run_pipeline(profile="auto", single_script=None):
    """Executes the pipeline and logs results to BigQuery."""
    run_id = str(uuid.uuid4())
    now = datetime.now(IST)

    # Determine scripts to run
    if single_script:
        # Find script by number: --script 3 → "3_fetch_technicals.py"
        matching = [s for s in ALL_SCRIPTS if s.startswith(f"{single_script}_")]
        if not matching:
            print(f"❌ No script found matching number: {single_script}")
            sys.exit(1)
        scripts = matching
        profile_name = "manual"
    else:
        scripts, profile_name = get_profile_scripts(profile)

    triggered_by = "scheduler" if os.environ.get("CLOUD_RUN_JOB") else "manual"

    print("=" * 70)
    print(f"🚀 QUANTAMENTAL PIPELINE ORCHESTRATOR")
    print(f"   Run ID:      {run_id}")
    print(f"   Profile:     {profile_name}")
    print(f"   Triggered:   {triggered_by}")
    print(f"   Timestamp:   {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"   Scripts:     {len(scripts)} to execute")
    print("=" * 70)

    # Initialize BigQuery logging
    bq_client = None
    try:
        bq_client = bigquery.Client(project=GCP_PROJECT_ID)
        ensure_log_table(bq_client)
    except Exception as e:
        print(f"⚠️ Could not initialize BigQuery logging: {e}")
        print("   Pipeline will continue, but logs won't be saved to BigQuery.")

    log_records = []
    total_start = time.time()
    failed_scripts = []

    for order, script in enumerate(scripts, 1):
        print(f"\n{'─' * 70}")
        print(f"▶ [{order}/{len(scripts)}] {script}")
        print(f"{'─' * 70}\n")

        start_time = time.time()
        exit_code, stderr_output, timed_out = run_single_script(script, SCRIPT_DIR)
        duration = time.time() - start_time

        # Determine status
        if timed_out:
            status = "TIMEOUT"
        elif exit_code == 0:
            status = "SUCCESS"
        else:
            status = "FAILED"

        # Build log record
        log_records.append({
            "run_id": run_id,
            "run_date": now.date(),
            "run_timestamp": now.isoformat(),
            "profile": profile_name,
            "script_name": script,
            "script_order": order,
            "status": status,
            "exit_code": exit_code,
            "duration_seconds": round(duration, 2),
            "stdout_tail": "",  # stdout goes directly to Cloud Logging
            "error_message": stderr_output[-2000:] if stderr_output else "",
            "triggered_by": triggered_by,
        })

        # Print status
        if status == "SUCCESS":
            print(f"\n✅ {script} — completed in {duration:.1f}s")
        elif status == "TIMEOUT":
            print(f"\n⏰ {script} — TIMED OUT after {duration:.1f}s")
            failed_scripts.append(script)
        else:
            print(f"\n❌ {script} — FAILED (exit code: {exit_code}) in {duration:.1f}s")
            if stderr_output:
                print(f"   Error: {stderr_output[-500:]}")
            failed_scripts.append(script)

        # Continue to next script regardless of failure

    # --- PUSH LOGS TO BIGQUERY ---
    total_duration = time.time() - total_start
    if bq_client:
        push_logs_to_bq(bq_client, log_records)

    # --- SUMMARY ---
    print(f"\n{'=' * 70}")
    print(f"📊 PIPELINE SUMMARY")
    print(f"   Total Duration: {total_duration:.1f}s ({total_duration / 60:.1f} min)")
    print(f"   Succeeded:      {len(scripts) - len(failed_scripts)}/{len(scripts)}")
    if failed_scripts:
        print(f"   ❌ Failed:      {', '.join(failed_scripts)}")
    else:
        print(f"   🎉 All scripts completed successfully!")
    print(f"{'=' * 70}")

    # Exit with error code if any script failed
    if failed_scripts:
        sys.exit(1)


# --- CLI ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quantamental Pipeline Orchestrator")
    parser.add_argument(
        "--profile",
        choices=["auto", "daily", "saturday", "full", "train"],
        default="auto",
        help="Script profile to run (default: auto-detect based on day)",
    )
    parser.add_argument(
        "--script",
        type=int,
        help="Run a single script by number (e.g., --script 3)",
    )
    args = parser.parse_args()

    run_pipeline(profile=args.profile, single_script=args.script)
