FROM ubuntu:22.04

WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y python3.10 python3-pip libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY orchestrator.py .

EXPOSE 8000

CMD ["python3", "orchestrator.py"]
