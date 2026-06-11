import os
import pandas as pd
import requests
import io
from dotenv import load_dotenv

# 1. Load environment variables
load_dotenv()

GCP_PROJECT_ID = "adk-mini-project"
BQ_DATASET_TABLE = "stocks.all_listed_stocks"

if not GCP_PROJECT_ID or not BQ_DATASET_TABLE:
    raise ValueError("Missing GCP project or table details in .env file.")
# Note: pandas-gbq automatically looks for GOOGLE_APPLICATION_CREDENTIALS in your environment.

def fetch_nse_data():
    """Fetches and cleans pure NSE stock data."""
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5'
    }
    
    try:
        print("Fetching master list from NSE...")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() 

        raw_data = io.StringIO(response.text)
        df = pd.read_csv(raw_data)
        df.columns = df.columns.str.strip()
        
        nse_df = df[['SYMBOL', 'NAME OF COMPANY', 'ISIN NUMBER', 'DATE OF LISTING']].copy()
        nse_df = nse_df.rename(columns={
            'SYMBOL': 'nse_symbol',
            'NAME OF COMPANY': 'company_name',
            'ISIN NUMBER': 'isin',
            'DATE OF LISTING': 'listing_date'
        })
        
        # Keep ONLY rows where the ISIN indicates a pure corporate stock (INE, IN9)
        nse_df = nse_df[nse_df['isin'].astype(str).str.startswith(('INE', 'IN9'))]
        
        nse_df['listing_date'] = pd.to_datetime(nse_df['listing_date'], format='%d-%b-%Y', errors='coerce').dt.date
        nse_df['is_on_nse'] = True
        return nse_df
    except Exception as e:
        print(f"Warning: Failed to fetch NSE data. Error: {e}")
        return pd.DataFrame()

def fetch_bse_data():
    """Fetches and cleans pure BSE stock data."""
    url = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
    
    bse_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://www.bseindia.com',
        'Referer': 'https://www.bseindia.com/',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site'
    }
    
    try:
        print("Fetching master list from BSE...")
        response = requests.get(url, headers=bse_headers, timeout=15)
        response.raise_for_status()
        
        bse_json = response.json()
        if not bse_json:
             return pd.DataFrame()
             
        df = pd.DataFrame(bse_json)
        df.columns = df.columns.str.lower()
        
        if not {'scrip_cd', 'scrip_name', 'isin_number'}.issubset(df.columns):
            return pd.DataFrame()

        bse_df = df.copy()
        
        if 'group' in bse_df.columns:
            invalid_groups = ['E', 'G', 'F', 'FC', 'IF', 'IT', 'MF']
            bse_df = bse_df[~bse_df['group'].isin(invalid_groups)]
            
        bse_df = bse_df.rename(columns={
            'scrip_cd': 'bse_symbol',
            'scrip_name': 'company_name_bse',
            'isin_number': 'isin'
        })
        
        # Keep ONLY pure stocks
        bse_df = bse_df[bse_df['isin'].astype(str).str.startswith(('INE', 'IN9'))]
        
        bse_df = bse_df[['bse_symbol', 'company_name_bse', 'isin']].copy()
        bse_df['is_on_bse'] = True
        return bse_df
        
    except Exception as e:
        print(f"Warning: Failed to fetch BSE data. Error: {e}")
        return pd.DataFrame()

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    nse_data = fetch_nse_data()
    bse_data = fetch_bse_data()

    if nse_data.empty:
        raise RuntimeError("NSE data fetching failed. Cannot perform left join without primary NSE data.")

    print("\nMerging datasets on ISIN (Left Join on NSE)...")
    
    if not bse_data.empty:
        merged_df = pd.merge(nse_data, bse_data, on='isin', how='left')
        if 'company_name_bse' in merged_df.columns:
            merged_df = merged_df.drop(columns=['company_name_bse'])
    else:
        merged_df = nse_data
        merged_df['bse_symbol'] = None
        merged_df['is_on_bse'] = False

    merged_df['is_on_nse'] = True 
    merged_df['is_on_bse'] = merged_df['is_on_bse'].fillna(False)

    print(f"Total NSE-focused stocks prepared: {len(merged_df)}")
    
    # Upload to Google BigQuery
    print(f"\nPushing data to BigQuery table: {BQ_DATASET_TABLE}...")
    
    # Explicitly define the BigQuery schema to guarantee the DATE type
    bq_schema = [
        {'name': 'nse_symbol', 'type': 'STRING'},
        {'name': 'company_name', 'type': 'STRING'},
        {'name': 'isin', 'type': 'STRING'},
        {'name': 'listing_date', 'type': 'DATE'},  # Enforces strict DATE format
        {'name': 'bse_symbol', 'type': 'STRING'},
        {'name': 'is_on_nse', 'type': 'BOOLEAN'},
        {'name': 'is_on_bse', 'type': 'BOOLEAN'}
    ]
    
    try:
        merged_df.to_gbq(
            destination_table=BQ_DATASET_TABLE,
            project_id=GCP_PROJECT_ID,
            if_exists='replace',
            table_schema=bq_schema
        )
        print("Success! The BigQuery table has been fully overridden with native DATE types.")
    except Exception as e:
        print(f"BigQuery upload failed: {e}")