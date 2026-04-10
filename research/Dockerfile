FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy the single requirements file
COPY requirements.txt .

# Install all requirements
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the research project code
COPY . .

# Default command (will be overridden by docker-compose for Jupyter)
CMD ["python", "scripts/tune_architectures.py"]