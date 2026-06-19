import os
import json
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
    
    # ==========================================
    # 🔁 STEP 1: ADAPT & UPLOAD MINMAX SCALERS
    # ==========================================
    print("\nSynchronizing Scaler Parameters...")
    for commodity in commodities:
        local_scaler_path = os.path.join("saved_scalers", commodity, "scaler_params.json")
        
        s3_scaler_key = f"saved_scalers/{commodity.lower()}_scaler_params.json"
        
        if os.path.exists(local_scaler_path):
            try:
                print(f"🔄 Reshaping and uploading scaler parameters for {commodity}...")
                
                with open(local_scaler_path, 'r') as f:
                    local_params = json.load(f)
                
                lambda_compatible_params = {
                    "min": local_params["data_min_"],
                    "max": local_params["data_max_"],
                    "columns": [f"{commodity.lower()}_Close"]
                }
                
                temp_upload_path = "temp_lambda_scaler.json"
                with open(temp_upload_path, 'w') as f:
                    json.dump(lambda_compatible_params, f)
                
                s3_client.upload_file(temp_upload_path, bucket_name, s3_scaler_key)
                print(f"   ✅ Scaler successfully adapted & saved to s3://{bucket_name}/{s3_scaler_key}")
                
                if os.path.exists(temp_upload_path):
                    os.remove(temp_upload_path)
                    
            except Exception as e:
                print(f"   ❌ Error uploading {commodity} scaler: {e}")
        else:
            print(f"⚠️ Warning: Scaler parameters not found at {local_scaler_path}. Skipping.")


    # ==========================================
    # 🔁 STEP 2: CONVERT & UPLOAD LITERT MODELS
    # ==========================================
    print("\nSynchronizing LiteRT Models...")
    s3_prefix = "deployable_models/" 

    for commodity in commodities:
        for window in windows:
            experiment_name = f"{commodity}_{window}"
            local_path = os.path.join("models", "production", experiment_name, "best_model.keras")
            
            if not os.path.exists(local_path):
                print(f"⚠️ Warning: Model not found at {local_path}. Skipping.")
                continue
            
            print(f"🔄 Converting {experiment_name} to LiteRT format...")
            tflite_local_path = local_path.replace(".keras", ".tflite")
            
            try:
                # 1. Load the local Keras model
                model = tf.keras.models.load_model(local_path)
                
                # 2. Extract operational dimensions safely
                lookback = window
                first_layer = model.layers[0]
                
                if hasattr(first_layer, 'kernel'):
                    weights_shape = first_layer.kernel.shape
                    features = weights_shape[1] if len(weights_shape) == 3 else weights_shape[0]
                else:
                    features = 1
                
                # 3. Freeze batch size to 1 using a concrete trace function
                @tf.function
                def run_inference(tensor_input):
                    return model(tensor_input)

                concrete_func = run_inference.get_concrete_function(
                    tf.TensorSpec(shape=[1, lookback, features], dtype=tf.float32)
                )
                
                # 4. Pass the static concrete graph to the converter
                converter = tf.lite.TFLiteConverter.from_concrete_functions([concrete_func])
                converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
                converter._experimental_lower_tensor_list_ops = True
                
                tflite_model = converter.convert()
                
                # 5. Save the temporary local .tflite file
                with open(tflite_local_path, "wb") as f:
                    f.write(tflite_model)
                
                s3_key = f"{s3_prefix}{experiment_name}/best_model.tflite"
                
                print(f"☁️ Uploading {experiment_name} (Shape: [1, {lookback}, {features}])...")
                s3_client.upload_file(tflite_local_path, bucket_name, s3_key)
                print(f"   ✅ Successfully saved to s3://{bucket_name}/{s3_key}")
                                
            except Exception as e:
                print(f"   ❌ Error uploading {experiment_name}: {e}")
            
            finally:
                if os.path.exists(tflite_local_path):
                    os.remove(tflite_local_path)

    print("\nAll pipeline execution files have been synchronized with AWS S3!")

if __name__ == "__main__":
    upload_production_models()