FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
RUN mkdir -p /home/app/.local/share/fastmcp /home/app/.cache && chown -R 65532:65532 /home/app
ENV HOME=/home/app
ENV XDG_DATA_HOME=/home/app/.local/share
ENV XDG_CACHE_HOME=/home/app/.cache
USER 65532:65532
EXPOSE 8765
CMD ["python", "server.py"]
