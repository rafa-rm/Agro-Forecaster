import os
import json
import datetime
import boto3
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from dotenv import load_dotenv

# Load local environment configurations
load_dotenv()
BUCKET_NAME = os.getenv('AGRO_BUCKET_NAME')

# Page settings
st.set_page_config(
    page_title="Agro-Forecaster Dashboard",
    page_icon="🌾",
    layout="wide"
)

# Initialize AWS S3 Client
@st.cache_resource
def get_s3_client():
    return boto3.client('s3')

# Cached download for the Silver table to speed up interactions
@st.cache_data(ttl=3600)
def load_historical_data():
    s3_client = get_s3_client()
    local_path = "/tmp/dashboard_silver_data.parquet"
    s3_client.download_file(BUCKET_NAME, "trusted/agro_master_table.parquet", local_path)
    df = pd.read_parquet(local_path)
    
    # Ensure index or Date column is properly cast to datetime
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
        df = df.reset_index().rename(columns={'index': 'Date'})
    return df

# Cached download for predictions JSON array
@st.cache_data(ttl=600)
def load_prediction_data():
    s3_client = get_s3_client()
    local_path = "/tmp/dashboard_predictions.json"
    s3_client.download_file(BUCKET_NAME, "forecasts/latest_commodity_predictions.json", local_path)
    with open(local_path, 'r') as f:
        return json.load(f)

# ==========================================
# 📊 DATA LOADING & APPLICATION SIDEBAR
# ==========================================
st.title("🌾 Commodity Price Forecasting Center")
st.markdown("Automated end-to-end ML inference execution and recursive analytics pipeline.")

if not BUCKET_NAME:
    st.error("❌ Environment variable 'AGRO_BUCKET_NAME' not detected. Please verify your local configuration.")
    st.stop()

try:
    with st.spinner("🔄 Fetching datasets live from AWS S3..."):
        df_historical = load_historical_data()
        predictions_json = load_prediction_data()
except Exception as e:
    st.error(f"❌ Failed connecting to AWS S3: {e}")
    st.stop()

# Sidebar Setup
st.sidebar.header("Control Interface")
selected_commodity = st.sidebar.selectbox("Select Target Commodity:", ["Corn", "Wheat", "Soy"])

# Filter JSON records for selected commodity
commodity_preds = [p for p in predictions_json if p['commodity'].lower() == selected_commodity.lower()]

if not commodity_preds:
    st.sidebar.warning(f"No prediction metadata found for {selected_commodity}.")
    st.stop()

# ==========================================
# 📈 KPI METRIC CARDS GENERATION
# ==========================================
# Extract last known actual price
col_name = f"{selected_commodity.lower()}_Close"
last_actual_row = df_historical.dropna(subset=[col_name]).iloc[-1]
last_actual_date = last_actual_row['Date']
last_actual_price = float(last_actual_row[col_name])

# Isolate models
pred_m7 = next((p for p in commodity_preds if p['lookback_days'] == 7), None)
pred_m30 = next((p for p in commodity_preds if p['lookback_days'] == 30), None)

st.subheader(f"📊 {selected_commodity} Execution Summary")
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

with kpi1:
    st.metric(
        label=f"Last Close ({last_actual_date.strftime('%Y-%m-%d')})",
        value=f"${last_actual_price:.2f}"
    )

with kpi2:
    if pred_m30:
        final_p30 = pred_m30['forecast_values'][-1]
        delta_p30 = final_p30 - last_actual_price
        st.metric(
            label="30-Day Outlook (M30 Model)",
            value=f"${final_p30:.2f}",
            delta=f"{delta_p30:.2f} ({ (delta_p30/last_actual_price)*100 :.1f}%)"
        )

with kpi3:
    if pred_m7:
        final_p7 = pred_m7['forecast_values'][-1]
        delta_p7 = final_p7 - last_actual_price
        st.metric(
            label="30-Day Outlook (M7 Model)",
            value=f"${final_p7:.2f}",
            delta=f"{delta_p7:.2f} ({(delta_p7/last_actual_price)*100:.1f}%)"
        )

with kpi4:
    generated_time = datetime.datetime.fromisoformat(commodity_preds[0]['generated_at'].replace('Z', '+00:00'))
    st.metric(
        label="Pipeline Sync Time",
        value=generated_time.strftime("%H:%M UTC"),
        delta=generated_time.strftime("%b %d, %Y"),
        delta_color="off"
    )

