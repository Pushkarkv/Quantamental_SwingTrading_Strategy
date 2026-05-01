"""
Screener.in Stock Fundamentals — Direct-to-BigQuery Scraper.

Fetches stock symbols from BigQuery, scrapes Screener.in, and pushes 
all data natively to BigQuery tables (no CSVs). Dynamically adds new 
columns (like Bank headers) using BigQuery's ALLOW_FIELD_ADDITION.

Usage:
    python scrape_all_bq.py                  # Scrape all NSE stocks
    python scrape_all_bq.py --limit 100      # First 100 only
    python scrape_all_bq.py --delay 3        # Custom delay
    python scrape_all_bq.py --no-resume      # Force re-scrape ignoring quarter check
"""

import sys, os, io, re, time, logging, argparse
from datetime import datetime
from collections import OrderedDict
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import pandas as pd
from google.cloud import bigquery

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
GCP_PROJECT_ID = "adk-mini-project"
BQ_DATASET = "fundamentals"
BQ_MASTER_STOCKS_TABLE = "adk-mini-project.stocks.all_listed_stocks" 

BASE_URL = "https://www.screener.in/company/{symbol}/consolidated/"
STANDALONE_URL = "https://www.screener.in/company/{symbol}/"
PEER_API_URL = "https://www.screener.in/api/company/{warehouse_id}/peers/"

FLUSH_INTERVAL = 50
REQUEST_DELAY = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.screener.in/",
}

if not GCP_PROJECT_ID or not BQ_MASTER_STOCKS_TABLE:
    raise ValueError("Missing GCP project or master stock table in .env file.")

bq_client = bigquery.Client(project=GCP_PROJECT_ID)

# ═══════════════════════════════════════════════════════════════════════════════
#  DATE MATH & QUARTER CHECK LOGIC
# ═══════════════════════════════════════════════════════════════════════════════
def get_latest_completed_quarter_date():
    now = datetime.now()
    curr_month = now.month
    if curr_month in [1, 2, 3]: return datetime(now.year - 1, 12, 1)
    elif curr_month in [4, 5, 6]: return datetime(now.year, 3, 1)
    elif curr_month in [7, 8, 9]: return datetime(now.year, 6, 1)
    else: return datetime(now.year, 9, 1)

