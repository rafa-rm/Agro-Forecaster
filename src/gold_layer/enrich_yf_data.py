import pandas as pd
import numpy as np
import boto3
import os
from indicators import get_rsi

s3 = boto3.client('s3')
BUCKET_NAME = os.environ['S3_BUCKET_NAME']


def add_lags(df, lags=[1, 7, 14, 30]):
    """Adds lag features for all numeric columns."""
    print("... Adding Lags")
    target_cols = [c for c in df.columns if c.endswith('_Close') or c.endswith('_Volatility')]
    
    for col in target_cols:
        for lag in lags:
            df[f'{col}_lag_{lag}'] = df[col].shift(lag)
    return df

def add_rolling_features(df, windows=[7, 30]):
    """Adds rolling mean and standard deviation."""
    print("... Adding Rolling Stats")
    target_cols = [c for c in df.columns if c.endswith('_Close') or c.endswith('_Volatility')]
    
    for col in target_cols:
        for window in windows:
            df[f'{col}_rolling_mean_{window}'] = df[col].rolling(window=window).mean()
            df[f'{col}_rolling_std_{window}'] = df[col].rolling(window=window).std()
    return df

def add_technical_indicators(df, rsi=[7, 14]):
    """Adds RSI"""
    target_cols = [c for c in df.columns if c.endswith('_Close') or c.endswith('_Volatility')]

    for col in target_cols:
        for period in rsi:
            df[f'{col}_RSI_{period}'] = get_rsi(df[col], period=period)

    return df


def clean_nans(df):
    """Removes the empty rows created by Lags/Rolling."""
    return df.dropna()


def lambda_handler(event, context):
    print("🚀 Starting Feature Engineering...")
    
    local_path = "/tmp/agro_master_table.parquet"
    s3_key = "trusted/agro_master_table.parquet"
    # 1. Load Trusted Data 
    print(f"⬇️ Downloading {s3_key} to {local_path}...")
    s3.download_file(BUCKET_NAME, s3_key, local_path)
    df = pd.read_parquet(local_path)

    if 'Date' in df.columns:
        df = df.sort_values('Date')
    

    # 2. Configuration
    list_lags = [1, 7, 14, 30]
    list_windows = [7, 30]
    list_rsi = [7, 14]

    # 3. Pipeline 
    df_gold = (df
               .pipe(add_lags, lags=list_lags)
               .pipe(add_rolling_features, windows=list_windows)
               .pipe(add_technical_indicators, rsi=list_rsi)
               .pipe(clean_nans)
              )
              
    print(f"✅ Features Created. Final Shape: {df_gold.shape}")
    

    # 4. Save and Upload to S3
    output_path = "/tmp/enriched_agro_table.parquet"
    df_gold.to_parquet(output_path, index=False)
    s3_key = "enriched/agro_analytics_table.parquet"
    s3.upload_file(output_path, BUCKET_NAME, s3_key)
    print(f"✅ Uploaded Enriched data to s3://{BUCKET_NAME}/{s3_key}")
    
    return {"statusCode": 200, "body": "Success"}
