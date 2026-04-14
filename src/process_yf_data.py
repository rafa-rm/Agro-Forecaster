import boto3
import pandas as pd
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from botocore.config import Config
import json


MAX_WORKERS = 50

my_config = Config(
    max_pool_connections=MAX_WORKERS + 5,  
    retries={'max_attempts': 3}            
)

s3 = boto3.client('s3', config=my_config)
BUCKET_NAME = os.environ['S3_BUCKET_NAME']
MASTER_KEY = "trusted/agro_master_table.parquet"
lambda_client = boto3.client('lambda')

def cleanup_tmp():
    """Safely removes all files from /tmp without deleting the folder itself."""
    folder = '/tmp'
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"⚠️ Failed to delete {file_path}. Reason: {e}")

def process_single_key(key: str, prefix_name: str) -> pd.DataFrame:
    """
    Downloads and processes a single Parquet file given its Key (String).
    """
    if not key.endswith('.parquet'):
        print(f"⚠️ Skipping non-parquet file: {key}")
        return None

    local_path = f"/tmp/{key.replace('/', '_')}"
    try:
        s3.download_file(BUCKET_NAME, key, local_path)
        df = pd.read_parquet(local_path)
        if 'Date' not in df.columns:
            print(f"⚠️ 'Date' column missing in {key}. Skipping file.")
            return None
        df['Date'] = df['Date'].astype(str)
        if set(['Open', 'High', 'Low']).issubset(df.columns):
            df['Open'] = df['Open'].replace(0, pd.NA) 
            df['Volatility'] = (df['High'] - df['Low']) / df['Open']
        else:
            df['Volatility'] = 0.0
        
        df = df[['Date', 'Close', 'Volatility']]
        df.columns = ['Date', f'{prefix_name}_Close', f'{prefix_name}_Volatility']
        return df
    except Exception as e:
        print(f"Error processing file {key}: {e}")
        return None
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)

def process_file_list(file_keys: list, prefix_name: str) -> pd.DataFrame:
    if not file_keys:
        return pd.DataFrame()
    
    print(f"   Processing {len(file_keys)} files for {prefix_name}...")
    all_dfs = []
    
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = executor.map(lambda key: process_single_key(key, prefix_name), file_keys)
            for res in results:
                if res is not None and not res.empty:
                    all_dfs.append(res)

            print(f"Finished. Processed {len(file_keys)} items.")
    except Exception as e:
        print(f"Error during parallel upload for {prefix_name}: {e}")
        return pd.DataFrame()
    if not all_dfs:
        print(f"❌ No data found for {prefix_name}")
        return pd.DataFrame() 
    
    # Combine all partitions for this commodity
    full_df = pd.concat(all_dfs, ignore_index=True)
    # Remove duplicates if any
    full_df = full_df.drop_duplicates(subset=['Date'])
    # Set Date as Index for the final Merge step
    full_df.set_index('Date', inplace=True)

    return full_df


def load_current_master() -> pd.DataFrame:
    """Downloads the existing Master Table from S3."""
    path = "/tmp/current_master.parquet"
    try:
        s3.download_file(BUCKET_NAME, MASTER_KEY, path)
        df = pd.read_parquet(path)
        
        # Ensure Master also treats Date as String
        df['Date'] = df['Date'].astype(str)
        df.set_index('Date', inplace=True)
        
        print(f"📖 Loaded Master Table: {len(df)} rows.")
        return df
    except Exception:
        print("⚠️ No existing Master Table found. Starting fresh.")
        return pd.DataFrame()

def lambda_handler(event, context):
    print("Starting Trusted layer ETL...")
    cleanup_tmp()
    try:
        # 1. Get the manifest
        manifest_key = event.get('manifest_key')
        if manifest_key:
            print(f"📥 Loading manifest from {manifest_key}...")
            obj = s3.get_object(Bucket=BUCKET_NAME, Key=manifest_key)
            all_files_list = json.loads(obj['Body'].read())
        else:
            print("⚠️ No manifest provided. Exiting.")
            return {"statusCode": 200, "body": "No data to process"}
        
        # 2. Group Files by Commodity
        commodities_map = {
            "soybean": "soy", "corn": "corn", "wheat": "wheat", 
            "oil": "oil", "usd_brl": "usdbrl"
        }
        grouped_files = {k: [] for k in commodities_map.keys()}
        
        for file_key in all_files_list:
            for comm_name in commodities_map.keys():
                if f"raw/{comm_name}/" in file_key:
                    grouped_files[comm_name].append(file_key)
                    break

        # 3. Process new data
        dfs_new_batch = []
        for comm_name, prefix in commodities_map.items():
            keys = grouped_files.get(comm_name, [])
            if keys:
                df_comm = process_file_list(keys, prefix)
                if not df_comm.empty:
                    dfs_new_batch.append(df_comm)
        
        # 3. Merge DataFrames
        if not dfs_new_batch:
            print("No data to merge. Exiting.")
            return {"statusCode": 500, "body": "No valid data extracted."}

        print("Merging data...")
        df_delta = pd.concat(dfs_new_batch, axis=1, join='outer')
        df_master = load_current_master()

        if df_master.empty:
            df_final = df_delta
        else:
            df_combined = pd.concat([df_master, df_delta])
            df_final = df_combined.groupby(df_combined.index).last()

        # 4. Sort, Reindex, and Fill Missing Values

        df_final.index = pd.to_datetime(df_final.index)
        df_final.sort_index(inplace=True)

        full_date_range = pd.date_range(start=df_final.index.min(), 
                                        end=df_final.index.max(), 
                                        freq='D') # 'D' stands for Daily frequency
        
        # This explicitly injects empty rows for weekends and holidays!
        df_final = df_final.reindex(full_date_range)

        df_final.ffill(inplace=True)

        # If there are still missing values at the beginning of the dataset, backfill them
        df_final.bfill(inplace=True)

        df_final.index.name = 'Date'
        df_final.reset_index(inplace=True)
        df_final['Date'] = df_final['Date'].astype(str)

        # 5. Save to CSV and upload to S3
        output_path = "/tmp/agro_master_table.parquet"
        print(f"💾 Saving {len(df_final)} rows to {output_path}...")
        df_final.to_parquet(output_path, index=False)

        s3_key = "trusted/agro_master_table.parquet"
        s3.upload_file(output_path, BUCKET_NAME, s3_key)
        print(f"✅ Uploaded cleaned data to s3://{BUCKET_NAME}/{s3_key}")


        next_lambda_name = 'agro-data-enricher' 
    
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
            "body": json.dumps("Trusted finished, Enriched triggered.")
        }
    except Exception as e:
        print(f"❌ Error: {e}")
        return {
            "statusCode": 500,
            "body": f"Error processing data: {e}"
        }
    finally:
        print("Cleaning up /tmp...")
        cleanup_tmp()