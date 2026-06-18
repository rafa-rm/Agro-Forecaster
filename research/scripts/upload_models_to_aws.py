import os
import boto3
import tensorflow as tf
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
            
            print(f"🔄 Converting {experiment_name} to LiteRT format...")
            
            try:
                # 1. Load the local Keras model
                model = tf.keras.models.load_model(local_path)
                
                # 2. Convert to LiteRT (TFLite) using pure built-in operators
                converter = tf.lite.TFLiteConverter.from_keras_model(model)
                converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
                converter._experimental_lower_tensor_list_ops = True
                
                tflite_model = converter.convert()
                
                # 3. Create a temporary local .tflite file
                tflite_local_path = local_path.replace(".keras", ".tflite")
                with open(tflite_local_path, "wb") as f:
                    f.write(tflite_model)
                
                # 4. Target the updated .tflite path for your AWS Lambda
                s3_key = f"{s3_prefix}{experiment_name}/best_model.tflite"
                
                print(f"☁️ Uploading {experiment_name}...")
                s3_client.upload_file(tflite_local_path, bucket_name, s3_key)
                print(f"   ✅ Successfully saved to s3://{bucket_name}/{s3_key}")
                                
            except Exception as e:
                print(f"   ❌ Error uploading {experiment_name}: {e}")
            
            finally:
                if os.path.exists(tflite_local_path):
                    os.remove(tflite_local_path)

    print("\nAll specified production models have been synchronized with AWS S3!")

if __name__ == "__main__":
    upload_production_models()