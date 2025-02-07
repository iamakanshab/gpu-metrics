#!/usr/bin/env python3
import requests
import json
from datetime import datetime
import time
import os

def collect_metrics():
    output_dir = os.path.expanduser("~/gpu_metrics")
    os.makedirs(output_dir, exist_ok=True)
    
    while True:
        try:
            response = requests.get("http://localhost:5000/metrics")
            if response.status_code == 200:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{output_dir}/metrics_{timestamp}.txt"
                with open(filename, 'w') as f:
                    f.write(response.text)
            time.sleep(60)  # Collect every minute
        except Exception as e:
            print(f"Error collecting metrics: {e}")
            time.sleep(5)

if __name__ == "__main__":
    collect_metrics()
