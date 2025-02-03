#!/usr/bin/env python3

import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass
from typing import Dict, List, Optional

from kubernetes import client, config
from prometheus_client import start_http_server, Gauge, Counter

@dataclass
class GPUMetric:
    """Data class to hold GPU metrics"""
    utilization: float = 0.0
    memory: float = 0.0
    power: float = 0.0

@dataclass
class NamespaceMetric:
    """Data class to hold namespace-level metrics"""
    utilization: float = 0.0
    memory: float = 0.0
    gpu_count: int = 0

class PrometheusMetrics:
    """Class to manage Prometheus metrics"""
    def __init__(self):
        # GPU-level metrics
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
        
        # Namespace-level metrics
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

class KubernetesClient:
    """Class to handle Kubernetes client initialization and operations"""
    def __init__(self):
        self.logger = logging.getLogger('k8s-gpu-exporter')
        self.client = self._initialize_client()
        
    def _initialize_client(self) -> client.CoreV1Api:
        """Initialize Kubernetes client with fallback options"""
        try:
            config.load_incluster_config()
            self.logger.info("Loaded in-cluster configuration")
        except config.ConfigException:
            try:
                config.load_kube_config()
                self.logger.info("Loaded kubeconfig configuration")
            except Exception as e:
                self.logger.warning(f"Failed to load kubeconfig: {e}")
                self._configure_explicit_client()
                
        return client.CoreV1Api()
    
    def _configure_explicit_client(self):
        """Configure client explicitly using environment variables"""
        k8s_host = os.getenv('KUBERNETES_HOST', 'https://kubernetes.default.svc')
        k8s_token = self._get_kubernetes_token()
        
        configuration = client.Configuration()
        configuration.host = k8s_host
        configuration.api_key = {"authorization": f"Bearer {k8s_token}"}
        
        if os.getenv('KUBERNETES_SKIP_SSL_VERIFY', 'false').lower() == 'true':
            configuration.verify_ssl = False
        
        client.Configuration.set_default(configuration)
        self.logger.info(f"Using explicit configuration with host: {k8s_host}")
    
    def _get_kubernetes_token(self) -> str:
        """Get Kubernetes token from environment or file"""
        token = os.getenv('KUBERNETES_TOKEN', '')
        if not token and os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token'):
            with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
                token = f.read().strip()
        return token

    def list_pods_on_node(self, node_name: str):
        """List all pods on a specific node"""
        return self.client.list_pod_for_all_namespaces(
            field_selector=f"spec.nodeName={node_name}"
        )

class GPUMetricsCollector:
    """Class to collect GPU metrics using rocm-smi"""
    def __init__(self):
        self.logger = logging.getLogger('k8s-gpu-exporter')

    def get_metrics(self) -> Dict[str, GPUMetric]:
        """Collect GPU metrics using rocm-smi commands"""
        try:
            utilization = self._run_rocm_command(["rocm-smi", "--showuse"])
            memory = self._run_rocm_command(["rocm-smi", "--showmemuse"])
            power = self._run_rocm_command(["rocm-smi", "--showpower"])
            
            return self._parse_metrics(utilization, memory, power)
        except Exception as e:
            self.logger.error(f"Error collecting GPU metrics: {str(e)}")
            return {}

    def _run_rocm_command(self, command: List[str]) -> str:
        """Run a rocm-smi command and return output"""
        import subprocess
        result = subprocess.run(command, capture_output=True, text=True)
        return result.stdout

    def _parse_metrics(self, utilization: str, memory: str, power: str) -> Dict[str, GPUMetric]:
        """Parse rocm-smi output into structured metrics"""
        metrics = {}
        
        def parse_value(line: str, indicator: str) -> Optional[float]:
            try:
                if indicator in line:
                    value_part = line.split(indicator)[1].strip()
                    return float(''.join(c for c in value_part if c.isdigit() or c == '.'))
                return None
            except Exception:
                return None

        # Parse each metric type
        for gpu_line in utilization.splitlines():
            if 'GPU[' in gpu_line:
                gpu_id = gpu_line.split('[')[1].split(']')[0]
                if gpu_id not in metrics:
                    metrics[gpu_id] = GPUMetric()
                
                util_value = parse_value(gpu_line, "GPU use (%)")
                if util_value is not None:
                    metrics[gpu_id].utilization = util_value

        for gpu_line in memory.splitlines():
            if 'GPU[' in gpu_line:
                gpu_id = gpu_line.split('[')[1].split(']')[0]
                if gpu_id not in metrics:
                    metrics[gpu_id] = GPUMetric()
                
                mem_value = parse_value(gpu_line, "GPU Memory Allocated (VRAM%)")
                if mem_value is not None:
                    metrics[gpu_id].memory = mem_value

        for gpu_line in power.splitlines():
            if 'GPU[' in gpu_line:
                gpu_id = gpu_line.split('[')[1].split(']')[0]
                if gpu_id not in metrics:
                    metrics[gpu_id] = GPUMetric()
                
                power_value = parse_value(gpu_line, "Current Socket Graphics Package Power (W)")
                if power_value is not None:
                    metrics[gpu_id].power = power_value

        return metrics

