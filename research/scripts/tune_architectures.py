import json
import re

import pandas as pd
import numpy as np
import tomllib
import itertools
import mlflow
import random
import os

from sklearn.preprocessing import MinMaxScaler

import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Input, Conv1D, AveragePooling1D, LSTM, Dense, Flatten
from tensorflow.keras.regularizers import l2
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from tensorflow.keras.losses import Huber

# ==========================================
# 0. GENERAL UTILITIES
# ==========================================

def set_global_determinism(seed=42, init_tf_config=False):
    """
    Configures a fixed seed across multiple libraries to ensure reproducibility.

    Parameters:
    ----------
    seed : int, optional
        The seed value used for random number generators. Defaults to 42.
    """
    os.environ['PYTHONHASHSEED'] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    tf.random.set_seed(seed)
    tf.keras.utils.set_random_seed(seed)
    if init_tf_config:
        tf.config.experimental.enable_op_determinism()

def sanitize_filename(name):
    """Removes any characters that aren't alphanumeric, dashes, or underscores."""
    return re.sub(r'[^a-zA-Z0-9_\-]', '', str(name))

# ==========================================
# 1. CUSTOM VALIDATION LOGIC
# ==========================================
class RecursiveRMSECallback(tf.keras.callbacks.Callback):
    def __init__(self, val_initial_seqs, val_true_horizons, steps=30, batch_size=256):
        super(RecursiveRMSECallback, self).__init__()
        self.val_initial_seqs = tf.cast(val_initial_seqs, tf.float32)
        self.val_true_horizons = tf.cast(val_true_horizons, tf.float32)
        self.steps = steps
        self.batch_size = batch_size

    def on_train_begin(self, logs=None):
        @tf.function
        def _fast_forecast_batch(initial_seq_batch):
            current_seq = initial_seq_batch
            predictions = tf.TensorArray(tf.float32, size=self.steps)
            for i in tf.range(self.steps):
                next_pred = self.model(current_seq, training=False) 
                predictions = predictions.write(i, next_pred)
                next_pred_reshaped = tf.expand_dims(next_pred, axis=1)
                current_seq = tf.concat([current_seq[:, 1:, :], next_pred_reshaped], axis=1)
            return tf.transpose(tf.squeeze(predictions.stack(), axis=-1), perm=[1, 0])
        
        self.fast_forecast_batch = _fast_forecast_batch

    def on_epoch_end(self, epoch, logs=None):
        logs = logs or {}
        
        # REFACTOR: Batch the validation set to prevent GPU OOM crashes
        dataset = tf.data.Dataset.from_tensor_slices(self.val_initial_seqs).batch(self.batch_size)
        all_preds = []
        
        for batch in dataset:
            batch_preds = self.fast_forecast_batch(batch)
            all_preds.append(batch_preds)
            
        recursive_preds = tf.concat(all_preds, axis=0)
        
        mse = tf.reduce_mean(tf.square(self.val_true_horizons - recursive_preds))
        rmse = tf.sqrt(mse)
        logs['val_recursive_rmse'] = rmse.numpy()
        
        if mlflow.active_run():
            mlflow.log_metric('val_recursive_rmse', logs['val_recursive_rmse'], step=epoch)
        

# ==========================================
# 2. DATA PROCESSING
# ==========================================

def load_data(file_path):
    df = pd.read_parquet(file_path)
    return df

def create_sequences(data, target_idx, time_steps=7, forecast_horizon=1):
    X, y = [], []
    for i in range(len(data) - time_steps - forecast_horizon + 1):
        X.append(data[i : i + time_steps, :])
        y.append(data[i + time_steps + forecast_horizon - 1, target_idx]) 
    return np.array(X), np.array(y)

def create_recursive_validation_data(scaled_data, time_steps, horizon_steps):
    X_val_recursive = []
    y_val_recursive = []
    for i in range(len(scaled_data) - time_steps - horizon_steps + 1):
        X_val_recursive.append(scaled_data[i : i + time_steps, :])
        y_val_recursive.append(scaled_data[i + time_steps : i + time_steps + horizon_steps, 0])
    return np.array(X_val_recursive), np.array(y_val_recursive)

