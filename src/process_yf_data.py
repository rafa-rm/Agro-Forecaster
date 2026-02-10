import boto3
import pandas as pd
import os
import shutil

s3 = boto3.client('s3')
BUCKET_NAME = os.environ['S3_BUCKET_NAME']

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

def get_and_process_data(commodity_name: str, prefix_name: str) -> pd.DataFrame:
    """
    1. Lists all parquet files for a commodity (e.g., 'soybean').
    2. Downloads them to /tmp.
    3. Reads, Calculates Volatility, and Renames columns.
    """
    paginator = s3.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=BUCKET_NAME, Prefix=f"raw/{commodity_name}/")
    
    all_dfs = []
    for page in pages:
        if 'Contents' not in page:
            print(f"⚠️ No files found for {commodity_name}")
            continue

        for obj in page['Contents']:
            key = obj['Key']
            if not key.endswith('.parquet'):
                print(f"⚠️ Skipping non-parquet file: {key}")
                continue

            local_path = f"/tmp/{key.replace('/', '_')}"
            s3.download_file(BUCKET_NAME, key, local_path)
            try:
                df = pd.read_parquet(local_path)
                if 'Date' not in df.columns:
                    print(f"⚠️ 'Date' column missing in {key}. Skipping file.")
                    continue
                if 'Open' in df.columns and 'High' in df.columns and 'Low' in df.columns:
                    df['Open'] = df['Open'].replace(0, pd.NA) 
                    df['Volatility'] = (df['High'] - df['Low']) / df['Open']
                else:
                    df['Volatility'] = 0.0
                
                df = df[['Date', 'Close', 'Volatility']]
                df.columns = ['Date', f'{prefix_name}_Close', f'{prefix_name}_Volatility']
                all_dfs.append(df)
            except Exception as e:
                print(f"Error processing file {key}: {e}")
            finally:
                if os.path.exists(local_path):
                    os.remove(local_path)
    
    if not all_dfs:
        print(f"❌ No data found for {commodity_name}")
        return pd.DataFrame() 
    

    # Combine all partitions for this commodity
    full_df = pd.concat(all_dfs, ignore_index=True)
    
    # Remove duplicates if any
    full_df = full_df.drop_duplicates(subset=['Date'])
    
    # Set Date as Index for the final Merge step
    full_df.set_index('Date', inplace=True)


    return full_df
    

def lambda_handler(event, context):
    """ETL Process for Trusted Layer:
    1. For each commodity, list and download all raw parquet files.
    2. Process each file to calculate volatility and rename columns.
    3. Merge all commodities into a master DataFrame.
    4. Sort by Date and fill missing values.
    5. Save the final DataFrame as a parquet file and upload to S3.
    """
    print("Starting Trusted layer ETL...")

    try:
        # 1. Define commodities and their corresponding prefixes
        commodities = {
            "soybean": "soy", 
            "corn": "corn", 
            "wheat": "wheat", 
            "oil": "oil", 
            "usd_brl": "usdbrl"
        }

        dfs_to_merge = []

        # 2. Process each commodity
        for folder, prefix in commodities.items():
            df = get_and_process_data(folder, prefix)
            if not df.empty:
                dfs_to_merge.append(df)
        
        # 3. Merge DataFrames
        if not dfs_to_merge:
            print("No data to merge. Exiting.")
            return {"statusCode": 500, "body": "No data to merge."}

        print("Merging data...")
        master_df = pd.concat(dfs_to_merge, axis=1, join='outer')

        # 4. Sort and Fill Missing Values
        master_df.sort_index(inplace=True)

        # If weekend/holiday, use Friday's price
        master_df.ffill(inplace=True)

        # If there are still missing values at the beginning of the dataset, backfill them
        master_df.bfill(inplace=True)

        master_df.reset_index(inplace=True)

        # 5. Save to CSV and upload to S3
        output_path = "/tmp/agro_master_table.parquet"
        print(f"💾 Saving {len(master_df)} rows to {output_path}...")
        master_df.to_parquet(output_path, index=False)

        s3_key = "trusted/agro_master_table.parquet"
        s3.upload_file(output_path, BUCKET_NAME, s3_key)
        print(f"✅ Uploaded cleaned data to s3://{BUCKET_NAME}/{s3_key}")

        return {
            "statusCode": 200,
            "body": f"Successfully processed and uploaded master table with {len(master_df)} rows."
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