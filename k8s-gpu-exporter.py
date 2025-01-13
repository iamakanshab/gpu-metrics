#!/usr/bin/env python3
import logging
from prometheus_client import start_http_server, Gauge, Counter
import time
import os
from kubernetes import client, config
import subprocess
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('k8s-gpu-exporter')

class K8sGPUMetrics:
    def __init__(self):
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

class K8sGPUExporter:
    def __init__(self):
        self.metrics = K8sGPUMetrics()
        self.watched_namespaces = [
            'arc-iree-gpu',
            'buildkite',
            'tuning'
        ]
        
        logger.info("Initializing Kubernetes client...")
        try:
            config.load_kube_config()
            logger.info("Successfully loaded kubeconfig")
        except:
            try:
                config.load_incluster_config()
                logger.info("Successfully loaded in-cluster config")
            except Exception as e:
                logger.error(f"Failed to load kubernetes config: {e}")
                raise
                
        self.k8s_client = client.CoreV1Api()
        
    def _get_gpu_metrics_from_rocm(self):
        try:
            logger.info("Executing rocm-smi...")
            result = subprocess.run(
                ['rocm-smi', '--showuse', '--showmemuse', '--showpower', '--json'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.error(f"rocm-smi error: {result.stderr}")
                return None
                
            # Print raw output for debugging
            logger.info(f"rocm-smi output: {result.stdout[:200]}...")  # First 200 chars
            
            return json.loads(result.stdout)
        except FileNotFoundError:
            logger.error("rocm-smi command not found. Is ROCm installed?")
            self.metrics.collection_errors.labels(type='rocm_smi_not_found').inc()
            return None
        except Exception as e:
            logger.error(f"Error executing rocm-smi: {e}")
            self.metrics.collection_errors.labels(type='rocm_smi').inc()
            return None

    def _get_gpu_pods(self):
        gpu_pods = []
        for namespace in self.watched_namespaces:
            try:
                logger.info(f"Fetching pods from namespace: {namespace}")
                pods = self.k8s_client.list_namespaced_pod(namespace)
                for pod in pods.items:
                    for container in pod.spec.containers:
                        if (container.resources and 
                            container.resources.limits and 
                            'amd.com/gpu' in container.resources.limits):
                            gpu_limit = container.resources.limits['amd.com/gpu']
                            gpu_pods.append({
                                'name': pod.metadata.name,
                                'namespace': pod.metadata.namespace,
                                'node': pod.spec.node_name if pod.spec.node_name else 'unknown',
                                'gpu_count': int(gpu_limit)
                            })
                            logger.info(f"Found GPU pod: {pod.metadata.name} in {namespace}")
                            
            except Exception as e:
                logger.error(f"Error getting pods from namespace {namespace}: {e}")
                self.metrics.collection_errors.labels(type='k8s_api').inc()
        
        logger.info(f"Total GPU pods found: {len(gpu_pods)}")
        return gpu_pods

    def collect_metrics(self):
        logger.info("Starting metrics collection...")
        
        # Get GPU metrics from rocm-smi
        gpu_metrics = self._get_gpu_metrics_from_rocm()
        if gpu_metrics:
            logger.info(f"Collected GPU metrics for {len(gpu_metrics)} GPUs")
        
        # Get all pods using GPUs
        gpu_pods = self._get_gpu_pods()
        
        # Update metrics
        for pod in gpu_pods:
            try:
                if gpu_metrics:
                    # Assuming gpu_metrics contains data per GPU
                    for gpu_id, gpu_data in gpu_metrics.items():
                        # Update utilization
                        if 'GPU use (%)' in gpu_data:
                            self.metrics.gpu_utilization.labels(
                                node=pod['node'],
                                namespace=pod['namespace'],
                                pod=pod['name'],
                                gpu_id=gpu_id
                            ).set(gpu_data['GPU use (%)'])
                            
                        # Update memory
                        if 'Memory use (bytes)' in gpu_data:
                            self.metrics.gpu_memory_used.labels(
                                node=pod['node'],
                                namespace=pod['namespace'],
                                pod=pod['name'],
                                gpu_id=gpu_id
                            ).set(gpu_data['Memory use (bytes)'])
                            
                        if 'Memory total (bytes)' in gpu_data:
                            self.metrics.gpu_memory_total.labels(
                                node=pod['node'],
                                namespace=pod['namespace'],
                                pod=pod['name'],
                                gpu_id=gpu_id
                            ).set(gpu_data['Memory total (bytes)'])
                            
                        # Update power
                        if 'Power use (watts)' in gpu_data:
                            self.metrics.gpu_power_usage.labels(
                                node=pod['node'],
                                namespace=pod['namespace'],
                                pod=pod['name'],
                                gpu_id=gpu_id
                            ).set(gpu_data['Power use (watts)'])
                            
                        logger.info(f"Updated metrics for pod {pod['name']} GPU {gpu_id}")
                
            except Exception as e:
                logger.error(f"Error updating metrics for pod {pod['name']}: {e}")
                self.metrics.collection_errors.labels(type='update_metrics').inc()

        logger.info("Metrics collection completed")

def main():
    port = int(os.environ.get('EXPORTER_PORT', 9400))
    collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 15))

    logger.info(f"Starting Kubernetes GPU exporter on port {port}")
    start_http_server(port)
    
    logger.info("Initializing exporter...")
    exporter = K8sGPUExporter()
    
    logger.info(f"Starting main collection loop with {collection_interval}s interval")
    while True:
        try:
            exporter.collect_metrics()
            time.sleep(collection_interval)
        except Exception as e:
            logger.error(f"Error in main collection loop: {e}")
            time.sleep(collection_interval)

if __name__ == "__main__":
    main()
