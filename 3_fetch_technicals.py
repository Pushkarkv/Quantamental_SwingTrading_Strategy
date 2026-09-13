import os
import time
import datetime
import pandas as pd
import yfinance as yf
import pytz
from google.cloud import bigquery
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

GCP_PROJECT_ID = "adk-mini-project"
BQ_DATASET = "technicals"
BQ_MASTER_STOCKS_TABLE =  "adk-mini-project.stocks.all_listed_stocks"

START_DATE = "2015-01-01"
SPLIT_THRESHOLD = 0.05  # 5% price difference triggers a redownload
BATCH_LIMIT = 100000     # Push to DB when accumulated rows exceed this

if not GCP_PROJECT_ID or not BQ_MASTER_STOCKS_TABLE:
    raise ValueError("Missing GCP project or master stock table in .env file.")

# --- UTILS ---

def get_bq_client():
    return bigquery.Client(project=GCP_PROJECT_ID)

def get_ist_time():
    return datetime.datetime.now(pytz.timezone('Asia/Kolkata'))

# --- DATABASE SETUP & READ LOGIC ---

def ensure_tables_exist(client):
    """Creates the necessary tables in BigQuery if they don't already exist."""
    
    # 1. Ensure the Dataset exists and REMOVE default expirations
    dataset_ref = bigquery.Dataset(f"{GCP_PROJECT_ID}.{BQ_DATASET}")
    dataset_ref.location = "asia-south1" # Change if your dataset is in another region
    
    # Create dataset if it doesn't exist
    dataset = client.create_dataset(dataset_ref, exists_ok=True)
    
    # Force update the dataset to ensure no hidden 60-day default exists
    # CRITICAL: Must clear BOTH expiration settings.
    #   - default_table_expiration_ms: affects ALL tables and views (this was killing our views!)
    #   - default_partition_expiration_ms: affects partitioned table partitions
    dataset.default_table_expiration_ms = None
    dataset.default_partition_expiration_ms = None
    client.update_dataset(dataset, ["default_table_expiration_ms", "default_partition_expiration_ms"])

    # 2. Data Table (NOW PARTITIONED AND CLUSTERED WITH EXPIRATION DISABLED)
    client.query(f"""
        CREATE TABLE IF NOT EXISTS `{GCP_PROJECT_ID}.{BQ_DATASET}.daily_stock_price` (
            symbol_date STRING,
            symbol STRING,
            date DATE,
            open FLOAT64,
            high FLOAT64,
            low FLOAT64,
            close FLOAT64,
            volume INT64
        )
        PARTITION BY DATE_TRUNC(date, MONTH)
        CLUSTER BY symbol
        OPTIONS(
            partition_expiration_days = NULL
        )
    """).result()

    # 3. Log Table
    client.query(f"""
        CREATE TABLE IF NOT EXISTS `{GCP_PROJECT_ID}.{BQ_DATASET}.daily_stock_price_log` (
            symbol STRING,
            last_fetched_date DATE,
            last_close_price FLOAT64,
            status STRING,
            source STRING,
            updated_at TIMESTAMP
        )
    """).result()

def get_symbols_from_db(client):
    """Fetches the master list of active symbols from BigQuery."""
    # Using nse_symbol or symbol depending on your master table structure
    # Adjust 'nse_symbol' below to match your master table's column name if needed
    query = f"SELECT nse_symbol as symbol FROM `{BQ_MASTER_STOCKS_TABLE}` WHERE nse_symbol IS NOT NULL;"
    df = client.query(query).to_dataframe()
    return df['symbol'].unique()

def load_update_log(client):
    """Loads the log from BigQuery into a Pandas DataFrame."""
    query = f"SELECT * FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.daily_stock_price_log`;"
    df = client.query(query).to_dataframe()
    
    if not df.empty:
        df['last_fetched_date'] = pd.to_datetime(df['last_fetched_date']).dt.date
        return df.set_index('symbol')
    else:
        return pd.DataFrame(columns=['symbol', 'last_fetched_date', 'last_close_price', 'status', 'source', 'updated_at']).set_index('symbol')

# --- IN-MEMORY BATCH EXECUTION ---

