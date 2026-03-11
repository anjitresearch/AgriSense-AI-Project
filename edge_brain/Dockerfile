FROM ubuntu:22.04

WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y python3.10 python3-pip libgl1-mesa-glx libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001
EXPOSE 8002

CMD ["python3", "-m", "uvicorn", "edge_brain_api:app", "--host", "0.0.0.0", "--port", "8001"]
