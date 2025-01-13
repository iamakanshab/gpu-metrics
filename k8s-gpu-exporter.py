#!/usr/bin/env python3
import subprocess
import json
import logging
from prometheus_client import start_http_server, Gauge, Counter
import time
import os

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
        
    def _run_kubectl(self, command):
        """Execute kubectl command and return output."""
        try:
            result = subprocess.run(
                f"kubectl {command}",
                shell=True,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise subprocess.SubprocessError(f"Command failed: {result.stderr}")
            return result.stdout
        except Exception as e:
            logger.error(f"Error executing kubectl command: {e}")
            self.metrics.collection_errors.labels(type='kubectl').inc()
            return ""

    def _get_gpu_pods(self):
        """Get all pods using GPUs across watched namespaces."""
        gpu_pods = []
        for namespace in self.watched_namespaces:
            # Get pods in JSON format with node information
            pods_json = self._run_kubectl(
                f"get pods -n {namespace} -o json"
            )
            if not pods_json:
                continue
                
            try:
                pods = json.loads(pods_json)
                for pod in pods.get('items', []):
                    # Check if pod has GPU resources
                    containers = pod.get('spec', {}).get('containers', [])
                    for container in containers:
                        resources = container.get('resources', {})
                        limits = resources.get('limits', {})
                        if 'amd.com/gpu' in limits:
                            gpu_pods.append({
                                'name': pod['metadata']['name'],
                                'namespace': pod['metadata']['namespace'],
                                'node': pod.get('spec', {}).get('nodeName', 'unknown'),
                                'gpu_count': int(limits['amd.com/gpu'])
                            })
            except Exception as e:
                logger.error(f"Error parsing pod data: {e}")
                self.metrics.collection_errors.labels(type='parse').inc()
                
        return gpu_pods

    def _get_gpu_metrics_for_node(self, node):
        """Get GPU metrics for a specific node using rocm-smi."""
        try:
            # Execute rocm-smi on the node
            cmd = f"kubectl debug node/{node} -it --image=rocm/rocm-terminal -- rocm-smi --json"
            metrics_json = self._run_kubectl(cmd)
            if not metrics_json:
                return {}
                
            return json.loads(metrics_json)
        except Exception as e:
            logger.error(f"Error getting GPU metrics for node {node}: {e}")
            self.metrics.collection_errors.labels(type='metrics').inc()
            return {}

    def collect_metrics(self):
        """Collect GPU metrics for all GPU-using pods."""
        # Get all pods using GPUs
        gpu_pods = self._get_gpu_pods()
        
        # Track processed nodes to avoid duplicate metric collection
        processed_nodes = set()
        
        for pod in gpu_pods:
            node = pod['node']
            
            # Only collect node metrics once
            if node not in processed_nodes:
                gpu_metrics = self._get_gpu_metrics_for_node(node)
                processed_nodes.add(node)
                
                if not gpu_metrics:
                    continue
                
                # Update metrics for each GPU
                for gpu_id, gpu_data in gpu_metrics.items():
                    try:
                        self.metrics.gpu_utilization.labels(
                            node=node,
                            namespace=pod['namespace'],
                            pod=pod['name'],
                            gpu_id=gpu_id
                        ).set(gpu_data.get('GPU use (%)', 0))
                        
                        self.metrics.gpu_memory_used.labels(
                            node=node,
                            namespace=pod['namespace'],
                            pod=pod['name'],
                            gpu_id=gpu_id
                        ).set(gpu_data.get('Memory use (bytes)', 0))
                        
                        self.metrics.gpu_memory_total.labels(
                            node=node,
                            namespace=pod['namespace'],
                            pod=pod['name'],
                            gpu_id=gpu_id
                        ).set(gpu_data.get('Memory total (bytes)', 0))
                        
                        self.metrics.gpu_power_usage.labels(
                            node=node,
                            namespace=pod['namespace'],
                            pod=pod['name'],
                            gpu_id=gpu_id
                        ).set(gpu_data.get('Power use (watts)', 0))
                    except Exception as e:
                        logger.error(f"Error setting metrics for GPU {gpu_id} on {node}: {e}")
                        self.metrics.collection_errors.labels(type='set_metrics').inc()

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
