FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create data directory
RUN mkdir -p data public/images

# Copy logo if exists
RUN ls public/images/ 2>/dev/null || true

EXPOSE 8080

CMD ["python", "app.py"]
