import os
import time
import pandas as pd
from datetime import datetime, timedelta
from curl_cffi import requests
from google.cloud import bigquery
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
GCP_PROJECT_ID = "adk-mini-project"
BQ_MASTER_STOCKS_TABLE = "adk-mini-project.stocks.all_listed_stocks"
BQ_DATASET = "earnings"
BQ_RAW_TABLE = f"{GCP_PROJECT_ID}.{BQ_DATASET}.historical_earnings_raw"
BQ_CLEANED_TABLE = f"{GCP_PROJECT_ID}.{BQ_DATASET}.historical_earnings_cleaned"

def get_master_companies():
    print("Fetching master company list from BigQuery...")
    try:
        client = bigquery.Client(project=GCP_PROJECT_ID)
        query = f"SELECT * FROM `{BQ_MASTER_STOCKS_TABLE}` WHERE nse_symbol IS NOT NULL"
        df = client.query(query).to_dataframe()
        
        # Try to find company name column
        name_col = None
        for col in ['company_name', 'name', 'security_name']:
            if col in df.columns:
                name_col = col
                break
                
        if name_col:
            return df[['nse_symbol', name_col]].rename(columns={name_col: 'company_name'})
        else:
            df['company_name'] = df['nse_symbol'] # fallback
            return df[['nse_symbol', 'company_name']]
    except Exception as e:
        print(f"Error fetching from BigQuery: {e}")
        return pd.DataFrame(columns=['nse_symbol', 'company_name'])

def ensure_bq_dataset_exists(client):
    dataset_id = f"{GCP_PROJECT_ID}.{BQ_DATASET}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = "asia-south1"
    dataset = client.create_dataset(dataset, exists_ok=True)
    dataset.default_partition_expiration_ms = None
    client.update_dataset(dataset, ["default_partition_expiration_ms"])

def push_to_bigquery(raw_df, cleaned_df):
    print("Pushing data to BigQuery...")
    try:
        client = bigquery.Client(project=GCP_PROJECT_ID)
        ensure_bq_dataset_exists(client)
        
        # --- 1. Push Raw Data (Unchanged) ---
        if raw_df is not None and not raw_df.empty:
            raw_copy = raw_df.copy()
            # Convert objects to string to avoid BQ type inference errors on mixed columns
            for col in raw_copy.columns:
                if raw_copy[col].dtype == 'object':
                    raw_copy[col] = raw_copy[col].astype(str)
                    
            job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
            job = client.load_table_from_dataframe(raw_copy, BQ_RAW_TABLE, job_config=job_config)
            job.result()
            print(f"--> Pushed {len(raw_copy)} rows to {BQ_RAW_TABLE}")
            
        # --- 2. Push Cleaned Data (With Explicit Schema Enforcement) ---
        if cleaned_df is not None and not cleaned_df.empty:
            cleaned_copy = cleaned_df.copy()
            
            # Explicitly define the schema to enforce DATE types
            job_config = bigquery.LoadJobConfig(
                write_disposition="WRITE_TRUNCATE",
                schema=[
                    bigquery.SchemaField("nse_symbol", "STRING"),
                    bigquery.SchemaField("company_name", "STRING"),
                    bigquery.SchemaField("result_release_date", "DATE"),
                    bigquery.SchemaField("result_release_for_quarter", "STRING"),
                    bigquery.SchemaField("source", "STRING"),
                    bigquery.SchemaField("last_updated_date", "DATE"),
                ]
            )
            
            job = client.load_table_from_dataframe(cleaned_copy, BQ_CLEANED_TABLE, job_config=job_config)
            job.result()
            print(f"--> Pushed {len(cleaned_copy)} rows to {BQ_CLEANED_TABLE}")
            
    except Exception as e:
        print(f"Error pushing to BigQuery: {e}")

