import os
import pandas as pd
import requests
import zipfile
import io
import datetime
from dotenv import load_dotenv

# 1. Load environment variables
load_dotenv()

GCP_PROJECT_ID = "adk-mini-project"
BQ_DATASET_TABLE = "stocks.all_listed_stocks"

if not GCP_PROJECT_ID or not BQ_DATASET_TABLE:
    raise ValueError("Missing GCP project or table details in .env file.")

def fetch_nse_data():
    """Fetches and cleans pure NSE stock data."""
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
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
        
        bse_df = bse_df[bse_df['isin'].astype(str).str.startswith(('INE', 'IN9'))]
        bse_df = bse_df[['bse_symbol', 'company_name_bse', 'isin']].copy()
        bse_df['is_on_bse'] = True
        return bse_df
        
    except Exception as e:
        print(f"Warning: Failed to fetch BSE data. Error: {e}")
        return pd.DataFrame()

def fetch_official_nse_market_cap():
    """
    Downloads the PR Zip file from NSE for the most recent trading day,
    extracts the MCAP file, and returns a DataFrame of Symbol and Market Cap.
    """
    print("Searching for the most recent official NSE PR archive...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    
    # Loop back up to 5 days to handle weekends/holidays seamlessly
    for i in range(5):
        target_date = datetime.datetime.now() - datetime.timedelta(days=i)
        date_str_short = target_date.strftime("%d%m%y")
        
        zip_url = f"https://archives.nseindia.com/archives/equities/bhavcopy/pr/PR{date_str_short}.zip"
        
        try:
            response = requests.get(zip_url, headers=headers, timeout=10)
            if response.status_code == 200:
                print(f"-> Successfully located PR file for {target_date.strftime('%d-%b-%Y')}")
                
                # Extract the zip entirely in memory
                with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                    mcap_filename = next((name for name in z.namelist() if name.lower().startswith('mcap') and name.lower().endswith('.csv')), None)
                    
                    if not mcap_filename:
                        print("-> MCAP file not found in the zip. Trying previous day...")
                        continue
                        
                    print(f"-> Extracting internal file: {mcap_filename}")
                    
                    with z.open(mcap_filename) as f:
                        mcap_df = pd.read_csv(f)
                        mcap_df.columns = mcap_df.columns.str.strip().str.lower()
                        
                        # Dynamically find the market cap column to future-proof against NSE column renames
                        mcap_col = next((col for col in mcap_df.columns if 'market cap' in col or 'mcap' in col), None)
                        
                        if 'symbol' in mcap_df.columns and mcap_col:
                            mcap_df = mcap_df.rename(columns={'symbol': 'nse_symbol', mcap_col: 'market_cap_raw'})
                            # Convert raw INR to Crores (1 Crore = 10,000,000 INR)
                            mcap_df['market_cap_cr'] = mcap_df['market_cap_raw'] / 10000000
                            
                            # Keep only unique symbols (in case of multiple series like EQ, BE, etc.)
                            mcap_df = mcap_df.drop_duplicates(subset=['nse_symbol'])
                            return mcap_df[['nse_symbol', 'market_cap_cr']].copy()
                        else:
                            print("-> Warning: Expected columns not found in MCAP file.")
                            return pd.DataFrame()
            else:
                continue
                
        except Exception as e:
            print(f"Error checking {date_str_short}: {e}")
            continue
            
    print("Failed to find a valid PR Zip file in the last 5 days.")
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
    
    print(f"Total NSE-focused stocks before filtering: {len(merged_df)}")

    # --- OFFICIAL MARKET CAP FILTERING ---
    market_cap_df = fetch_official_nse_market_cap()
    
    if not market_cap_df.empty:
        merged_df = pd.merge(merged_df, market_cap_df, on='nse_symbol', how='left')
        merged_df['market_cap_cr'] = merged_df['market_cap_cr'].fillna(0)
        
        # Apply the >= 1000 Cr Filter
        merged_df = merged_df[merged_df['market_cap_cr'] >= 1000].copy()
        print(f"Total stocks remaining AFTER applying >= 1000 Cr Market Cap filter: {len(merged_df)}")
    else:
        print("Market cap data could not be joined. Uploading unfiltered data.")
        merged_df['market_cap_cr'] = 0.0

    # --- UPLOAD TO BIGQUERY ---
    print(f"\nPushing data to BigQuery table: {BQ_DATASET_TABLE}...")
    
    bq_schema = [
        {'name': 'nse_symbol', 'type': 'STRING'},
        {'name': 'company_name', 'type': 'STRING'},
        {'name': 'isin', 'type': 'STRING'},
        {'name': 'listing_date', 'type': 'DATE'},  
        {'name': 'bse_symbol', 'type': 'STRING'},
        {'name': 'is_on_nse', 'type': 'BOOLEAN'},
        {'name': 'is_on_bse', 'type': 'BOOLEAN'},
        {'name': 'market_cap_cr', 'type': 'FLOAT64'} 
    ]
    
    try:
        merged_df.to_gbq(
            destination_table=BQ_DATASET_TABLE,
            project_id=GCP_PROJECT_ID,
            if_exists='replace',
            table_schema=bq_schema
        )
        print("Success! The BigQuery table has been fully overridden with native Exchange Market Cap data.")
    except Exception as e:
        print(f"BigQuery upload failed: {e}")