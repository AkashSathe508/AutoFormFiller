FROM python:3.11-slim

WORKDIR /app

RUN pip install fastapi uvicorn jinja2 python-multipart

COPY main.py .
COPY templates/ ./templates/

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
