#!/bin/bash

# Install required packages
sudo apt-get update
sudo apt-get install -y python3-pip curl

# Install Python dependencies system-wide
sudo pip3 install docker requests pandas

# Remove any existing metrics exporter container
sudo docker rm -f device-metrics-exporter || true

# Pull the metrics exporter image
sudo docker pull rocm/device-metrics-exporter:v1.0.0

# Start the metrics exporter
sudo docker run -d \
  --device=/dev/dri:/dev/dri \
  --device=/dev/kfd:/dev/kfd \
  -p 5000:5000 \
  --name device-metrics-exporter \
  --restart unless-stopped \
  rocm/device-metrics-exporter:v1.0.0

# Create directory for metrics
sudo mkdir -p /var/log/gpu-metrics
sudo chmod 777 /var/log/gpu-metrics

# Wait for container to be ready
echo "Waiting for metrics exporter to start..."
sleep 10

# Test metrics endpoint
curl -s http://localhost:5000/metrics > /dev/null
if [ $? -eq 0 ]; then
    echo "Metrics exporter is running successfully"
else
    echo "Error: Metrics exporter is not responding"
    sudo docker logs device-metrics-exporter
fi
