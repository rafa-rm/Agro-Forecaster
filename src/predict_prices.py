import os
import json
import datetime
import boto3
import pandas as pd
import numpy as np
import ai_edge_litert.interpreter as litert

s3_client = boto3.client('s3')
BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
if not BUCKET_NAME:
    raise EnvironmentError("Missing required environment variable: S3_BUCKET_NAME")

def load_json_scaler_params(commodity):
    """Downloads and extracts your custom min-max scaling parameters from S3."""
    scaler_key = f"saved_scalers/{commodity.lower()}_scaler_params.json"
    local_scaler_path = f"/tmp/{commodity}_scaler.json"
    
    s3_client.download_file(BUCKET_NAME, scaler_key, local_scaler_path)
    with open(local_scaler_path, 'r') as f:
        return json.load(f)

def inverse_scale_predictions(scaled_preds, scaler_params):
    """Reverses your custom min-max calculation back to original currency prices."""
    min_val = scaler_params['min'][0]
    max_val = scaler_params['max'][0]
    # Works seamlessly with multi-step NumPy arrays via array broadcasting
    return scaled_preds * (max_val - min_val) + min_val

def lambda_handler(event, context):
    print("🚀 Initiating serverless recursive time-series forecasting cycle using Silver Layer...")
    
    # 1. Download the latest Trusted Silver Master Table from the Data Lake
    silver_data_key = "trusted/agro_master_table.parquet"
    local_data_path = "/tmp/silver_data.parquet"
    s3_client.download_file(BUCKET_NAME, silver_data_key, local_data_path)
    df = pd.read_parquet(local_data_path)
    
    commodities = ["Corn", "Wheat", "Soy"]
    windows = [7, 30] # Dictates both lookback window config and forecasting steps
    forecast_results = []

    # 2. Iterate through the Model Evaluation Matrix
    for commodity in commodities:
        try:
            scaler_params = load_json_scaler_params(commodity)
            feature_columns = list(scaler_params['columns'])
        except Exception as e:
            print(f"❌ Failed loading scalar metadata for {commodity}: {e}")
            continue
        
        for window in windows:
            experiment_name = f"{commodity}_{window}"
            model_key = f"deployable_models/{experiment_name}/best_model.tflite"
            local_model_path = f"/tmp/{experiment_name}.tflite"
            
            try:
                # Download the target model FlatBuffer file from S3
                s3_client.download_file(BUCKET_NAME, model_key, local_model_path)
                
                # 3. Mount the model into the LiteRT Interpreter runtime
                interpreter = litert.Interpreter(model_path=local_model_path)
                interpreter.allocate_tensors()
                
                input_details = interpreter.get_input_details()
                output_details = interpreter.get_output_details()
                
                # Extract structural shape expectations from the compiled model
                lookback_window = input_details[0]['shape'][1] 
                features = input_details[0]['shape'][2]
                
                # 4. Isolate and slice the seed time-series sequence from the Silver table
                if 'commodity' in df.columns:
                    commodity_df = df[df['commodity'] == commodity.lower()].sort_index()
                else:
                    commodity_df = df.sort_index()
                
                scaled_features = commodity_df[feature_columns].tail(lookback_window).values
                
                # Check to confirm the dataframe has enough historical depth for the sequence lookback
                if len(scaled_features) < lookback_window:
                    print(f"⚠️ Insufficient lookback rows in Silver data for {experiment_name}. Skipping.")
                    continue
                
                # Initialize seed sequence loop array with shape: (1, lookback_window, features)
                current_seq = np.expand_dims(scaled_features, axis=0).astype(np.float32)
                
                # ==========================================
                # 🔄 5. RECURSIVE INFERENCE LOOP (NumPy Driven)
                # ==========================================
                preds_scaled = []
                steps = window # Predict forward 7 or 30 steps matching your execution strategy
                
                for _ in range(steps):
                    # Inject current context array and execute model
                    interpreter.set_tensor(input_details[0]['index'], current_seq)
                    interpreter.invoke()
                    next_pred = interpreter.get_tensor(output_details[0]['index']) # Shape: (1, 1)
                    
                    # Store step result
                    preds_scaled.append(next_pred[0, 0])
                    
                    # Reshape prediction to fit concatenation layout: (1, 1, 1)
                    next_pred_reshaped = np.reshape(next_pred, (1, 1, 1))
                    
                    # Core Loop Step: Slice off oldest step index [:, 1:, :] and append fresh forecast array
                    current_seq = np.concatenate([current_seq[:, 1:, :], next_pred_reshaped], axis=1)
                
                # ==========================================
                # ⚖️ 6. INVERSE TRANSFORM RESULTS
                # ==========================================
                preds_scaled_arr = np.array(preds_scaled).reshape(-1, 1)
                actual_predictions = inverse_scale_predictions(preds_scaled_arr, scaler_params)
                
                forecast_results.append({
                    "commodity": commodity,
                    "horizon_days": window,
                    "forecast_values": actual_predictions.flatten().tolist(),
                    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                })
                print(f"✅ Generated valid {steps}-day recursive prediction array for {experiment_name}")
                
            except Exception as e:
                print(f"❌ Failed processing sequence for {experiment_name}: {e}")

    # 7. Execute Hybrid Storage Pattern Upload
    local_output_path = "/tmp/predictions.json"
    with open(local_output_path, 'w') as f:
        json.dump(forecast_results, f, indent=4)
        
    # Destination A: Overwrite static dashboard path
    static_key = "forecasts/latest_commodity_predictions.json"
    s3_client.upload_file(local_output_path, BUCKET_NAME, static_key)
    print(f"📡 Production Dashboard asset updated: s3://{BUCKET_NAME}/{static_key}")
    
    # Destination B: Append to date-partitioned historical record
    execution_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    historical_key = f"forecasts/historical/execution_date={execution_date}/predictions.json"
    s3_client.upload_file(local_output_path, BUCKET_NAME, historical_key)
    print(f"💾 Historical audit logs archived: s3://{BUCKET_NAME}/{historical_key}")
    
    return {
        'statusCode': 200,
        'body': json.dumps('Serverless recursive inference cycle concluded successfully!')
    }