def create_train_test_data(df, all_cols, time_steps, horizon_steps=30, train_pct=0.80, val_pct=0.10, target_col=None):
    train_size = int(len(df) * train_pct)
    val_size = int(len(df) * val_pct)
    
    # Split the raw DataFrames
    train_df = df.iloc[:train_size][all_cols]
    val_df = df.iloc[train_size : train_size + val_size][all_cols]
    test_df = df.iloc[train_size + val_size:][all_cols]

    scaler = MinMaxScaler(feature_range=(0, 1))
    train_scaled = scaler.fit_transform(train_df)


    # ---------- Saving Scaler for Future Use ----------
    if target_col is not None:
        folder_name = sanitize_filename(target_col.split('_')[0])
        save_dir = os.path.join("saved_scalers", folder_name)
        os.makedirs(save_dir, exist_ok=True)
        
        # Extract attributes and convert NumPy arrays to lists for JSON
        scaler_params = {
            "min_": scaler.min_.tolist(),
            "scale_": scaler.scale_.tolist(),
            "data_min_": scaler.data_min_.tolist(),
            "data_max_": scaler.data_max_.tolist(),
            "feature_range": scaler.feature_range
        }
        
        scaler_path = os.path.join(save_dir, "scaler_params.json")
        with open(scaler_path, "w") as f:
            json.dump(scaler_params, f, indent=4)
            
        print(f"Scaler parameters saved successfully to: {scaler_path}")
    
    val_scaled = scaler.transform(val_df)
    test_scaled = scaler.transform(test_df)

    target_idx = 0 

    # Create standard sequences (1-step ahead) for Training
    X_train, y_train = create_sequences(train_scaled, target_idx, time_steps=time_steps)
    
    # Create standard sequences for the Final Test Set
    X_test, y_test = create_sequences(test_scaled, target_idx, time_steps=time_steps)
    
    # 6. Create Recursive sequences from the validation Set
    # This guarantees the callback never sees the test data
    X_val_rec, y_val_rec = create_recursive_validation_data(val_scaled, time_steps, horizon_steps)

    return X_train, y_train, X_val_rec, y_val_rec, X_test, y_test

# ==========================================
# 3. MODEL ARCHITECTURE & TRAINING
# ==========================================

def build_and_compile_model(input_shape, learning_rate=0.001, cnn_filters=None, lstm_units=None, dense_units=None):
    model = Sequential()
    model.add(Input(shape=input_shape, name='Input_Layer'))
    reg = l2(1e-4)

    if cnn_filters:
        model.add(Conv1D(filters=cnn_filters, kernel_size=3, activation='relu', kernel_regularizer=reg, name='Conv1D_Layer'))
        model.add(AveragePooling1D(pool_size=2, name='AvgPooling_Layer')) 

    if lstm_units:
        model.add(LSTM(units=lstm_units, return_sequences=False, kernel_regularizer=reg, name='LSTM_Layer'))
    else:
        model.add(Flatten(name='Flatten_Layer'))

    if dense_units:
        model.add(Dense(units=dense_units, activation='relu', kernel_regularizer=reg, name='First_Dense_Layer'))
        model.add(Dense(16, activation='relu', kernel_regularizer=reg, name='Second_Dense_Layer'))

    model.add(Dense(1, name='Output_Layer'))

    model.compile(
        optimizer=Adam(learning_rate=learning_rate), 
        loss=Huber(), 
        metrics=['mae']
    )
    return model

def train_model(model, X_train, y_train, X_val_rec, y_val_rec, experiment_config, horizon_steps, model_name, target_col, time_steps):
    # 1. Sanitize the inputs to prevent path traversal
    safe_target = sanitize_filename(target_col)
    safe_time_steps = sanitize_filename(time_steps)
    safe_model_name = sanitize_filename(model_name)
    
    # 2. Use the safe variables to construct the directory path
    save_dir = f'models/commodity_{safe_target}__window_{safe_time_steps}/'
    os.makedirs(save_dir, exist_ok=True)

    # 3. Instantiate the custom callback
    recursive_callback = RecursiveRMSECallback(
        val_initial_seqs=X_val_rec, 
        val_true_horizons=y_val_rec, 
        steps=horizon_steps,
        batch_size=experiment_config.get('batch_size', 256)
    )

    # 4. Point EarlyStopping to the new recursive metric
    early_stop = EarlyStopping(
        monitor='val_recursive_rmse', 
        patience=25, 
        restore_best_weights=True,
        mode='min'
    )

    # 5. Point Checkpoint to the new recursive metric and use safe paths
    checkpoint = ModelCheckpoint(
        filepath=os.path.join(save_dir, f'best_model_{safe_model_name}.keras'),
        monitor='val_recursive_rmse',
        save_best_only=True,
        mode='min'
    )

    ordered_callbacks = [recursive_callback, early_stop, checkpoint]
    
    history = model.fit(
        X_train, y_train,
        epochs=experiment_config['epochs'],
        batch_size=experiment_config['batch_size'],
        callbacks=ordered_callbacks, 
        verbose=0 
    )

    return history

