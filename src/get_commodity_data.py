import json
import os
import boto3
import requests
import pandas as pd
from bs4 import BeautifulSoup
from io import BytesIO
from datetime import datetime
import xlrd
from concurrent.futures import ThreadPoolExecutor

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
MAX_WORKERS = 50  
s3 = boto3.client('s3')
bucket_name = os.environ['S3_BUCKET_NAME']


def get_cepea_historical_table_url(commodity_name: str, commodity_id: str) -> str:
    """
    Fetches the URL of the historical data table for a given CEPEA commodity.

    Args:
        commodity_name (str): The name of the commodity.
        commodity_id (str): The ID of the commodity.
    
    Returns:
        str: The URL of the historical data table.
    """
    base_url = f"https://www.cepea.org.br/br/indicador/{commodity_name.lower()}.aspx"

    response = requests.get(base_url, headers=HEADERS)
    soup = BeautifulSoup(response.content, 'html.parser')
    target_link = soup.find('a', href=lambda href: href and f"id={commodity_id}" in href)
    if target_link and 'href' in target_link.attrs:
        return target_link['href']
    else:
        raise ValueError(f"Historical data table URL not found for {commodity_name}.")

def upload_single_row(commodity_name: str, row):
    
    single_data = pd.DataFrame([row])
    date_row = row['Data']
    S3_PATH = f"raw/{commodity_name}/" + f"year={date_row.year}/month={date_row.month}/day={date_row.day}/data.parquet"

    out_buffer = BytesIO()
    single_data.to_parquet(out_buffer, index=False, engine='fastparquet', compression='snappy')

    try:
        s3.put_object(Bucket=bucket_name, Key=S3_PATH, Body=out_buffer.getvalue())
        return f"✅ Uploaded {S3_PATH}"
    except Exception as e:
        return f"❌ Error {S3_PATH}: {str(e)}"

def process_historical_commodity_data(commodity_name: str, commodity_id: str) -> bool:
    """
    Fetches CEPEA commodity data based on the provided commodity name and ID
    and processes it.

    Args:
        commodity_name (str): The name of the commodity.
        commodity_id (str): The ID of the commodity.
    
    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        table_url = get_cepea_historical_table_url(commodity_name, commodity_id)
        if not table_url.startswith('http'):
            table_url = "https://www.cepea.org.br" + table_url

        response = requests.get(table_url, headers=HEADERS)


        # The files from CEPEA seem to be corrupted in some way (the workbook structure is broken),
        # For that, it is necessary to use xlrd with ignore_workbook_corruption=True
        workbook = xlrd.open_workbook(
            file_contents=response.content, 
            ignore_workbook_corruption=True
        )

        sheet = workbook.sheet_by_index(0)

        data = []

        # Begin from row index 3 to skip headers
        for row_idx in range(3, sheet.nrows):
            data.append(sheet.row_values(row_idx))
        
        print(data)
        headers = data[0]
        data = data[1:]  

        raw_commodity_data = pd.DataFrame(data, columns=headers)
        raw_commodity_data['Data'] = pd.to_datetime(raw_commodity_data['Data'], format='%d/%m/%Y', errors='coerce')
        print(raw_commodity_data)
        
    except Exception as e:
        print(f"Error processing data for {commodity_name}: {e}")
        return False

    #today_date = datetime.now().strftime('%Y-%m-%d')

    #raw_s3_key = f"commodity={commodity_name}/{today_date}_raw.csv"
    
    rows_to_process = [row for _, row in raw_commodity_data.iterrows()]
    
    print(f"Starting parallel upload of {len(rows_to_process)} records for {commodity_name}...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(lambda row: upload_single_row(commodity_name, row), rows_to_process))

    print(f"Finished. Processed {len(results)} items.")
    # Save raw data to S3
    '''try:
        s3 = boto3.client('s3')
        
        csv_buffer = BytesIO()
        raw_commodity_data.to_csv(csv_buffer, index=False)
        s3.put_object(Bucket=bucket_name, Key=raw_s3_key, Body=csv_buffer.getvalue())
        print(f"Raw data for {commodity_name} saved to s3://{bucket_name}/{raw_s3_key}")
        return True
    except Exception as e:
        print(f"Error saving {commodity_name} to S3: {e}")
        return False
    '''
def lambda_handler(event, context):
    commodities = [
        {"name": "soja", "id": "12"},
        {"name": "trigo", "id": "178"},
    ]

    results = {}
    
    if event.get('mode') == 'historical':
        for commodity in commodities:
            success = process_historical_commodity_data(commodity["name"], commodity["id"])
            results[commodity["name"]] = "Success" if success else "Failed"

    return {
        'statusCode': 200,
        'body': json.dumps(results)
    }