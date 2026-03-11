FROM ubuntu:22.04

WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y python3.10 python3-pip && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8003

CMD ["python3", "-m", "uvicorn", "fabric_gateway:app", "--host", "0.0.0.0", "--port", "8003"]
