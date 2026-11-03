FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY proofline ./proofline
RUN useradd -m -u 10001 proofline
USER proofline
ENV PROOFLINE_DB=/tmp/proofline.db
ENV PROOFLINE_DEMO=1
CMD ["sh","-c","uvicorn proofline.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
