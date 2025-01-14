#!/usr/bin/env python3
import logging
from prometheus_client import start_http_server, Gauge, Counter
import time
import os
from kubernetes import client, config
import subprocess
import sys
import traceback
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('k8s-gpu-exporter')

def parse_gpu_metrics(output):
    """Parse rocm-smi output into structured data."""
    metrics = {}
    current_gpu = None
    
    for line in output.split('\n'):
        line = line.strip()
        
        # Match GPU index
        gpu_match = re.match(r'GPU\[(\d+)\]', line)
        if gpu_match:
            current_gpu = gpu_match.group(1)
            if current_gpu not in metrics:
                metrics[current_gpu] = {}
            
        # Parse different metrics
        if current_gpu is not None:
            if 'Current Socket Graphics Package Power (W):' in line:
                power = float(line.split(':')[1].strip())
                metrics[current_gpu]['power'] = power
                
            elif 'GPU use (%):' in line:
                utilization = float(line.split(':')[1].strip())
                metrics[current_gpu]['utilization'] = utilization
                
            elif 'GPU Memory Allocated (VRAM%):' in line:
                memory = float(line.split(':')[1].strip())
                metrics[current_gpu]['memory'] = memory
                
    return metrics

def get_gpu_metrics():
    """Get GPU metrics using rocm-smi with detailed logging."""
    logger.info("Attempting to collect GPU metrics...")
    try:
        # Get GPU metrics
        result = subprocess.run(['rocm-smi', '--showuse', '--showmemuse', '--showpower'],
                              capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"rocm-smi error: {result.stderr}")
            return None
            
        logger.info(f"GPU metrics collected successfully")
        return parse_gpu_metrics(result.stdout)

    except Exception as e:
        logger.error(f"Error collecting GPU metrics: {str(e)}")
        return None

class K8sGPUMetrics:
    def __init__(self):
        logger.info("Initializing metrics...")
        self.gpu_utilization = Gauge(
            'k8s_gpu_utilization', 
            'GPU utilization percentage',
            ['node', 'gpu_id']
        )
        self.gpu_memory = Gauge(
            'k8s_gpu_memory',
            'GPU memory usage percentage',
            ['node', 'gpu_id']
        )
        self.gpu_power = Gauge(
            'k8s_gpu_power',
            'GPU power usage in watts',
            ['node', 'gpu_id']
        )
        self.collection_errors = Counter(
            'k8s_gpu_collector_errors_total',
            'Total number of collection errors',
            ['type']
        )
        logger.info("Metrics initialized successfully")

class K8sGPUExporter:
    def __init__(self):
        logger.info("Initializing exporter...")
        self.metrics = K8sGPUMetrics()
        self.current_node = os.uname().nodename
        logger.info(f"Running on node: {self.current_node}")

        # Load kubernetes configuration
        logger.info("Loading Kubernetes configuration...")
        config.load_kube_config()
        self.k8s_client = client.CoreV1Api()
        
        # Test kubernetes connection
        namespaces = self.k8s_client.list_namespace()
        logger.info(f"Connected to Kubernetes. Found {len(namespaces.items)} namespaces")

    def update_metrics(self, gpu_metrics):
        """Update Prometheus metrics with GPU data."""
        try:
            for gpu_id, metrics in gpu_metrics.items():
                # Update utilization
                if 'utilization' in metrics:
                    self.metrics.gpu_utilization.labels(
                        node=self.current_node,
                        gpu_id=gpu_id
                    ).set(metrics['utilization'])
                
                # Update memory
                if 'memory' in metrics:
                    self.metrics.gpu_memory.labels(
                        node=self.current_node,
                        gpu_id=gpu_id
                    ).set(metrics['memory'])
                
                # Update power
                if 'power' in metrics:
                    self.metrics.gpu_power.labels(
                        node=self.current_node,
                        gpu_id=gpu_id
                    ).set(metrics['power'])
                    
                logger.info(f"Updated metrics for GPU {gpu_id}: {metrics}")
                
        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
            self.metrics.collection_errors.labels(type='update_metrics').inc()

    def collect_metrics(self):
        """Collect and update GPU metrics."""
        try:
            logger.info("Starting metrics collection...")
            
            # Get GPU metrics
            gpu_metrics = get_gpu_metrics()
            if not gpu_metrics:
                logger.error("Failed to collect GPU metrics")
                return

            # Update Prometheus metrics
            self.update_metrics(gpu_metrics)
            logger.info("Metrics collection completed successfully")

        except Exception as e:
            logger.error(f"Error in collect_metrics: {e}")
            logger.error(traceback.format_exc())

def main():
    try:
        port = int(os.environ.get('EXPORTER_PORT', 9400))
        collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 300))

        logger.info(f"Starting Kubernetes GPU exporter on port {port}")
        logger.info(f"Collection interval: {collection_interval} seconds")
        start_http_server(port)
        
        exporter = K8sGPUExporter()
        
        while True:
            try:
                exporter.collect_metrics()
                time.sleep(collection_interval)
            except Exception as e:
                logger.error(f"Error in collection loop: {e}")
                time.sleep(collection_interval)
                
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