def should_scrape(last_quarter_str):
    if not last_quarter_str: return True
    try: last_dt = datetime.strptime(last_quarter_str.strip(), "%b %Y")
    except ValueError: return True
    latest_q = get_latest_completed_quarter_date()
    months_diff = (latest_q.year - last_dt.year) * 12 + (latest_q.month - last_dt.month)
    return (months_diff // 3) >= 2

# ═══════════════════════════════════════════════════════════════════════════════
#  SCRAPER
# ═══════════════════════════════════════════════════════════════════════════════
def _clean(text): return re.sub(r"[\s\xa0]+", " ", text).strip()
def _clean_header(text): return re.sub(r"\s*\+\s*$", "", _clean(text))

def _fetch_page(url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except (requests.Timeout, requests.ConnectionError) as e:
            wait = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            if attempt < MAX_RETRIES: time.sleep(wait)
            else: return None
        except requests.RequestException as e:
            return None
    return None

def _get_warehouse_id(soup):
    el = soup.find(attrs={"data-warehouse-id": True})
    return el.get("data-warehouse-id") if el else None

def _extract_table(section_or_table, table_index=0):
    if section_or_table is None: return {"headers": [], "rows": []}
    if section_or_table.name == "table": table = section_or_table
    else:
        tables = section_or_table.find_all("table", recursive=True)
        if table_index >= len(tables): return {"headers": [], "rows": []}
        table = tables[table_index]
    headers = []
    thead = table.find("thead")
    if thead: headers = [_clean_header(th.get_text()) for th in thead.find_all(["th", "td"])]
    else:
        first_tr = table.find("tr")
        if first_tr: headers = [_clean_header(c.get_text()) for c in first_tr.find_all(["th", "td"])]
    rows = []
    tbody = table.find("tbody")
    body_rows = tbody.find_all("tr", recursive=False) if tbody else table.find_all("tr")[1:]
    for tr in body_rows:
        cells = tr.find_all(["td", "th"], recursive=False)
        cell_texts = [_clean(cell.get_text()) for cell in cells]
        if cell_texts: cell_texts[0] = re.sub(r"\s*\+\s*$", "", cell_texts[0])
        if not cell_texts or all(c == "" for c in cell_texts) or cell_texts == headers: continue
        row_data = {headers[i] if i < len(headers) else f"col_{i}": val for i, val in enumerate(cell_texts)}
        row_data["_is_sub_row"] = "sub" in " ".join(tr.get("class", []))
        row_data["_row_header"] = cell_texts[0] if cell_texts else ""
        rows.append(row_data)
    return {"headers": headers, "rows": rows}

def extract_company_info(soup):
    info = {}
    h1 = soup.find("h1")
    if h1: info["company_name"] = _clean(h1.get_text())
    about = soup.find("div", class_="company-profile")
    if about and about.find("p"): info["description"] = _clean(about.find("p").get_text())
    for a_tag in soup.find_all("a"):
        href, text = a_tag.get("href", ""), _clean(a_tag.get_text())
        if "bseindia" in href and "bse_code" not in info:
            m = re.search(r"(\d{5,6})", text) or re.search(r"/(\d{5,6})(?:/|$)", href)
            if m: info["bse_code"] = m.group(1)
        elif "nseindia" in href and "nse_symbol" not in info:
            m = re.search(r"symbol=(\w+)", href) or re.search(r"NSE:\s*(\w+)", text)
            if m: info["nse_symbol"] = m.group(1)
    peers = soup.find("section", id="peers")
    if peers:
        sectors = [_clean(a.get_text()) for a in peers.find_all("a") if "/market/" in a.get("href", "")]
        if sectors: info["sector_classification"] = " > ".join(sectors[:4])
    return info

def extract_key_ratios(soup):
    ratios = {}
    top_section = soup.find("section", id="top") or soup.find("div", id="top") or soup
    ratio_list = top_section.find("ul", id="top-ratios")
    if not ratio_list:
        for ul in top_section.find_all("ul"):
            if ul.find("li") and ul.find("span", class_="name"): ratio_list = ul; break
    if ratio_list:
        for li in ratio_list.find_all("li", recursive=False):
            name_el = li.find("span", class_="name")
            if not name_el: continue
            name = _clean(name_el.get_text())
            if not name or name == "Edit ratios": continue
            val = re.sub(r"[\s\xa0]+", " ", li.get_text()).replace(name_el.get_text(), "", 1).strip()
            ratios[name] = re.sub(r"\s*Cr\.\s*$", "", re.sub(r"^[₹$]\s*", "", val)).strip()
    return ratios

def extract_pros_cons(soup):
    result = {"pros": [], "cons": []}
    for cls, key in [("pros", "pros"), ("cons", "cons")]:
        section = soup.find("div", class_=cls)
        if section:
            ul = section.find("ul") if section.name != "ul" else section
            if ul: result[key] = [_clean(li.get_text()) for li in ul.find_all("li")]
    return result

def extract_peer_comparison(soup, symbol):
    section = soup.find("section", id="peers")
    if section and section.find_all("table"):
        result = _extract_table(section, 0)
        if result["rows"]: return result
    wid = _get_warehouse_id(soup)
    if wid:
        try:
            resp = requests.get(PEER_API_URL.format(warehouse_id=wid), headers=REQUEST_HEADERS, timeout=30)
            if resp.status_code == 200:
                table = BeautifulSoup(resp.text, "lxml").find("table")
                if table:
                    result = _extract_table(table)
                    if result["rows"]: return result
        except: pass
    return {"headers": [], "rows": []}

def _extract_section(soup, section_id, label, table_index=0):
    return _extract_table(soup.find("section", id=section_id), table_index) if soup.find("section", id=section_id) else {"headers": [], "rows": []}

def extract_shareholding(soup, table_idx, label):
    section = soup.find("section", id="shareholding")
    if not section or table_idx >= len(section.find_all("table")): return {"headers": [], "rows": []}
    return _extract_table(section.find_all("table")[table_idx])

def _data_has_periods(data):
    for key in ["quarterly_results", "profit_loss", "balance_sheet"]:
        if len(data.get(key, {}).get("headers", [])) >= 2: return True
    return False

def scrape_company(symbol, consolidated=True):
    sym = symbol.upper()
    if consolidated:
        url = BASE_URL.format(symbol=sym)
        soup = _fetch_page(url)
        if soup:
            data = _scrape_page(soup, sym, "consolidated", url)
            if _data_has_periods(data): return data

    url = STANDALONE_URL.format(symbol=sym)
    soup = _fetch_page(url)
    if not soup: return {"error": f"Failed to fetch {sym}", "symbol": sym}
    return _scrape_page(soup, sym, "standalone", url)

def _scrape_page(soup, symbol, mode_label, url):
    info = extract_company_info(soup)
    return {
        "symbol": symbol.upper(), "nse_symbol": info.get("nse_symbol", symbol.upper()),
        "bse_code": info.get("bse_code", ""), "type": mode_label, "url": url,
        "company_info": info, "key_ratios": extract_key_ratios(soup), "pros_cons": extract_pros_cons(soup),
        "peer_comparison": extract_peer_comparison(soup, symbol.upper()),
        "quarterly_results": _extract_section(soup, "quarters", "Quarterly Results"),
        "profit_loss": _extract_section(soup, "profit-loss", "P&L"),
        "balance_sheet": _extract_section(soup, "balance-sheet", "Balance Sheet"),
        "cash_flows": _extract_section(soup, "cash-flow", "Cash Flows"),
        "ratios": _extract_section(soup, "ratios", "Ratios"),
        "shareholding_quarterly": extract_shareholding(soup, 0, "Shareholding (quarterly)"),
        "shareholding_yearly": extract_shareholding(soup, 1, "Shareholding (yearly)"),
    }

def get_last_quarter(data):
    headers = data.get("quarterly_results", {}).get("headers", [])
    periods = [h for h in headers[1:] if h.strip()] if len(headers) > 1 else []
    return periods[-1] if periods else ""

# ═══════════════════════════════════════════════════════════════════════════════
#  DIRECT BIGQUERY EXPORTER (Replaces CSV Logic)
# ═══════════════════════════════════════════════════════════════════════════════
def _transpose_financial_table(table_data, nse_symbol, bse_code):
    if not table_data or not table_data.get("rows") or len(table_data["headers"]) < 2: return []
    headers, rows = table_data["headers"], table_data["rows"]
    line_items = [row.get(headers[0], row.get("_row_header", "")) for row in rows]
    records = []
    for period in headers[1:]:
        record = OrderedDict([("nse_symbol", nse_symbol), ("bse_code", bse_code), ("Period", period)])
        for i, row in enumerate(rows):
            if i < len(line_items) and line_items[i]: record[line_items[i]] = row.get(period, "")
        records.append(record)
    return records

def export_combined_to_bq(all_data, client):
    """Pushes data directly to BigQuery tables using dynamic schemas and sanitized columns."""
    def ext_ci(sym, data):
        r = OrderedDict([("nse_symbol", data.get("nse_symbol", sym)), ("bse_code", data.get("bse_code", ""))])
        r.update({k: v for k, v in data.get("company_info", {}).items() if k not in ("nse_symbol", "bse_code")})
        return r
        
    def ext_kr(sym, data):
        r = OrderedDict([("nse_symbol", data.get("nse_symbol", sym)), ("bse_code", data.get("bse_code", ""))])
        r.update(data.get("key_ratios", {}))
        return r

    exports = [
        ("company_info", "_ci"), ("key_ratios", "_kr"), ("pros_cons", "_pc"),
        ("peer_comparison", "_peer"), ("quarterly_results", "quarterly_results"),
        ("profit_loss", "profit_loss"), ("balance_sheet", "balance_sheet"),
        ("cash_flows", "cash_flows"), ("ratios", "ratios"),
        ("shareholding_quarterly", "shareholding_quarterly"),
        ("shareholding_yearly", "shareholding_yearly"),
    ]
    
    # Helper function to clean column names for BigQuery
    def clean_bq_col(col_name):
        # Replace non-alphanumeric characters with underscores
        cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', str(col_name))
        # Collapse multiple underscores into one
        cleaned = re.sub(r'_+', '_', cleaned)
        # Strip leading/trailing underscores
        cleaned = cleaned.strip('_')
        # BigQuery columns cannot start with a number, prepend an underscore if they do
        if cleaned and cleaned[0].isdigit():
            cleaned = '_' + cleaned
        return cleaned

    for table_name, key in exports:
        records = []
        if key in ("_ci", "_kr"):
            func = ext_ci if key == "_ci" else ext_kr
            for sym, data in all_data.items():
                if "error" not in data: records.append(func(sym, data))
        elif key == "_pc":
            for sym, data in all_data.items():
                if "error" in data: continue
                nse, bse = data.get("nse_symbol", sym), data.get("bse_code", "")
                for p in data.get("pros_cons", {}).get("pros", []): records.append(OrderedDict([("nse_symbol", nse), ("bse_code", bse), ("Type", "Pro"), ("Description", p)]))
                for c in data.get("pros_cons", {}).get("cons", []): records.append(OrderedDict([("nse_symbol", nse), ("bse_code", bse), ("Type", "Con"), ("Description", c)]))
        elif key == "_peer":
            for sym, data in all_data.items():
                if "error" in data: continue
                nse, bse = data.get("nse_symbol", sym), data.get("bse_code", "")
                ph = [h for h in data.get("peer_comparison", {}).get("headers", []) if not h.startswith("_")]
                for row in data.get("peer_comparison", {}).get("rows", []):
                    r = OrderedDict([("source_nse_symbol", nse), ("source_bse_code", bse)])
                    for h in ph: r[h] = row.get(h, "")
                    records.append(r)
        else:
            for sym, data in all_data.items():
                if "error" not in data: records.extend(_transpose_financial_table(data.get(key, {}), data.get("nse_symbol", sym), data.get("bse_code", "")))
            
        if not records: continue
        
        df = pd.DataFrame(records)
        
        # --- THE FIX: Sanitize all column headers before BigQuery interactions ---
        df.columns = [clean_bq_col(c) for c in df.columns]
        
        table_id = f"{GCP_PROJECT_ID}.{BQ_DATASET}.{table_name}"
        
        # 1. DELETE existing records for these symbols to prevent duplicates
        symbol_col = "source_nse_symbol" if key == "_peer" else "nse_symbol"
        unique_symbols = df[symbol_col].dropna().unique()
        
        if len(unique_symbols) > 0:
            symbols_formatted = ", ".join([f"'{s}'" for s in unique_symbols if s])
            delete_query = f"DELETE FROM `{table_id}` WHERE {symbol_col} IN ({symbols_formatted})"
            try:
                client.query(delete_query).result()
            except Exception:
                pass # Safe to ignore on first run
        
        # 2. APPEND the newly scraped data (Dynamic ALTER enabled)
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
            schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]
        )
        
        try:
            job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
            job.result()
            log.info(f"  -> Pushed {len(df)} rows to BQ:{table_name} (Auto-Schema: ON)")
        except Exception as e:
            log.error(f"  X BigQuery Upload failed for {table_name}: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#  BIGQUERY LOG INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════
def fetch_all_symbols(client):
    log.info("Fetching symbols from BigQuery master table...")
    query = f"SELECT nse_symbol as symbol, company_name, isin FROM `{BQ_MASTER_STOCKS_TABLE}` WHERE nse_symbol IS NOT NULL;"
    return client.query(query).to_dataframe().to_dict('records')

def _load_existing_status(client):
    client.query(f"""
        CREATE TABLE IF NOT EXISTS `{GCP_PROJECT_ID}.{BQ_DATASET}.fundamentals_log` (
            symbol STRING, company_name STRING, isin STRING, status STRING,
            data_source STRING, last_quarter STRING, error_message STRING, scraped_at TIMESTAMP
        )
    """).result()
    query = f"SELECT * FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.fundamentals_log`"
    df = client.query(query).to_dataframe()
    status_dict = {}
    for _, row in df.iterrows():
        d = row.to_dict()
        if pd.isna(d['last_quarter']): d['last_quarter'] = ""
        status_dict[d['symbol']] = d
    return status_dict

def flush_log_to_bq(client, status_records):
    table_id = f"{GCP_PROJECT_ID}.{BQ_DATASET}.fundamentals_log"
    staging_id = f"{table_id}_staging"
    
    df = pd.DataFrame(status_records)
    
    # FIX: Ensure the datetime is UTC timezone-aware so BigQuery accepts it as a TIMESTAMP
    df['scraped_at'] = pd.to_datetime(df['scraped_at'], errors='coerce', utc=True)
    
    job = client.load_table_from_dataframe(df, staging_id, job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"))
    job.result()
    
    merge_query = f"""
    MERGE `{table_id}` T
    USING `{staging_id}` S
    ON T.symbol = S.symbol
    WHEN MATCHED THEN
        UPDATE SET company_name=S.company_name, isin=S.isin, status=S.status, data_source=S.data_source, last_quarter=S.last_quarter, error_message=S.error_message, scraped_at=S.scraped_at
    WHEN NOT MATCHED THEN
        INSERT (symbol, company_name, isin, status, data_source, last_quarter, error_message, scraped_at)
        VALUES (S.symbol, S.company_name, S.isin, S.status, S.data_source, S.last_quarter, S.error_message, S.scraped_at)
    """
    client.query(merge_query).result()

# ═══════════════════════════════════════════════════════════════════════════════
#  BATCH SCRAPER
# ═══════════════════════════════════════════════════════════════════════════════
def batch_scrape(symbols, consolidated=True, delay=REQUEST_DELAY, flush_interval=FLUSH_INTERVAL, resume=True):
    existing_status = _load_existing_status(bq_client) if resume else {}
    remaining, skipped_count = [], 0

    if resume:
        for stock in symbols:
            sym = stock["symbol"]
            if sym in existing_status and existing_status[sym].get("status") == "success":
                if not should_scrape(existing_status[sym].get("last_quarter", "")):
                    skipped_count += 1; continue
            remaining.append(stock)
        log.info("Resume Mode: Skipped %d stocks (Up to date). %d remaining.", skipped_count, len(remaining))
    else: remaining = symbols

    if not remaining: return log.info("All stocks up-to-date! Nothing to scrape.")

    all_data, status_records = {}, []
    total, scraped_count, failed_count, batch_count = len(remaining), 0, 0, 0

    for i, stock in enumerate(remaining):
        symbol = stock["symbol"]
        log.info("[%d/%d] Scraping %s ...", i+1, total, symbol)
        
        sr = {"symbol": symbol, "company_name": stock.get("company_name", ""), "isin": stock.get("isin", ""), 
              "status": "pending", "data_source": "", "last_quarter": "", "error_message": "", "scraped_at": ""}
              
        try:
            data = scrape_company(symbol, consolidated=consolidated)
            if "error" in data: sr["status"], sr["error_message"], failed_count = "failed", data["error"], failed_count + 1
            else:
                sr.update({"status": "success", "data_source": data.get("type", ""), "last_quarter": get_last_quarter(data), "scraped_at": datetime.now().isoformat()})
                all_data[symbol] = data
                scraped_count += 1
        except Exception as e:
            sr["status"], sr["error_message"], failed_count = "error", str(e)[:200], failed_count + 1

        status_records.append(sr)
        batch_count += 1

        if batch_count >= flush_interval or (i+1) == total:
            log.info("\n>> FLUSHING: %d ok, %d failed to BigQuery (batch #%d)", scraped_count, failed_count, (i+1)//flush_interval+1)
            flush_log_to_bq(bq_client, status_records)
            if all_data: export_combined_to_bq(all_data, bq_client)
            status_records, all_data, batch_count = [], {}, 0
            log.info("")

        if (i+1) < total: time.sleep(delay)

    log.info("\nBATCH COMPLETE — %d succeeded, %d failed out of %d attempted.", scraped_count, failed_count, total)

# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Batch scrape NSE stocks from BigQuery → Screener.in")
    parser.add_argument("symbols", nargs="*", help="Optional specific symbols")
    parser.add_argument("--limit", type=int, default=0, help="Limit stocks (0=all)")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY, help="Delay between requests (default: 2s)")
    parser.add_argument("--flush", type=int, default=FLUSH_INTERVAL, help="Flush every N stocks (default: 50)")
    parser.add_argument("--standalone", action="store_true", help="Use standalone financials")
    parser.add_argument("--no-resume", action="store_true", help="Force re-scrape ignoring quarter check")
    args = parser.parse_args()

    all_symbols = [{"symbol": s.upper(), "company_name": "", "isin": ""} for s in args.symbols] if args.symbols else fetch_all_symbols(bq_client)
    if args.limit > 0: all_symbols = all_symbols[:args.limit]

    print(f"\n  Stocks Target: {len(all_symbols)} | Mode: {'Standalone' if args.standalone else 'Consolidated'}")
    print(f"  Delay: {args.delay}s | Flush: every {args.flush} | Resume/Quarter Check: {'Off' if args.no_resume else 'On'}\n")

    batch_scrape(all_symbols, consolidated=not args.standalone, delay=args.delay, flush_interval=args.flush, resume=not args.no_resume)

if __name__ == "__main__": main()