def fetch_raw_data():
    print("Initializing Chrome session for NSE...")
    session = requests.Session(impersonate="chrome")

    base_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    print("Warming up session cookies from the NSE homepage...")
    try:
        home_response = session.get("https://www.nseindia.com/", headers=base_headers, timeout=15)
        if home_response.status_code != 200:
            print("Failed to access NSE homepage. Exiting.")
            return None
    except Exception as e:
        print(f"Error connecting to base URL: {e}")
        return None

    time.sleep(2) 

    api_headers = base_headers.copy()
    api_headers.update({
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-board-meetings"
    })

    # Determine start date by querying BigQuery
    print(f"Checking BigQuery {BQ_RAW_TABLE} for incremental start date...")
    existing_df = None
    try:
        client = bigquery.Client(project=GCP_PROJECT_ID)
        query = f"SELECT * FROM `{BQ_RAW_TABLE}`"
        existing_df = client.query(query).to_dataframe()
        
        if not existing_df.empty and 'bm_date' in existing_df.columns:
            existing_df['parsed_date'] = pd.to_datetime(existing_df['bm_date'], errors='coerce')
            max_date = existing_df['parsed_date'].max()
            if pd.isna(max_date):
                start_date = datetime(2015, 1, 1)
            else:
                start_date = max_date - pd.DateOffset(months=2)
                # Drop the temporary parsed_date column
                existing_df = existing_df.drop(columns=['parsed_date'])
        else:
            start_date = datetime(2015, 1, 1)
    except Exception as e:
        print(f"Table not found or error reading from BQ (This is normal for first run): {e}")
        start_date = datetime(2015, 1, 1)

    end_date = datetime.now()
    if start_date >= end_date:
        print("Data is already up to date. Re-fetching last 10 days just in case.")
        start_date = end_date - timedelta(days=10)
    
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    current_start = start_date
    step_days = 90 
    
    print(f"Starting extraction from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}...")

    new_records = []

    while current_start < end_date:
        current_end = current_start + timedelta(days=step_days)
        if current_end > end_date:
            current_end = end_date
            
        str_start = current_start.strftime("%d-%m-%Y") 
        str_end = current_end.strftime("%d-%m-%Y")
        
        print(f"Fetching chunk: {str_start} to {str_end}...")
        
        api_url = f"https://www.nseindia.com/api/corporate-board-meetings?index=equities&from_date={str_start}&to_date={str_end}"
        
        retries = 5
        for attempt in range(retries):
            try:
                api_response = session.get(api_url, headers=api_headers, timeout=20)
                
                if api_response.status_code == 200:
                    data = api_response.json()
                    records = data if isinstance(data, list) else data.get('data', [])
                    
                    if records:
                        df = pd.DataFrame(records)
                        
                        if 'purpose' in df.columns:
                            df = df[df['purpose'].astype(str).str.contains('Result|Financial', case=False, na=False)]
                        
                        if not df.empty:
                            new_records.append(df)
                            print(f"--> Found {len(df)} earnings records.")
                        else:
                            print("--> No earnings records found in this chunk.")
                    else:
                        print("--> No data returned for this period.")
                    break # Success, break out of retry loop
                else:
                    print(f"--> Failed chunk (Attempt {attempt+1}/{retries}). Status: {api_response.status_code}")
                    if api_response.status_code in [401, 403]:
                        print("Session expired. Attempting to re-warm cookies...")
                        session.get("https://www.nseindia.com/", headers=base_headers, timeout=15)
                    time.sleep(3) # Wait before retry
                    
            except Exception as e:
                print(f"--> Error fetching chunk (Attempt {attempt+1}/{retries}): {e}")
                time.sleep(3) # Wait before retry
            
        time.sleep(3)
        current_start = current_end + timedelta(days=1)

    if new_records:
        new_df = pd.concat(new_records, ignore_index=True)
        if existing_df is not None and not existing_df.empty:
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            # drop duplicates based on symbol, date, and purpose
            combined_df = combined_df.drop_duplicates(subset=['bm_symbol', 'bm_date', 'bm_purpose'])
        else:
            combined_df = new_df
            
        print(f"Total compiled records: {len(combined_df)}.")
        return combined_df
    else:
        print("No new records fetched.")
        if existing_df is not None and not existing_df.empty:
            return existing_df
        return pd.DataFrame()

