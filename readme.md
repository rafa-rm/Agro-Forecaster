# 🌾 Agro-Forecaster: End-to-End Commodity Price Prediction Pipeline

Agro-Forecaster is a serverless data engineering and machine learning pipeline designed to ingest, process, and forecast agricultural commodity prices (Soybean, Corn, Wheat, Oil, USD/BRL).

It features a Cost-Optimized Architecture that handles 15+ years of historical data and daily incremental updates using the same codebase, leveraging the Manifest Pattern to bypass AWS Lambda payload limits.

## 🏗️ Architecture Overview

The pipeline follows a Bronze (Raw) $\rightarrow$ Silver (Trusted) $\rightarrow$ Gold (Enriched/ML) <b>medallion </b>architecture.

<h3 style="color:#CD7F32">🥉 Ingestion Layer (Bronze)</h3>

**Source:** Yahoo Finance API (yfinance).

**Infrastructure:** AWS Lambda (Containerized Python).

**Optimization**:

**Manifest Pattern:** Instead of passing large JSON payloads (which can hit the 1MB Lambda limit), the Raw Lambda saves a list of generated files to S3 (raw/manifests/) and passes the key to the next step.

**Hive Partitioning**:  Data is stored in S3 using year=YYYY/month=MM/day=DD structure for efficient querying.


<h3 style="color:#C0C0C0">🥈 Processing Layer (Silver) </h3>


**Logic:** Incremental "Upsert" (Update/Insert).

**Workflow:**

<ol>

<li>Reads the Manifest from S3 to identify new files.

<li>Loads the existing Master Table (trusted/agro_master_table.parquet).

<li>Merges new data with history, deduplicating based on the Date index.

<li>String Date Handling: Dates are strictly handled as YYYY-MM-DD strings to ensure compatibility between Pandas (Python) and Athena (SQL/Presto).

</ol>

<h3 style="color:#D4AF37"> 🥇 Enriched Layer (Gold)</h3>

**Logic:** Feature Engineering layer. Calculates technical indicators (RSI, Rolling Means, Volatility) to prepare the dataset for ML models

**Workflow:**

<ol>

<li> Read the master table from trusted folder.

<li> Leverages pandas.pipe() to create a clean, functional method-chaining pipeline.

<li> Calculate the Lags, Rolling features, and RSI

</ol>

## 🔄 CI/CD Pipeline (GitHub Actions)

This project uses a fully automated CI/CD pipeline orchestrated by <b>GitHub Actions</b> to ensure secure and reliable deployments to AWS.

### Key Features:

* **Dynamic Lambda Layer Build:** Python dependencies (Pandas, Numpy) are compiled on-the-fly inside the CI runner.
* **Infrastructure as Code (Terraform):**
    * **Plan:** On every Pull Request, Terraform generates a speculative execution plan to preview changes.
    * **Apply:** On merge to `main`, Terraform applies the state changes to AWS, ensuring the infrastructure is idempotent and reproducible.


## 🧠Engineering Decisions

<h3>🔐 Security First (OIDC)</h3> 

Instead of storing long-lived AWS Access Keys in GitHub Secrets (which is a security risk), I implemented OpenID Connect (OIDC). This allows GitHub Actions to assume a temporary AWS role only for the duration of the deployment, scoped strictly to this repository.

<h3>📉 Cost Optimization (Partition Projection):</h3>

To avoid the cost and latency of AWS Glue Crawlers, I configured Athena Partition Projection. This allows for instant query availability of new data without needing to update the metastore manually.

<h3>📦 Incremental Merging</h3>

Reading the entire historical dataset every day to append five rows is expensive (S3 GET costs) and slow. The Silver layer uses an incremental merge strategy: it downloads the master file only once, appends the daily delta, and overwrites the master, reducing S3 operations by more than 99%.

<h3>⚡ Performance Tuning (vCPU Threshold)</h3> 
The 'Trusted' layer Lambda is configured with 1769 MB of memory. This is the specific threshold where AWS allocates a full vCPU, ensuring that single-threaded Pandas transformations run at maximum efficiency.

## 🚀 How to Run

### 0. Prerequisites

Install Terraform and AWS CLI

### 1. Infrastructure Deployment (Terraform)

Clone the repository and run these commands

```bash
cd infrastructure && terraform init
terraform apply
```

### 2. Configuring the CI/CD Pipeline (Optional)
<ul>
<li> Create the S3 Bucket for tf-state

<li> Run Terraform init locally

<li> Configure Github Secrets
</ul>

### 3. Manual Backfill (Historical Data)
To initiate a full backfill (15+ years of history), invoke the Raw Lambda with the following payload:

```json
{
  "mode": "historical"
}
```


## 🚀 Future Roadmap: Predictive Modeling

The current architecture provides a Data Engineering foundation. The next phase focuses on the **Machine Learning** capabilities, leveraging the "Gold" enriched data for time-series forecasting.

* **Deep Learning Integration:** Implement an **LSTM (Long Short-Term Memory)** neural network to forecast commodity prices (Soybean, Corn, etc.) based on historical volatility and trends.
* **MLOps Pipeline:** Integrate tools like **MLflow** to track model experiments, hyperparameters, and model registry versioning.
* **Dashboarding:** Expose the forecasted values via an API (API Gateway + Lambda) to a simple Streamlit dashboard.

## 💰 Cost Efficiency
This architecture is designed to be **Serverless** and **Free Tier eligible**:
* **Compute:** AWS Lambda operates on a "pay-per-use" model. Since the pipeline runs once daily, the monthly execution time is well within the AWS Free Tier (400,000 GB-seconds).
* **Storage:** S3 Standard storage costs are negligible for the current data volume (< $0.05/month).
* **Querying:** Athena Partition Projection eliminates the need for expensive Glue Crawlers, reducing the metadata management cost to near zero.

### ⚠️ One-Time Backfill Cost
The initial pipeline execution (Backfill Mode) processes ~15 years of daily OHLC data for multiple commodities. While the **steady-state** cost is near-zero, the **historical mode** generates approximately ~25,000 S3 `PUT` requests and consumes ~5 minutes of Lambda execution time. This remains well below $1.00 USD but is noted for transparency.