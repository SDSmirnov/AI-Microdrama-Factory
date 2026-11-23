FROM python:3.13-slim

# No Blender in the image: 3D sketches render through pyvista on headless EGL
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 libgomp1 libegl1 libgl1 libxrender1 \
    && rm -rf /var/lib/apt/lists/*
ENV AI_RENDER3D=auto

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5005

# Data lives in /project (mounted per-series at runtime)
WORKDIR /project
ENTRYPOINT ["python", "/app/cli.py"]
