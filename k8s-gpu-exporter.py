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
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('k8s-gpu-exporter')

class K8sGPUMetrics:
    def __init__(self):
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

class K8sGPUExporter:
    def __init__(self):
        logger.debug("Initializing exporter...")
        self.metrics = K8sGPUMetrics()
        self.watched_namespaces = [
            'arc-iree-gpu',
            'buildkite',
            'tuning'
        ]

        # Load kubernetes configuration
        kubeconfig_path = os.environ.get('KUBECONFIG', '/etc/kubernetes/kubeconfig')
        logger.debug(f"Using kubeconfig path: {kubeconfig_path}")
        
        if not os.path.exists(kubeconfig_path):
            raise Exception(f"Kubeconfig not found at {kubeconfig_path}")
            
        try:
            config.load_kube_config(config_file=kubeconfig_path)
            logger.info("Successfully loaded kubeconfig")
        except Exception as e:
            logger.error(f"Error loading kubeconfig: {e}")
            raise

        self.k8s_client = client.CoreV1Api()
        
        # Test kubernetes connection
        try:
            namespaces = self.k8s_client.list_namespace()
            logger.info(f"Successfully connected to Kubernetes. Found {len(namespaces.items)} namespaces")
        except Exception as e:
            logger.error(f"Failed to connect to Kubernetes: {e}")
            raise

    def _get_gpu_metrics_from_rocm(self):
        try:
            logger.debug("Checking rocm-smi...")
            rocm_smi_path = subprocess.check_output(['which', 'rocm-smi']).decode().strip()
            logger.info(f"Found rocm-smi at: {rocm_smi_path}")
            
            result = subprocess.run(
                [rocm_smi_path, '--showuse', '--showmemuse', '--showpower'],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"rocm-smi error: {result.stderr}")
                return None
            
            logger.debug(f"rocm-smi output: {result.stdout[:200]}...")
            return result.stdout
            
        except subprocess.CalledProcessError:
            logger.error("rocm-smi not found in PATH")
            return None
        except Exception as e:
            logger.error(f"Error executing rocm-smi: {e}")
            logger.error(traceback.format_exc())
            self.metrics.collection_errors.labels(type='rocm_smi').inc()
            return None

    def _get_gpu_pods(self):
        gpu_pods = []
        for namespace in self.watched_namespaces:
            try:
                logger.debug(f"Fetching pods from namespace: {namespace}")
                pods = self.k8s_client.list_namespaced_pod(namespace)
                for pod in pods.items:
                    for container in pod.spec.containers:
                        if (container.resources and 
                            container.resources.limits and 
                            'amd.com/gpu' in container.resources.limits):
                            gpu_pods.append({
                                'name': pod.metadata.name,
                                'namespace': pod.metadata.namespace,
                                'node': pod.spec.node_name if pod.spec.node_name else 'unknown',
                                'gpu_count': int(container.resources.limits['amd.com/gpu'])
                            })
                            logger.info(f"Found GPU pod: {pod.metadata.name} in {namespace}")
                
            except Exception as e:
                logger.error(f"Error getting pods from namespace {namespace}: {e}")
                self.metrics.collection_errors.labels(type='k8s_api').inc()
                
        logger.info(f"Total GPU pods found: {len(gpu_pods)}")
        return gpu_pods

    def collect_metrics(self):
        logger.debug("Starting metrics collection...")
        
        # Get GPU metrics
        gpu_metrics = self._get_gpu_metrics_from_rocm()
        if gpu_metrics:
            logger.info("Successfully collected GPU metrics")
        else:
            logger.error("Failed to collect GPU metrics")
            return

        # Get pods using GPUs
        gpu_pods = self._get_gpu_pods()
        
        # Update metrics for each pod
        for pod in gpu_pods:
            try:
                # Example metric update - adjust based on your rocm-smi output format
                self.metrics.gpu_utilization.labels(
                    node=pod['node'],
                    namespace=pod['namespace'],
                    pod=pod['name'],
                    gpu_id='0'
                ).set(0)  # Replace with actual value from gpu_metrics
                
            except Exception as e:
                logger.error(f"Error updating metrics for pod {pod['name']}: {e}")
                self.metrics.collection_errors.labels(type='update_metrics').inc()

def main():
    try:
        port = int(os.environ.get('EXPORTER_PORT', 9400))
        collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 15))

        logger.info(f"Starting Kubernetes GPU exporter on port {port}")
        start_http_server(port)
        
        exporter = K8sGPUExporter()
        
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
