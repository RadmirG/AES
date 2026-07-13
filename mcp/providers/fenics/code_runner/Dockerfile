FROM dolfinx-mcp:latest

USER root
WORKDIR /app
COPY server.py /app/server.py

EXPOSE 8000
ENTRYPOINT []
CMD ["python", "/app/server.py", "--host", "0.0.0.0", "--port", "8000"]
