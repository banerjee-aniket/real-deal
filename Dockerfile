FROM python:3.11-slim
LABEL "language"="python"

WORKDIR /app

# Install system dependencies (if any needed for scikit-learn/numpy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure start script is executable
RUN chmod +x start.sh

EXPOSE 8080

# Use start.sh to run both Bot and Dashboard
CMD ["bash", "start.sh"]
