FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY letting_copilot/ ./letting_copilot/
COPY data/ ./data/
COPY ui/ ./ui/
COPY main.py .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GOOGLE_GENAI_USE_VERTEXAI=false \
    PORT=8080 \
    ENVIRONMENT=dev

EXPOSE 8080

CMD ["python", "main.py"]
