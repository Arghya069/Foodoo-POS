FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py schemas.py receipt_pdf.py whatsapp_send.py sessions.py bootstrap.py ./
RUN python -m compileall -q .
USER app
EXPOSE 8080
CMD ["sh","-c","exec uvicorn app:app --host 0.0.0.0 --port ${PORT} --workers 2"]
