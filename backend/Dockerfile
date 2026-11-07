FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
# CPU-only PyTorch: the app runs inference on CPU, and the default Linux wheel bundles ~GBs of CUDA libraries
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt
COPY app ./app
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
