import json
import os
import boto3
import requests
import pandas as pd
from io import BytesIO, StringIO
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import yfinance as yf
from botocore.config import Config

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
MAX_WORKERS = 50 

my_config = Config(
    max_pool_connections=50,
    retries = {'max_attempts': 3}
)
s3 = boto3.client('s3', config=my_config)
bucket_name = os.environ['S3_BUCKET_NAME']

lambda_client = boto3.client('lambda')


def upload_single_row(name: str, row):
    
    single_data = pd.DataFrame([row])
    date_row = row['Date']
    single_data['Date'] = date_row.strftime('%Y-%m-%d')
    S3_PATH = f"raw/{name}/" + f"year={date_row.year}/month={date_row.month}/day={date_row.day}/data.parquet"
    out_buffer = BytesIO()
    single_data.to_parquet(out_buffer, index=False, engine='fastparquet', compression='snappy')

    try:
        s3.put_object(Bucket=bucket_name, Key=S3_PATH, Body=out_buffer.getvalue())
        return f"✅ Uploaded {S3_PATH}"
    except Exception as e:
        return f"❌ Error {S3_PATH}: {str(e)}"

def process_historical_yahoo_data(name: str, symbol: str) -> bool:
    """
    Fetches historical data from Yahoo Finance based on the provided name and ID.
    Args:
        name (str): The name.
        symbol (str): The Yahoo Finance symbol.
    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        current_date = datetime.now().strftime('%Y-%m-%d')
        ticker = yf.Ticker(symbol)
        df = ticker.history(start="2010-01-01", interval="1d")

        if df.empty:
            print(f"⚠️ No data for {name}")
            return False
        
        df.reset_index(inplace=True)
        raw_data = df.copy()[['Date', 'Open', 'High', 'Low', 'Close']]
        
    except Exception as e:
        print(f"Error processing data for {name}: {e}")
        return False

    rows_to_process = [row for _, row in raw_data.iterrows()]
    
    print(f"Starting parallel upload of {len(rows_to_process)} records for {name}...")
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(lambda row: upload_single_row(name, row), rows_to_process))

        print(f"Finished. Processed {len(results)} items.")
        return True
    except Exception as e:
        print(f"Error during parallel upload for {name}: {e}")
        return False

def process_daily_yahoo_data(name: str, symbol: str) -> bool:
    """
    Fetches daily data from Yahoo Finance based on the provided name and ID.
    Args:
        name (str): The name.
        symbol (str): The Yahoo Finance symbol.
    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        ticker = yf.Ticker(symbol)
        # Get data for the last 5 days to ensure we have recent data
        # and to be fault-tolerant in case of weekends/holidays or
        # errors in data fetching on previous days.
        df = ticker.history(period="5d", interval="1d")

        if df.empty:
            print(f"⚠️ No data for {name}")
            return False
        
        df.reset_index(inplace=True)
        raw_data = df.copy()[['Date', 'Open', 'High', 'Low', 'Close']]
        
    except Exception as e:
        print(f"Error processing data for {name}: {e}")
        return False

    rows_to_process = [row for _, row in raw_data.iterrows()]
    
    print(f"Starting parallel upload of {len(rows_to_process)} records for {name}...")
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(lambda row: upload_single_row(name, row), rows_to_process))

        print(f"Finished. Processed {len(results)} items.")
        return True
    except Exception as e:
        print(f"Error during parallel upload for {name}: {e}")
        return False
    
def lambda_handler(event, context):

    tickers = [
        {"name": "soybean", "symbol": "ZS=F"},  # Soy Futures
        {"name": "corn", "symbol": "ZC=F"},     # Corn Futures
        {"name": "wheat", "symbol": "ZW=F"},      # Wheat Futures
        {"name": "usd_brl", "symbol": "BRL=X"},  # Dollar to Real Exchange Rate
        {"name": "oil", "symbol": "BZ=F"}        # Oil Futures (Macro/Energy)
    ]
    results = {}
    
    if event.get('mode') == 'historical':
        for ticker in tickers:
            success = process_historical_yahoo_data(ticker["name"], ticker["symbol"])
            results[ticker["name"]] = "Success" if success else "Failed"
    
    else:
        for ticker in tickers:
            success = process_daily_yahoo_data(ticker["name"], ticker["symbol"])
            results[ticker["name"]] = "Success" if success else "Failed"

    
    next_lambda_name = 'agro-data-processor' 
    
    print(f"Triggering {next_lambda_name}...")
    try:
        lambda_client.invoke(
            FunctionName=next_lambda_name,
            InvocationType='Event',  
            Payload=json.dumps({})  
        )
    except Exception as e:
        print(f"❌ Failed to trigger {next_lambda_name}: {e}")
        raise e

    return {
        "statusCode": 200, 
        "body": json.dumps("Raw finished, Trusted triggered.")
    }