import os
import pandas as pd
import requests
import io
from dotenv import load_dotenv

# 1. Load environment variables
load_dotenv()

GCP_PROJECT_ID = "adk-mini-project"
BQ_INDICES_TABLE = "stocks.indices"

if not GCP_PROJECT_ID or not BQ_INDICES_TABLE:
    raise ValueError("Missing GCP project or table details in .env file.")

# 2. Zerodha's public Kite instruments URL
url = "https://api.kite.trade/instruments"

try:
    print("Downloading live instruments list from Zerodha...")
    response = requests.get(url, timeout=15)
    response.raise_for_status()

    # 3. Read the CSV data directly into Pandas
    df = pd.read_csv(io.StringIO(response.text))
    df.columns = df.columns.str.strip()

    # 4. Filter for BOTH NSE and BSE Indices
    # Segment must be 'INDICES' and Exchange can be either 'NSE' or 'BSE'
    combined_indices = df[
        (df['exchange'].isin(['NSE', 'BSE'])) & 
        (df['segment'] == 'INDICES')
    ]

    # 5. Clean up columns for your master index list
    clean_indices = combined_indices[['tradingsymbol', 'name', 'instrument_token', 'exchange']].copy()

    print(f"\nPrepared {len(clean_indices)} total indices (NSE & BSE). Pushing to BigQuery...")

    # 6. Explicitly define the BigQuery schema
    bq_schema = [
        {'name': 'tradingsymbol', 'type': 'STRING'},
        {'name': 'name', 'type': 'STRING'},
        {'name': 'instrument_token', 'type': 'INTEGER'}, 
        {'name': 'exchange', 'type': 'STRING'}
    ]

    # 7. Upload to Google BigQuery
    # if_exists='replace' drops the old table and recreates it with fresh data
    clean_indices.to_gbq(
        destination_table=BQ_INDICES_TABLE,
        project_id=GCP_PROJECT_ID,
        if_exists='replace',
        table_schema=bq_schema
    )
    
    print(f"Success! Data has been stored in BigQuery table: {BQ_INDICES_TABLE}")

except requests.exceptions.RequestException as e:
    print(f"Network error fetching the file: {e}")
except Exception as e:
    print(f"An error occurred: {e}")