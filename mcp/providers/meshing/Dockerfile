FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglu1-mesa \
        libgomp1 \
        libxcursor1 \
        libxft2 \
        libxinerama1 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN python -c "import gmsh; gmsh.initialize(); print('gmsh', gmsh.__version__); gmsh.finalize()"
COPY server.py /app/server.py

EXPOSE 8000
CMD ["python", "/app/server.py", "--host", "0.0.0.0", "--port", "8000"]
