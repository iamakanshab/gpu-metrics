#!/usr/bin/env python3
import logging
from prometheus_client import start_http_server, Gauge, Counter, Summary
from kubernetes import client, config
import subprocess
import re
import os
import time
import sys
import traceback
from typing import Dict, List, Optional, Tuple

class K8sGPUMetrics:
    def __init__(self):
        self.logger = logging.getLogger('k8s-gpu-exporter')
        self.logger.info("Initializing metrics with namespace support...")
        
        # Basic GPU metrics with namespace label
        self.gpu_utilization = Gauge(
            'k8s_gpu_utilization', 
            'GPU utilization percentage',
            ['node', 'gpu_id', 'namespace', 'pod']
        )
        self.gpu_memory = Gauge(
            'k8s_gpu_memory',
            'GPU memory usage percentage',
            ['node', 'gpu_id', 'namespace', 'pod']
        )
        self.gpu_power = Gauge(
            'k8s_gpu_power',
            'GPU power usage in watts',
            ['node', 'gpu_id', 'namespace', 'pod']
        )
        
        # Namespace-specific aggregated metrics
        self.namespace_gpu_utilization = Gauge(
            'k8s_namespace_gpu_utilization_total',
            'Total GPU utilization percentage per namespace',
            ['namespace']
        )
        self.namespace_gpu_memory = Gauge(
            'k8s_namespace_gpu_memory_total',
            'Total GPU memory usage percentage per namespace',
            ['namespace']
        )
        self.namespace_gpu_count = Gauge(
            'k8s_namespace_gpu_count',
            'Number of GPUs allocated per namespace',
            ['namespace']
        )
        
        # Error tracking
        self.collection_errors = Counter(
            'k8s_gpu_collector_errors_total',
            'Total number of collection errors',
            ['type']
        )

class GPUPodMapper:
    def __init__(self, k8s_client: client.CoreV1Api):
        self.k8s_client = k8s_client
        self.logger = logging.getLogger('k8s-gpu-exporter')

    def get_pod_gpu_mappings(self) -> Dict[str, Dict[str, str]]:
        """
        Get mappings of GPU devices to pods and namespaces.
        Returns: Dict[gpu_id, Dict[str, str]] mapping GPU IDs to pod and namespace info
        """
        try:
            # Get all pods in all namespaces
            pods = self.k8s_client.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={os.uname().nodename}"
            )
            
            gpu_mappings = {}
            
            for pod in pods.items:
                # Check if pod uses GPUs
                gpu_info = self._get_pod_gpu_info(pod)
                if gpu_info:
                    for gpu_id in gpu_info:
                        gpu_mappings[gpu_id] = {
                            'namespace': pod.metadata.namespace,
                            'pod': pod.metadata.name
                        }
                        self.logger.info(
                            f"Mapped GPU {gpu_id} to pod {pod.metadata.name} "
                            f"in namespace {pod.metadata.namespace}"
                        )
            
            return gpu_mappings

        except Exception as e:
            self.logger.error(f"Error getting pod GPU mappings: {str(e)}", exc_info=True)
            return {}

    def _get_pod_gpu_info(self, pod) -> List[str]:
        """Extract GPU information from pod spec."""
        gpu_ids = []
        
        try:
            # Check container resource limits and env vars for GPU information
            for container in pod.spec.containers:
                # Check resource limits
                if container.resources and container.resources.limits:
                    for resource_name, value in container.resources.limits.items():
                        if 'amd.com/gpu' in resource_name:
                            gpu_ids.extend(self._parse_gpu_ids(container))
                
                # Check environment variables
                if container.env:
                    for env in container.env:
                        if env.name in ['ROCR_VISIBLE_DEVICES', 'GPU_DEVICE_ORDINAL']:
                            if env.value:
                                gpu_ids.extend(env.value.split(','))
        
        except Exception as e:
            self.logger.error(f"Error parsing pod GPU info: {str(e)}")
        
        return list(set(gpu_ids))  # Remove duplicates

    def _parse_gpu_ids(self, container) -> List[str]:
        """Parse GPU IDs from container spec."""
        gpu_ids = []
        
        # Check annotations and env vars for explicit GPU assignments
        if container.env:
            for env in container.env:
                if env.name in ['ROCR_VISIBLE_DEVICES', 'GPU_DEVICE_ORDINAL']:
                    if env.value:
                        gpu_ids.extend(env.value.split(','))
        
        return gpu_ids