def flush_batches(client, batch_dfs, batch_logs, symbols_to_delete):
    """Pushes accumulated data to BigQuery using Staging tables and MERGE statements."""
    
    table_data = f"{GCP_PROJECT_ID}.{BQ_DATASET}.daily_stock_price"
    table_log = f"{GCP_PROJECT_ID}.{BQ_DATASET}.daily_stock_price_log"

    try:
        # 1. Execute Bulk Deletes (For Splits)
        if symbols_to_delete:
            format_strings = ', '.join([f"'{s}'" for s in symbols_to_delete])
            delete_query = f"DELETE FROM `{table_data}` WHERE symbol IN ({format_strings})"
            client.query(delete_query).result()

        # 2. Execute Bulk OHLCV Upserts via MERGE
        if batch_dfs:
            master_df = pd.concat(batch_dfs, ignore_index=True)
            staging_table_data = f"{table_data}_staging"
            
            # Load to staging table
            job = client.load_table_from_dataframe(
                master_df, 
                staging_table_data, 
                job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
            )
            job.result()

            # Merge staging into main table
            merge_data_query = f"""
                MERGE `{table_data}` T
                USING `{staging_table_data}` S
                ON T.symbol_date = S.symbol_date
                WHEN MATCHED THEN
                    UPDATE SET open = S.open, high = S.high, low = S.low, close = S.close, volume = S.volume
                WHEN NOT MATCHED THEN
                    INSERT (symbol_date, symbol, date, open, high, low, close, volume)
                    VALUES (S.symbol_date, S.symbol, S.date, S.open, S.high, S.low, S.close, S.volume)
            """
            client.query(merge_data_query).result()

        # 3. Execute Bulk Log Upserts via MERGE
        if batch_logs:
            log_df_to_push = pd.DataFrame(batch_logs, columns=[
                'symbol', 'last_fetched_date', 'last_close_price', 'status', 'source', 'updated_at'
            ])
            staging_table_log = f"{table_log}_staging"
            
            # Load to staging table
            job = client.load_table_from_dataframe(
                log_df_to_push, 
                staging_table_log, 
                job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
            )
            job.result()

            # Merge staging into main log table
            merge_log_query = f"""
                MERGE `{table_log}` T
                USING `{staging_table_log}` S
                ON T.symbol = S.symbol
                WHEN MATCHED THEN
                    UPDATE SET last_fetched_date = S.last_fetched_date, 
                               last_close_price = S.last_close_price, 
                               status = S.status, 
                               source = S.source, 
                               updated_at = S.updated_at
                WHEN NOT MATCHED THEN
                    INSERT (symbol, last_fetched_date, last_close_price, status, source, updated_at)
                    VALUES (S.symbol, S.last_fetched_date, S.last_close_price, S.status, S.source, S.updated_at)
            """
            client.query(merge_log_query).result()

        print(f"   💾 [BATCH FLUSH] Pushed {sum(len(df) for df in batch_dfs)} rows and {len(batch_logs)} logs to BigQuery.")
        
    except Exception as e:
        print(f"   ❌ [CRITICAL] Batch flush failed: {e}")
        raise e

# --- YFINANCE FETCH LOGIC ---

def fetch_candles_yf_raw(yf_symbol, start_date):
    if isinstance(start_date, datetime.date):
        start_date = start_date.strftime("%Y-%m-%d")

    try:
        stock = yf.Ticker(yf_symbol)
        df = stock.history(start=start_date, auto_adjust=True)
        
        if df.empty: return None
        
        df.reset_index(inplace=True)
        df.columns = [c.lower() for c in df.columns]
        
        if 'date' not in df.columns and 'index' in df.columns:
            df.rename(columns={'index': 'date'}, inplace=True)

        required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
        missing = [c for c in required_cols if c not in df.columns]
        if missing: return None 
            
        df['date'] = pd.to_datetime(df['date']).dt.date
        s_date_obj = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        df = df[df['date'] >= s_date_obj]
        
        # Clean Data
        df = df[df['close'] > 0.0].copy() 
        df['open'] = df['open'].round(2)
        df['high'] = df['high'].round(2)
        df['low'] = df['low'].round(2)
        df['close'] = df['close'].round(2)
        df.fillna(0, inplace=True)
        df['volume'] = df['volume'].astype(int)
        
        if df.empty: return None
        
        return df[required_cols]

    except Exception:
        return None

def fetch_with_nse_priority(raw_symbol, start_date):
    nse_symbol = f"{raw_symbol}.NS"
    df = fetch_candles_yf_raw(nse_symbol, start_date)
    if df is not None and not df.empty: return df, "NSE"
    
    bse_symbol = f"{raw_symbol}.BO"
    df = fetch_candles_yf_raw(bse_symbol, start_date)
    if df is not None and not df.empty: return df, "BSE"
        
    return None, "FAILED"

# --- MAIN PIPELINE ---

