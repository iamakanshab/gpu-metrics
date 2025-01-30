#!/usr/bin/env python3

import logging
import os
import time
import requests
from typing import Dict
from base64 import b64encode
from datetime import datetime

# Reuse your existing GPU metrics collection classes
from k8s_gpu_metrics import K8sGPUMetrics, GPUPodMapper, K8sGPUExporter

class GPUMetricsPusher:
    def __init__(self, pushgateway_url: str, job_name: str, machine_id: str, 
                 username: str = None, password: str = None):
        self.logger = logging.getLogger('gpu-metrics-pusher')
        self.pushgateway_url = pushgateway_url.rstrip('/')
        self.job_name = job_name
        self.machine_id = machine_id
        self.auth_header = self._get_auth_header(username, password)
        
        # Initialize the existing GPU metrics collector
        self.exporter = K8sGPUExporter()
        
    def _get_auth_header(self, username: str, password: str) -> Dict[str, str]:
        if username and password:
            credentials = b64encode(f"{username}:{password}".encode()).decode()
            return {"Authorization": f"Basic {credentials}"}
        return {}
        
    def push_metrics(self):
        try:
            # Collect GPU metrics using existing logic
            gpu_metrics = self.exporter.get_gpu_metrics()
            if not gpu_metrics:
                self.logger.error("Failed to collect GPU metrics")
                return
                
            # Format metrics for Pushgateway
            timestamp = datetime.now().timestamp() * 1000
            
            # Prepare metrics in Prometheus format
            metrics_data = ""
            
            # GPU Utilization
            for gpu_id, metrics in gpu_metrics.items():
                if 'utilization' in metrics:
                    metrics_data += (f'gpu_utilization{{machine="{self.machine_id}",'
                                   f'gpu_id="{gpu_id}"}} {metrics["utilization"]} {timestamp}\n')
                
                if 'memory' in metrics:
                    metrics_data += (f'gpu_memory_usage{{machine="{self.machine_id}",'
                                   f'gpu_id="{gpu_id}"}} {metrics["memory"]} {timestamp}\n')
                    
                if 'power' in metrics:
                    metrics_data += (f'gpu_power_usage{{machine="{self.machine_id}",'
                                   f'gpu_id="{gpu_id}"}} {metrics["power"]} {timestamp}\n')
            
            # Push to Pushgateway
            push_url = f"{self.pushgateway_url}/metrics/job/{self.job_name}/instance/{self.machine_id}"
            
            response = requests.post(
                push_url,
                data=metrics_data,
                headers={
                    "Content-Type": "text/plain",
                    **self.auth_header
                }
            )
            
            if response.status_code == 200:
                self.logger.info("Successfully pushed metrics to Pushgateway")
            else:
                self.logger.error(f"Failed to push metrics. Status: {response.status_code}, "
                                f"Response: {response.text}")
                
        except Exception as e:
            self.logger.error(f"Error pushing metrics: {str(e)}", exc_info=True)

def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
    )
    logger = logging.getLogger('gpu-metrics-pusher')
    
    # Get configuration from environment variables
    pushgateway_url = os.getenv('PUSHGATEWAY_URL')
    if not pushgateway_url:
        logger.error("PUSHGATEWAY_URL environment variable is required")
        return
        
    job_name = os.getenv('JOB_NAME', 'gpu_metrics')
    machine_id = os.getenv('MACHINE_ID', os.uname().nodename)
    collection_interval = int(os.getenv('COLLECTION_INTERVAL', '60'))
    username = os.getenv('PUSHGATEWAY_USERNAME')
    password = os.getenv('PUSHGATEWAY_PASSWORD')
    
    pusher = GPUMetricsPusher(
        pushgateway_url=pushgateway_url,
        job_name=job_name,
        machine_id=machine_id,
        username=username,
        password=password
    )
    
    logger.info(f"Starting GPU metrics pusher for machine: {machine_id}")
    logger.info(f"Pushing to: {pushgateway_url}")
    logger.info(f"Collection interval: {collection_interval} seconds")
    
    while True:
        try:
            pusher.push_metrics()
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}", exc_info=True)
        finally:
            time.sleep(collection_interval)

if __name__ == "__main__":
    main()
