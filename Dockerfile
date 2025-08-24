FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PORT=8080
EXPOSE 8080
CMD ["uvicorn", "app.main:fastapi_app", "--host", "0.0.0.0", "--port", "8080"]
