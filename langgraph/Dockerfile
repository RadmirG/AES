FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY aes_agent /app/aes_agent

EXPOSE 8001

CMD ["uvicorn", "aes_agent.main:app", "--host", "0.0.0.0", "--port", "8001"]