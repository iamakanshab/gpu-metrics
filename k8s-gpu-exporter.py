#!/usr/bin/env python3
import logging
from prometheus_client import start_http_server, Gauge, Counter
import time
import os
from kubernetes import client, config
import subprocess
import sys
import traceback

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more verbose output
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('k8s-gpu-exporter')

class K8sGPUMetrics:
    def __init__(self):
        try:
            logger.debug("Initializing metrics...")
            self.gpu_utilization = Gauge(
                'k8s_gpu_utilization', 
                'GPU utilization percentage',
                ['node', 'namespace', 'pod', 'gpu_id']
            )
            self.gpu_memory_used = Gauge(
                'k8s_gpu_memory_used',
                'GPU memory used in bytes',
                ['node', 'namespace', 'pod', 'gpu_id']
            )
            self.gpu_memory_total = Gauge(
                'k8s_gpu_memory_total',
                'Total GPU memory in bytes',
                ['node', 'namespace', 'pod', 'gpu_id']
            )
            self.gpu_power_usage = Gauge(
                'k8s_gpu_power_usage',
                'GPU power usage in watts',
                ['node', 'namespace', 'pod', 'gpu_id']
            )
            self.collection_errors = Counter(
                'k8s_gpu_collector_errors_total',
                'Total number of collection errors',
                ['type']
            )
            logger.debug("Metrics initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing metrics: {e}")
            logger.error(traceback.format_exc())
            raise

class K8sGPUExporter:
    def __init__(self):
        try:
            logger.debug("Initializing exporter...")
            self.metrics = K8sGPUMetrics()
            self.watched_namespaces = [
                'arc-iree-gpu',
                'buildkite',
                'tuning'
            ]
            
            # Check if kubeconfig exists
            kubeconfig = os.environ.get('KUBECONFIG')
            logger.debug(f"Using KUBECONFIG: {kubeconfig}")
            if kubeconfig and os.path.exists(kubeconfig):
                logger.debug("Loading kubeconfig...")
                config.load_kube_config()
            else:
                logger.debug("Trying in-cluster config...")
                config.load_incluster_config()
                
            self.k8s_client = client.CoreV1Api()
            logger.debug("Kubernetes client initialized")
            
            # Test kubernetes connection
            try:
                self.k8s_client.list_namespace()
                logger.debug("Successfully connected to Kubernetes")
            except Exception as e:
                logger.error(f"Failed to connect to Kubernetes: {e}")
                raise
                
        except Exception as e:
            logger.error(f"Error in initialization: {e}")
            logger.error(traceback.format_exc())
            raise
            
    def _get_gpu_metrics_from_rocm(self):
        try:
            logger.debug("Executing rocm-smi...")
            
            # First check if rocm-smi exists
            try:
                subprocess.run(['which', 'rocm-smi'], check=True, capture_output=True)
                logger.debug("rocm-smi found in PATH")
            except subprocess.CalledProcessError:
                logger.error("rocm-smi not found in PATH")
                return None
                
            result = subprocess.run(
                ['rocm-smi', '--showuse', '--showmemuse', '--showpower'],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"rocm-smi error: {result.stderr}")
                return None
                
            logger.debug(f"rocm-smi output: {result.stdout[:200]}...")
            return result.stdout
            
        except Exception as e:
            logger.error(f"Error executing rocm-smi: {e}")
            logger.error(traceback.format_exc())
            self.metrics.collection_errors.labels(type='rocm_smi').inc()
            return None

    def collect_metrics(self):
        try:
            logger.debug("Starting metrics collection...")
            metrics = self._get_gpu_metrics_from_rocm()
            if not metrics:
                logger.error("Failed to collect GPU metrics")
                return
                
            logger.debug("Successfully collected GPU metrics")
            # Process metrics here...
            
        except Exception as e:
            logger.error(f"Error in collect_metrics: {e}")
            logger.error(traceback.format_exc())
            time.sleep(5)  # Add delay before retry

def main():
    try:
        port = int(os.environ.get('EXPORTER_PORT', 9400))
        collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 15))

        logger.info(f"Starting Kubernetes GPU exporter on port {port}")
        logger.debug(f"Environment variables: KUBECONFIG={os.environ.get('KUBECONFIG')}")
        
        start_http_server(port)
        logger.debug("HTTP server started")
        
        exporter = K8sGPUExporter()
        logger.debug("Exporter initialized")
        
        while True:
            try:
                exporter.collect_metrics()
                time.sleep(collection_interval)
            except Exception as e:
                logger.error(f"Error in collection loop: {e}")
                logger.error(traceback.format_exc())
                time.sleep(collection_interval)
                
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
