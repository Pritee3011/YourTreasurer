FROM python:3.9-slim

WORKDIR /app

# Crucial: Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code (app.py, etc.)
COPY . .

# Set Port for Render
ENV PORT=5000

# Use Gunicorn to run the app
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app"]