def main():
    print("--- 🚀 High-Speed Batch Technicals Scraper Started ---")
    
    try:
        bq_client = get_bq_client()
        print("Checking/Creating BigQuery Tables...")
        ensure_tables_exist(bq_client)
    except Exception as e:
        print(f"❌ Failed to connect or initialize BigQuery: {e}")
        return

    symbols_to_fetch = get_symbols_from_db(bq_client)
    
    if len(symbols_to_fetch) == 0:
        print("❌ Error: No symbols found in master table.")
        return
        
    print(f"--- 🎯 Found {len(symbols_to_fetch)} symbols to process ---")
    log_df = load_update_log(bq_client)
    
    # --- Accumulators for Memory Batching ---
    batch_dfs = []
    batch_logs = []
    symbols_to_delete = []
    batch_row_count = 0
    
    for idx, symbol in enumerate(symbols_to_fetch):
        print(f"[{idx+1}/{len(symbols_to_fetch)}] {symbol}                  ", end="\r") 
        
        try:
            # --- INCREMENTAL / SPLIT CHECK ---
            if symbol in log_df.index:
                last_date = log_df.loc[symbol, 'last_fetched_date']
                last_price_raw = log_df.loc[symbol, 'last_close_price']
                last_price = float(last_price_raw) if not pd.isna(last_price_raw) and last_price_raw is not None else 0.0
                
                new_data, source = fetch_with_nse_priority(symbol, last_date)
                
                if new_data is None or new_data.empty:
                    batch_logs.append((symbol, last_date, last_price, "UP_TO_DATE", source, get_ist_time()))
                    continue
                    
                overlap_row = new_data[new_data['date'] == last_date]
                is_split = False
                
                if not overlap_row.empty and last_price > 0:
                    api_price = float(overlap_row.iloc[0]['close'])
                    if abs(api_price - last_price) / last_price > SPLIT_THRESHOLD:
                        print(f"\n      ⚠️ SPLIT DETECTED for {symbol}! (Old: {last_price:.2f}, New: {api_price:.2f})")
                        is_split = True
                
                if is_split:
                    full_data, source = fetch_with_nse_priority(symbol, START_DATE)
                    if full_data is not None and not full_data.empty:
                        symbols_to_delete.append(symbol)
                        
                        full_data['symbol'] = symbol
                        full_data['symbol_date'] = full_data['symbol'] + "_" + full_data['date'].astype(str)
                        
                        batch_dfs.append(full_data)
                        batch_row_count += len(full_data)
                        
                        new_last_date = full_data.iloc[-1]['date']
                        new_last_price = float(full_data.iloc[-1]['close'])
                        batch_logs.append((symbol, new_last_date, new_last_price, "REBUILT", source, get_ist_time()))
                else:
                    new_rows = new_data[new_data['date'] > last_date].copy()
                    if not new_rows.empty:
                        new_rows['symbol'] = symbol
                        new_rows['symbol_date'] = new_rows['symbol'] + "_" + new_rows['date'].astype(str)
                        
                        batch_dfs.append(new_rows)
                        batch_row_count += len(new_rows)
                        
                        new_last_date = new_rows.iloc[-1]['date']
                        new_last_price = float(new_rows.iloc[-1]['close'])
                        batch_logs.append((symbol, new_last_date, new_last_price, "APPENDED", source, get_ist_time()))
                    else:
                        batch_logs.append((symbol, last_date, last_price, "UP_TO_DATE", source, get_ist_time()))

            # --- FIRST TIME FETCH ---
            else:
                full_data, source = fetch_with_nse_priority(symbol, START_DATE)
                if full_data is not None and not full_data.empty:
                    full_data['symbol'] = symbol
                    full_data['symbol_date'] = full_data['symbol'] + "_" + full_data['date'].astype(str)
                    
                    batch_dfs.append(full_data)
                    batch_row_count += len(full_data)
                    
                    new_last_date = full_data.iloc[-1]['date']
                    new_last_price = float(full_data.iloc[-1]['close'])
                    batch_logs.append((symbol, new_last_date, new_last_price, "FULL_DOWNLOAD", source, get_ist_time()))
                else:
                    batch_logs.append((symbol, None, None, "ERROR_NO_DATA", "NONE", get_ist_time()))

        except Exception as e:
            print(f"\n      ❌ Error on {symbol}: {e}")
            batch_logs.append((symbol, None, None, f"ERROR: {str(e)[:40]}", "NONE", get_ist_time()))
            
        # --- BATCH EXECUTION TRIGGER ---
        if batch_row_count >= BATCH_LIMIT:
            print(f"\n   -> Reached {batch_row_count} rows. Triggering database flush...")
            flush_batches(bq_client, batch_dfs, batch_logs, symbols_to_delete)
            batch_dfs = []
            batch_logs = []
            symbols_to_delete = []
            batch_row_count = 0
            
        time.sleep(0.05)

    # --- FINAL CLEANUP FLUSH ---
    if batch_dfs or batch_logs or symbols_to_delete:
        print(f"\n   -> Final loop finished. Flushing remaining data...")
        flush_batches(bq_client, batch_dfs, batch_logs, symbols_to_delete)

    print("\n--- 🎉 Database Technicals Update Complete ---")

if __name__ == "__main__":
    main()