import os
import boto3
from dotenv import load_dotenv, find_dotenv

def upload_production_models():
    print("🚀 Connecting to AWS S3...")
    load_dotenv(find_dotenv())
    s3_client = boto3.client('s3')
    bucket_name = os.getenv('AGRO_BUCKET_NAME')
    
    if not bucket_name:
        print("❌ Error: AGRO_BUCKET_NAME environment variable is not set in .env.")
        return

    commodities = ["Corn", "Wheat", "Soy"]
    windows = [7, 30]
    
    s3_prefix = "deployable_models/" 

    for commodity in commodities:
        for window in windows:
            experiment_name = f"{commodity}_{window}"
            
            local_path = os.path.join("models", "production", experiment_name, "best_model.keras")
            
            if not os.path.exists(local_path):
                print(f"⚠️ Warning: Model not found at {local_path}. Skipping.")
                continue
            
            s3_key = f"{s3_prefix}{experiment_name}/best_model.keras"
            
            print(f"☁️ Uploading {experiment_name}...")
            
            try:
                s3_client.upload_file(local_path, bucket_name, s3_key)
                print(f"   ✅ Successfully saved to s3://{bucket_name}/{s3_key}")
            except Exception as e:
                print(f"   ❌ Error uploading {experiment_name}: {e}")

    print("\nAll specified production models have been synchronized with AWS S3!")

if __name__ == "__main__":
    upload_production_models()