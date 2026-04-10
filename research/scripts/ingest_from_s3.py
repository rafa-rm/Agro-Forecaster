# src/ingest_from_s3.py
import os
import boto3

def download_medallion_data():
    print("Connecting to AWS S3...")
    s3_client = boto3.client('s3')
    
    bucket_name = os.getenv('AGRO_BUCKET_NAME')
    
    # Mapping the AWS S3 keys to your local Docker volume paths.
    files_to_sync = {
        'trusted/agro_master_table.parquet': 'data/trusted/agro_master_table.parquet',
        
        'enriched/agro_analytics_table.parquet': 'data/enriched/agro_analytics_table.parquet' 
    }
    
    for s3_key, local_path in files_to_sync.items():
        # Ensure the local directories exist inside the container
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        print(f"Downloading {s3_key} to {local_path}...")
        try:
            s3_client.download_file(bucket_name, s3_key, local_path)
            print(f"Successfully saved to {local_path}")
        except Exception as e:
            print(f"Error downloading {s3_key}: {e}")
        
    print("Medallion data successfully downloaded for local ML pipeline!")

if __name__ == "__main__":
    download_medallion_data()