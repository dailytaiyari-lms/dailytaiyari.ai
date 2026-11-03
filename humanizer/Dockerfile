FROM python:3.12-slim

# CPU wheels by default. For a GPU host, build with the matching CUDA index, e.g.
# --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu126
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url "$TORCH_INDEX" -r requirements.txt
COPY *.py ./

RUN addgroup --system humanizer && adduser --system --group humanizer \
    && mkdir -p /models && chown humanizer:humanizer /models
USER humanizer

EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