class NodeManager:
    """Class to handle node-related operations"""
    def __init__(self):
        self.logger = logging.getLogger('k8s-gpu-exporter')
        self.node_name = self._get_node_name()

    def _get_node_name(self) -> str:
        """Get node name with fallback methods"""
        if node_name := os.getenv('NODE_NAME'):
            return node_name
            
        try:
            import subprocess
            return subprocess.check_output(['hostname']).decode().strip()
        except:
            return os.uname().nodename

class GPUExporter:
    """Main exporter class"""
    def __init__(self):
        self.logger = logging.getLogger('k8s-gpu-exporter')
        self.node_manager = NodeManager()
        self.k8s_client = KubernetesClient()
        self.metrics = PrometheusMetrics()
        self.collector = GPUMetricsCollector()

    def start(self, port: int, interval: int):
        """Start the exporter"""
        start_http_server(port)
        self.logger.info(f"Started exporter on port {port}")
        
        while True:
            try:
                self._collect_and_update_metrics()
                time.sleep(interval)
            except Exception as e:
                self.logger.error(f"Error in collection loop: {e}")
                self.metrics.collection_errors.labels(type='collection_loop').inc()
                time.sleep(interval)

    def _collect_and_update_metrics(self):
        """Collect and update metrics"""
        gpu_metrics = self.collector.get_metrics()
        if not gpu_metrics:
            return

        self._update_prometheus_metrics(gpu_metrics)

    def _update_prometheus_metrics(self, gpu_metrics: Dict[str, GPUMetric]):
        """Update Prometheus metrics"""
        try:
            pods = self.k8s_client.list_pods_on_node(self.node_manager.node_name)
            namespace_metrics = {}

            for gpu_id, metric in gpu_metrics.items():
                # Update GPU-level metrics
                self.metrics.gpu_utilization.labels(
                    node=self.node_manager.node_name,
                    gpu_id=gpu_id,
                    namespace='unmapped',
                    pod='unmapped'
                ).set(metric.utilization)

                self.metrics.gpu_memory.labels(
                    node=self.node_manager.node_name,
                    gpu_id=gpu_id,
                    namespace='unmapped',
                    pod='unmapped'
                ).set(metric.memory)

                self.metrics.gpu_power.labels(
                    node=self.node_manager.node_name,
                    gpu_id=gpu_id,
                    namespace='unmapped',
                    pod='unmapped'
                ).set(metric.power)

            # Update namespace-level metrics
            for namespace, metrics in namespace_metrics.items():
                self.metrics.namespace_gpu_utilization.labels(namespace=namespace).set(metrics.utilization)
                self.metrics.namespace_gpu_memory.labels(namespace=namespace).set(metrics.memory)
                self.metrics.namespace_gpu_count.labels(namespace=namespace).set(metrics.gpu_count)

        except Exception as e:
            self.logger.error(f"Error updating Prometheus metrics: {e}")
            self.metrics.collection_errors.labels(type='update_metrics').inc()

def main():
    """Main entry point"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
    )
    
    port = int(os.environ.get('EXPORTER_PORT', 9400))
    interval = int(os.environ.get('COLLECTION_INTERVAL', 300))
    
    try:
        exporter = GPUExporter()
        exporter.start(port, interval)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