st.markdown("---")

# ==========================================
# 📈 PLOTLY RECURSIVE FORECAST VISUALIZATION
# ==========================================
st.subheader("Hybrid Timeline & Multi-Model Horizon Projections")

# Generate future date axis
future_dates = [last_actual_date + datetime.timedelta(days=i) for i in range(1, 31)]

# Establish overlapping visual anchors so traces branch cleanly from historical data
plot_historical_dates = list(df_historical['Date'])
plot_historical_prices = list(df_historical[col_name])

fig = go.Figure()

# 1. Plot Historical Actual Data
fig.add_trace(go.Scatter(
    x=plot_historical_dates,
    y=plot_historical_prices,
    mode='lines',
    name='Historical Actual Price',
    line=dict(color='#2c3e50', width=2.5)
))

# 2. Plot 7-Day Lookback Recursive Forecast Trace
if pred_m7:
    m7_dates = [last_actual_date] + future_dates
    m7_values = [last_actual_price] + pred_m7['forecast_values']
    fig.add_trace(go.Scatter(
        x=m7_dates,
        y=m7_values,
        mode='lines',
        name='7-Day Lookback Model (Recursive)',
        line=dict(color='#e74c3c', width=2.5, dash='dash')
    ))

# 3. Plot 30-Day Lookback Recursive Forecast Trace
if pred_m30:
    m30_dates = [last_actual_date] + future_dates
    m30_values = [last_actual_price] + pred_m30['forecast_values']
    fig.add_trace(go.Scatter(
        x=m30_dates,
        y=m30_values,
        mode='lines',
        name='30-Day Lookback Model (Recursive)',
        line=dict(color='#2980b9', width=2.5, dash='dot')
    ))

# Vertical operational divider
fig.add_vline(x=last_actual_date, line_width=1.5, line_dash="solid", line_color="#7f8c8d")

# Configure timeline constraints and date window selector toggles
two_months_ago = last_actual_date - datetime.timedelta(days=60)
three_months_ago = last_actual_date - datetime.timedelta(90)
six_months_ago = last_actual_date - datetime.timedelta(days=180)
end_axis_view = future_dates[-1] + datetime.timedelta(days=2)

fig.update_layout(
    template="plotly_white",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=40, r=40, t=40, b=40),
    xaxis=dict(
        type="date",
        # Default starting view bound to exactly 6 months of historical data
        range=[six_months_ago.strftime("%Y-%m-%d"), end_axis_view.strftime("%Y-%m-%d")],
        rangeselector=dict(
            buttons=list([
                dict(count=2, label="2 Months", step="month", stepmode="backward"),
                dict(count=3, label="3 Months", step="month", stepmode="backward"),
                dict(count=6, label="6 Months", step="month", stepmode="backward"),
                dict(count=1, label="1 Year", step="year", stepmode="backward"),
                dict(count=5, label="5 Years", step="year", stepmode="backward"),
                dict(step="all", label="Entire Graph")
            ]),
            font=dict(size=13),
            y=0.9
        )
    ),
    yaxis=dict(title="Market Asset Valuation (USD)")
)

st.plotly_chart(fig, width="stretch")

# ==========================================
# 📋 MATRIX BREAKDOWN DATA TABLE
# ==========================================
st.subheader("📋 Next-Horizon Value Distribution Matrix")

# Build data summary frame
forecast_matrix = {
    "Execution Date / Horizon": [d.strftime("%Y-%m-%d") for d in future_dates]
}
if pred_m7:
    forecast_matrix["M7 Forecast Price"] = [f"${v:.2f}" for v in pred_m7['forecast_values']]
if pred_m30:
    forecast_matrix["M30 Forecast Price"] = [f"${v:.2f}" for v in pred_m30['forecast_values']]

df_matrix = pd.DataFrame(forecast_matrix).set_index("Execution Date / Horizon")

# Divide interface into presentation blocks
t_col1, t_col2 = st.columns([2, 1])
with t_col1:
    st.dataframe(df_matrix, width="stretch")

with t_col2:
    st.info(
        "💡 **Dashboard Architecture Context**\n\n"
        "This analytics view provides a direct evaluation layout. "
        "The **7-Day Model** reacts quickly to immediate short-term volatility, "
        "while the **30-Day Model** looks at a broader context window to filter out "
        "market noise and isolate underlying structural commodity trends."
    )