def create_model_name(params):
    name_parts = []
    for key, value in params.items():
        name_parts.append(f"{key}_{value}")
    return "_".join(name_parts)

# ==========================================
# 4. EXECUTION PIPELINE
# ==========================================
if __name__ == "__main__":
    set_global_determinism(seed=42, init_tf_config=True)
    with open("config.toml", "rb") as f:
        config = tomllib.load(f)

    experiment_config = config['experiment']
    tuning_grid = config['hyperparameters']

    targets_col = experiment_config['targets']
    time_steps_list = experiment_config['time_steps']
    horizon_steps = experiment_config['horizon_steps']

    df = load_data('data/trusted/agro_master_table.parquet')

    for target_col in targets_col:
        for time_steps in time_steps_list:

            all_cols = [target_col]
            
            # Unpack the new recursive validation arrays
            X_train, y_train, X_val_rec, y_val_rec, X_test, y_test = create_train_test_data(
                df, all_cols, time_steps, horizon_steps=horizon_steps, 
                train_pct=experiment_config['train_percentage'], 
                val_pct=experiment_config['validation_percentage'],
                target_col=target_col
            )

            keys = tuning_grid.keys()
            values = tuning_grid.values()
            hyper_combinations = [dict(zip(keys, combo)) for combo in itertools.product(*values)]


            # SECURITY WARNING: Ensure the target URL is HTTPS and requires authentication if 
            # deployed publicly in AWS. For local testing, the default is set to localhost:5000 which is safe.
            mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
            mlflow.set_tracking_uri(mlflow_uri)
            mlflow.set_experiment(f"Agro_Forecaster_Ablation_Study_Commodity_{target_col.split('_')[0]}_TimeSteps_{time_steps}")

            for params in hyper_combinations:
                model_name = create_model_name(params)
                
                with mlflow.start_run(run_name=f"Run_{model_name}"):
                    mlflow.log_param("target", target_col.split('_')[0])
                    mlflow.log_param("time_steps", time_steps)
                    mlflow.log_param("horizon_steps", horizon_steps)
                    mlflow.log_param("epochs", experiment_config['epochs'])
                    mlflow.log_param("batch_size", experiment_config['batch_size'])
                    mlflow.log_param("train_percentage", experiment_config['train_percentage'])
                    mlflow.log_param("validation_percentage", experiment_config['validation_percentage'])
                    mlflow.log_params(params)
                    
                    print(f"\nBuilding model with: {params}")
                    
                    # Always set global determinism at the start of each run to ensure reproducibility across different hyperparameter combinations
                    set_global_determinism(seed=42)

                    model = build_and_compile_model(
                        input_shape=(time_steps, X_train.shape[2]),
                        **params 
                    )
                    
                    # Pass the recursive arrays into the train function
                    history = train_model(
                        model, X_train, y_train, X_val_rec, y_val_rec, 
                        experiment_config, horizon_steps, model_name, 
                        target_col=target_col.split('_')[0],
                        time_steps=time_steps
                    )
                    
                    safe_registry_target = sanitize_filename(target_col.split('_')[0])
                    safe_registry_model = sanitize_filename(model_name)

                    mlflow.keras.log_model(
                        model, 
                        name="model", 
                        registered_model_name=f"AgroForecaster_{safe_registry_target}_{safe_registry_model}" 
                    )
                    
                    # Log the best recursive RMSE achieved during this run
                    best_rmse = min(history.history['val_recursive_rmse'])
                    mlflow.log_metric("best_val_recursive_rmse", best_rmse)
                    
                    print(f"✅ Run finished. Best Recursive RMSE: {best_rmse:.4f}")
                    tf.keras.backend.clear_session()