class K8sGPUExporter:
    def __init__(self):
        self.logger = logging.getLogger('k8s-gpu-exporter')
        self.logger.info("Initializing namespace-aware exporter...")
        
        self.metrics = K8sGPUMetrics()
        self.current_node = os.uname().nodename
        
        # Initialize Kubernetes client
        config.load_incluster_config()
        self.k8s_client = client.CoreV1Api()
        self.gpu_mapper = GPUPodMapper(self.k8s_client)
        
        self.logger.info(f"Exporter initialized on node: {self.current_node}")

    def _get_namespace_metrics(self, gpu_metrics: Dict[str, Dict[str, float]], 
                             gpu_mappings: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, float]]:
        """Aggregate metrics per namespace."""
        namespace_metrics = {}
        
        for gpu_id, metrics in gpu_metrics.items():
            if gpu_id in gpu_mappings:
                namespace = gpu_mappings[gpu_id]['namespace']
                
                if namespace not in namespace_metrics:
                    namespace_metrics[namespace] = {
                        'utilization': 0.0,
                        'memory': 0.0,
                        'gpu_count': 0
                    }
                
                namespace_metrics[namespace]['utilization'] += metrics.get('utilization', 0)
                namespace_metrics[namespace]['memory'] += metrics.get('memory', 0)
                namespace_metrics[namespace]['gpu_count'] += 1
        
        return namespace_metrics

    def update_metrics(self, gpu_metrics: Dict[str, Dict[str, float]]):
        """Update Prometheus metrics with namespace awareness."""
        try:
            # Get GPU to pod/namespace mappings
            gpu_mappings = self.gpu_mapper.get_pod_gpu_mappings()
            
            # Update individual GPU metrics
            for gpu_id, metrics in gpu_metrics.items():
                namespace = 'unmapped'
                pod_name = 'unmapped'
                
                if gpu_id in gpu_mappings:
                    namespace = gpu_mappings[gpu_id]['namespace']
                    pod_name = gpu_mappings[gpu_id]['pod']
                
                if 'utilization' in metrics:
                    self.metrics.gpu_utilization.labels(
                        node=self.current_node,
                        gpu_id=gpu_id,
                        namespace=namespace,
                        pod=pod_name
                    ).set(metrics['utilization'])
                
                if 'memory' in metrics:
                    self.metrics.gpu_memory.labels(
                        node=self.current_node,
                        gpu_id=gpu_id,
                        namespace=namespace,
                        pod=pod_name
                    ).set(metrics['memory'])
                
                if 'power' in metrics:
                    self.metrics.gpu_power.labels(
                        node=self.current_node,
                        gpu_id=gpu_id,
                        namespace=namespace,
                        pod=pod_name
                    ).set(metrics['power'])
            
            # Update namespace-level metrics
            namespace_metrics = self._get_namespace_metrics(gpu_metrics, gpu_mappings)
            for namespace, metrics in namespace_metrics.items():
                self.metrics.namespace_gpu_utilization.labels(
                    namespace=namespace
                ).set(metrics['utilization'])
                
                self.metrics.namespace_gpu_memory.labels(
                    namespace=namespace
                ).set(metrics['memory'])
                
                self.metrics.namespace_gpu_count.labels(
                    namespace=namespace
                ).set(metrics['gpu_count'])
            
            self.logger.info(f"Updated metrics for all GPUs with namespace mapping")
            
        except Exception as e:
            self.logger.error(f"Error updating metrics: {e}")
            self.metrics.collection_errors.labels(type='update_metrics').inc()

    def collect_metrics(self):
        """Collect and update GPU metrics."""
        try:
            self.logger.info("Starting metrics collection...")
            
            # Get GPU metrics
            gpu_metrics = get_gpu_metrics()
            if not gpu_metrics:
                self.logger.error("Failed to collect GPU metrics")
                return

            # Update Prometheus metrics with namespace awareness
            self.update_metrics(gpu_metrics)
            self.logger.info("Metrics collection completed successfully")

        except Exception as e:
            self.logger.error(f"Error in collect_metrics: {e}")
            self.logger.error(traceback.format_exc())

def main():
    try:
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
        )
        logger = logging.getLogger('k8s-gpu-exporter')

        port = int(os.environ.get('EXPORTER_PORT', 9400))
        collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 300))

        logger.info(f"Starting namespace-aware GPU exporter on port {port}")
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
