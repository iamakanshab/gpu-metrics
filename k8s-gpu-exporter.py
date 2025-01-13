#!/usr/bin/env python3
import logging
from prometheus_client import start_http_server, Gauge, Counter
import time
import os
from kubernetes import client, config
import subprocess

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('k8s-gpu-exporter')

class K8sGPUMetrics:
    def __init__(self):
        # GPU metrics with pod and namespace labels
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
        
        # Error metrics
        self.collection_errors = Counter(
            'k8s_gpu_collector_errors_total',
            'Total number of collection errors',
            ['type']
        )

class K8sGPUExporter:
    def __init__(self):
        self.metrics = K8sGPUMetrics()
        self.watched_namespaces = [
            'arc-iree-gpu',
            'buildkite',
            'tuning'
        ]
        
        # Initialize kubernetes client
        try:
            config.load_kube_config()  # try loading from kubeconfig first
        except:
            try:
                config.load_incluster_config()  # try in-cluster config
            except Exception as e:
                logger.error(f"Failed to load kubernetes config: {e}")
                raise
                
        self.k8s_client = client.CoreV1Api()
        
    def _get_gpu_metrics_from_rocm(self):
        """Get GPU metrics directly using rocm-smi."""
        try:
            result = subprocess.run(
                ['rocm-smi', '--showuse', '--showmemuse', '--showpower', '--json'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.error(f"rocm-smi error: {result.stderr}")
                return None
            return result.stdout
        except Exception as e:
            logger.error(f"Error executing rocm-smi: {e}")
            self.metrics.collection_errors.labels(type='rocm_smi').inc()
            return None

    def _get_gpu_pods(self):
        """Get all pods using GPUs across watched namespaces."""
        gpu_pods = []
        for namespace in self.watched_namespaces:
            try:
                pods = self.k8s_client.list_namespaced_pod(namespace)
                for pod in pods.items:
                    # Check if pod has GPU resources
                    for container in pod.spec.containers:
                        if container.resources and container.resources.limits:
                            gpu_limit = container.resources.limits.get('amd.com/gpu')
                            if gpu_limit:
                                gpu_pods.append({
                                    'name': pod.metadata.name,
                                    'namespace': pod.metadata.namespace,
                                    'node': pod.spec.node_name if pod.spec.node_name else 'unknown',
                                    'gpu_count': int(gpu_limit)
                                })
            except Exception as e:
                logger.error(f"Error getting pods from namespace {namespace}: {e}")
                self.metrics.collection_errors.labels(type='k8s_api').inc()
        return gpu_pods

    def collect_metrics(self):
        """Collect GPU metrics."""
        # Get GPU metrics from rocm-smi
        gpu_metrics = self._get_gpu_metrics_from_rocm()
        if not gpu_metrics:
            return

        # Get all pods using GPUs
        gpu_pods = self._get_gpu_pods()
        
        # Update metrics
        for pod in gpu_pods:
            try:
                # Get GPU utilization from rocm-smi output
                # Parse the JSON output and update metrics accordingly
                # This is a simplified version - you'll need to adapt the parsing
                # based on your actual rocm-smi output format
                self.metrics.gpu_utilization.labels(
                    node=pod['node'],
                    namespace=pod['namespace'],
                    pod=pod['name'],
                    gpu_id='0'  # You'll need to get the actual GPU ID
                ).set(0)  # Replace with actual utilization value
                
                # Similar updates for other metrics...
                
            except Exception as e:
                logger.error(f"Error updating metrics for pod {pod['name']}: {e}")
                self.metrics.collection_errors.labels(type='update_metrics').inc()

def main():
    # Load configuration from environment
    port = int(os.environ.get('EXPORTER_PORT', 9400))
    collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 15))

    # Start exporter
    logger.info(f"Starting Kubernetes GPU exporter on port {port}")
    start_http_server(port)
    
    # Initialize exporter
    exporter = K8sGPUExporter()
    
    # Main collection loop
    while True:
        try:
            exporter.collect_metrics()
            time.sleep(collection_interval)
        except Exception as e:
            logger.error(f"Error in main collection loop: {e}")
            time.sleep(collection_interval)

if __name__ == "__main__":
    main()