def generate_cleaned_data(raw_df, master_df):
    print("Cleaning and generating quarter-level data...")
    if raw_df.empty:
        print("Raw data is empty. Nothing to clean.")
        return
        
    raw_df = raw_df[raw_df['bm_purpose'].astype(str).str.contains('Result|Financial', case=False, na=False)].copy()
    raw_df = raw_df.dropna(subset=['bm_symbol'])
    
    # Parse dates
    raw_df['datetime'] = pd.to_datetime(raw_df['bm_timestamp'], errors='coerce')
    raw_df.loc[raw_df['datetime'].isna(), 'datetime'] = pd.to_datetime(raw_df.loc[raw_df['datetime'].isna(), 'bm_date'], errors='coerce')
    raw_df = raw_df.dropna(subset=['datetime'])
    
    raw_df['release_year'] = raw_df['datetime'].dt.year.astype(int)
    raw_df['release_quarter'] = raw_df['datetime'].dt.quarter.astype(int)
    
    # Keep only the first result announcement per company per quarter
    raw_df = raw_df.sort_values('datetime')
    first_results = raw_df.drop_duplicates(subset=['bm_symbol', 'release_year', 'release_quarter'], keep='first')
    
    # Expected quarters start from 2015 Q1 to current YQ
    start_year = 2015
    current_dt = datetime.now()
    current_year = current_dt.year
    current_quarter = (current_dt.month - 1) // 3 + 1
    
    all_quarters = []
    for y in range(start_year, current_year + 1):
        for q in range(1, 5):
            if y == current_year and q > current_quarter:
                break
            all_quarters.append((y, q))
            
    # Lookup dictionaries
    actuals = {}
    symbol_min_y_q = {}
    
    for _, row in first_results.iterrows():
        sym = row['bm_symbol']
        y = row['release_year']
        q = row['release_quarter']
        dt = row['datetime'].date()
        
        actuals[(sym, y, q)] = dt
        
        if sym not in symbol_min_y_q:
            symbol_min_y_q[sym] = (y, q)
        else:
            if (y, q) < symbol_min_y_q[sym]:
                symbol_min_y_q[sym] = (y, q)
                
    cleaned_records = []
    
    # For mapping default SEBI dates (based on Release Quarter)
    def get_default_date(y, q):
        if q == 1: return datetime(y, 2, 14).date()
        elif q == 2: return datetime(y, 5, 30).date()
        elif q == 3: return datetime(y, 8, 14).date()
        elif q == 4: return datetime(y, 11, 14).date()
    
    today = datetime.now().date()
    
    # Convert master list to symbol set for tracking
    master_symbols = set(master_df['nse_symbol'].tolist())
    
    # Some symbols in raw_df might not be in the master list (e.g. delisted).
    # It's up to you if you want to include them. We will include all master symbols,
    # plus any symbol that actually reported earnings.
    all_symbols_to_process = master_symbols.union(set(symbol_min_y_q.keys()))
    
    # Create lookup for company names
    name_lookup = dict(zip(master_df['nse_symbol'], master_df['company_name']))
    
    for symbol in all_symbols_to_process:
        company_name = name_lookup.get(symbol, symbol)
        
        if symbol in symbol_min_y_q:
            start_y, start_q = symbol_min_y_q[symbol]
        else:
            # If no results ever and it's in the master list, maybe it hasn't reported since 2015.
            # Skip to avoid bloating fake data for newly listed or inactive companies.
            continue
            
        for y, q in all_quarters:
            if (y, q) < (start_y, start_q):
                continue
            
            key = (symbol, y, q)
            quarter_str = f"{y} Q{q}"
            
            if key in actuals:
                release_date = actuals[key]
                source = "NSE Website"
            else:
                release_date = get_default_date(y, q)
                if release_date > today:
                    continue
                source = "Using default, could not find the result filing on NSE"
                
            cleaned_records.append({
                'nse_symbol': symbol,
                'company_name': company_name,
                'result_release_date': release_date,          # Pass actual Date object
                'result_release_for_quarter': quarter_str,
                'source': source,
                'last_updated_date': today                    # Pass actual Date object
            })
            
    cleaned_df = pd.DataFrame(cleaned_records)
    cleaned_df = cleaned_df.sort_values(by=['nse_symbol', 'result_release_for_quarter'])
    
    print(f"Generated {len(cleaned_df)} cleaned records in memory.")
    return cleaned_df

if __name__ == "__main__":
    print("--- 🚀 NSE Earnings Fetch & Clean Pipeline Started ---")
    master_df = get_master_companies()
    raw_df = fetch_raw_data()
    cleaned_df = None
    if raw_df is not None:
        cleaned_df = generate_cleaned_data(raw_df, master_df)
        
    push_to_bigquery(raw_df, cleaned_df)
    print("--- 🎉 Process Complete ---")
