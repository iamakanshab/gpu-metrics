#!/usr/bin/env python3

# Standard library imports
import logging
import os
import sys
import time
import traceback
from typing import Dict, List, Optional, Tuple

# Third-party imports
from kubernetes import client, config
from kubernetes.config import config_exception
from prometheus_client import start_http_server, Gauge, Counter, Summary
import subprocess
import re

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
    def __init__(self, k8s_client: client.CoreV1Api, node_name: str):
        self.k8s_client = k8s_client
        self.current_node = node_name
        self.logger = logging.getLogger('k8s-gpu-exporter')
        
        # Static mapping of PCI bus IDs to indices
        self.bus_to_idx = {
            '0000:05:00.0': '0',
            '0000:26:00.0': '1',
            '0000:46:00.0': '2',
            '0000:65:00.0': '3',
            '0000:85:00.0': '4',
            '0000:a6:00.0': '5',
            '0000:c6:00.0': '6',
            '0000:e5:00.0': '7'
        }
        
        self.idx_to_bus = {v: k for k, v in self.bus_to_idx.items()}

    def get_pod_gpu_mappings(self) -> Dict[str, Dict[str, str]]:
        """Get mappings of GPU devices to pods and namespaces."""
        try:
            self.logger.info(f"Getting pod GPU mappings for node {self.current_node}")
            
            # List all pods on this node
            pods = self.k8s_client.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={self.current_node}"
            )
            
            self.logger.info(f"Found {len(pods.items)} pods on this node")
            
            gpu_mappings = {}
            for pod in pods.items:
                self.logger.info(f"Checking pod: {pod.metadata.namespace}/{pod.metadata.name}")
                
                # Log pod's resource requests and limits
                for container in pod.spec.containers:
                    if container.resources:
                        if hasattr(container.resources, 'limits') and container.resources.limits:
                            self.logger.info(f"Resource limits: {container.resources.limits}")
                        if hasattr(container.resources, 'requests') and container.resources.requests:
                            self.logger.info(f"Resource requests: {container.resources.requests}")
                
                gpu_info = self._get_pod_gpu_info(pod)
                if gpu_info:
                    self.logger.info(f"Found GPU assignment for pod {pod.metadata.name}: {gpu_info}")
                    for gpu_id in gpu_info:
                        gpu_mappings[gpu_id] = {
                            'namespace': pod.metadata.namespace,
                            'pod': pod.metadata.name
                        }
                        self.logger.info(f"Mapped GPU {gpu_id} to {pod.metadata.namespace}/{pod.metadata.name}")
                else:
                    self.logger.debug(f"No GPU assignment found for pod {pod.metadata.name}")
            
            self.logger.info(f"Final GPU mappings: {gpu_mappings}")
            return gpu_mappings

        except Exception as e:
            self.logger.error(f"Error getting pod GPU mappings: {str(e)}")
            return {}

    def _get_pod_gpu_info(self, pod) -> List[str]:
        """Extract GPU information from pod spec."""
        gpu_ids = []
        try:
            # Check for AMD GPU resource requests
            amd_gpu_resources = [
                'amd.com/gpu',
                'rocm.amd.com/gpu',
                'amd.com/mi300x',
                'amd.com/mi300',
                'amd.com/mi200'
            ]
            
            self.logger.debug(f"Checking pod {pod.metadata.name} for GPU assignments")
            
            for container in pod.spec.containers:
                # Check resource limits and requests
                for resources in [getattr(container.resources, 'limits', {}), 
                                getattr(container.resources, 'requests', {})]:
                    if resources:
                        for resource_name, value in resources.items():
                            if any(gpu_type in resource_name.lower() for gpu_type in amd_gpu_resources):
                                self.logger.info(f"Found AMD GPU resource: {resource_name} = {value} in pod {pod.metadata.name}")
                                # Add number of GPUs based on resource count
                                try:
                                    num_gpus = int(value)
                                    gpu_ids.extend([str(i) for i in range(len(gpu_ids), len(gpu_ids) + num_gpus)])
                                except (ValueError, TypeError):
                                    self.logger.warning(f"Invalid GPU resource value: {value}")

                # Check environment variables
                if container.env:
                    gpu_env_vars = [
                        'ROCR_VISIBLE_DEVICES',
                        'GPU_DEVICE_ORDINAL',
                        'HIP_VISIBLE_DEVICES',
                        'CUDA_VISIBLE_DEVICES'  # Some apps use CUDA env vars with ROCm
                    ]
                    
                    for env in container.env:
                        if env.name in gpu_env_vars and env.value:
                            self.logger.info(f"Found GPU environment variable {env.name}={env.value} in pod {pod.metadata.name}")
                            # Parse comma-separated GPU IDs
                            try:
                                gpu_list = [x.strip() for x in env.value.split(',') if x.strip()]
                                gpu_ids.extend(gpu_list)
                            except Exception as e:
                                self.logger.warning(f"Error parsing GPU env var: {e}")

            if gpu_ids:
                self.logger.info(f"Pod {pod.metadata.name} is using GPUs: {gpu_ids}")
            
        except Exception as e:
            self.logger.error(f"Error parsing pod GPU info: {str(e)}", exc_info=True)
        
        return list(set(gpu_ids))

    def _parse_gpu_ids(self, container) -> List[str]:
        """Parse GPU IDs from container spec."""
        gpu_ids = []
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
        
        # Get node name with fallbacks
        self.current_node = self._get_node_name()
        
        # Initialize Kubernetes client with fallback options
        try:
            config.load_incluster_config()
            self.logger.info("Successfully loaded in-cluster configuration")
        except config.ConfigException:
            try:
                self.logger.info("Not in cluster, trying kubeconfig...")
                config.load_kube_config()
                self.logger.info("Successfully loaded kubeconfig configuration")
            except Exception as e:
                self.logger.warning(f"Failed to load kubeconfig: {e}")
                self.logger.info("Falling back to explicit k8s configuration")
                
                k8s_host = os.getenv('KUBERNETES_HOST', 'https://kubernetes.default.svc')
                k8s_token = os.getenv('KUBERNETES_TOKEN', '')
                
                if not k8s_token and os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token'):
                    with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
                        k8s_token = f.read().strip()
                
                configuration = client.Configuration()
                configuration.host = k8s_host
                configuration.api_key = {"authorization": f"Bearer {k8s_token}"}
                
                if os.getenv('KUBERNETES_SKIP_SSL_VERIFY', 'false').lower() == 'true':
                    configuration.verify_ssl = False
                
                client.Configuration.set_default(configuration)
                self.logger.info(f"Using explicit configuration with host: {k8s_host}")
        
        self.k8s_client = client.CoreV1Api()
        self.gpu_mapper = GPUPodMapper(self.k8s_client, self.current_node)
        self.logger.info(f"Exporter initialized on node: {self.current_node}")
        
        # Print available nodes for debugging
        try:
            nodes = self.k8s_client.list_node()
            self.logger.info("Available nodes in cluster:")
            for node in nodes.items:
                self.logger.info(f"- {node.metadata.name}")
        except Exception as e:
            self.logger.error(f"Error listing nodes: {e}")

    def _get_node_name(self) -> str:
        """Get the node name with various fallback methods."""
        # Try environment variable first
        node_name = os.getenv('NODE_NAME')
        if node_name:
            self.logger.info(f"Using NODE_NAME from environment: {node_name}")
            return node_name
            
        # Try hostname
        try:
            hostname = subprocess.check_output(['hostname']).decode().strip()
            self.logger.info(f"Using hostname: {hostname}")
            return hostname
        except:
            pass
            
        # Fallback to uname
        node_name = os.uname().nodename
        self.logger.info(f"Using uname nodename: {node_name}")
        return node_name

def get_gpu_metrics(self) -> Dict[str, Dict[str, float]]:
    """Get GPU metrics using rocm-smi."""
    try:
        # Get GPU utilization
        cmd_util = ["rocm-smi", "--showuse"]
        result_util = subprocess.run(cmd_util, capture_output=True, text=True)
        
        # Get memory usage
        cmd_mem = ["rocm-smi", "--showmemuse"]
        result_mem = subprocess.run(cmd_mem, capture_output=True, text=True)
        
        # Get power usage
        cmd_power = ["rocm-smi", "--showpower"]
        result_power = subprocess.run(cmd_power, capture_output=True, text=True)
        
        if any(r.returncode != 0 for r in [result_util, result_mem, result_power]):
            self.logger.error("Error running rocm-smi commands")
            return {}
        
        # Parse the output
        metrics = {}
        
        # Helper function to extract GPU usage percentage
        def extract_gpu_usage(line: str) -> float:
            try:
                if 'GPU use (%)' in line:
                    return float(line.split(':')[1].strip())
                return 0.0
            except (ValueError, IndexError):
                return 0.0
        
        # Helper function to extract memory percentage
        def extract_memory(line: str) -> float:
            try:
                if 'GPU Memory Allocated (VRAM%)' in line:
                    return float(line.split(':')[1].strip())
                return 0.0
            except (ValueError, IndexError):
                return 0.0
                
        # Helper function to extract power value
        def extract_power(line: str) -> float:
            try:
                if 'Current Socket Graphics Package Power (W)' in line:
                    return float(line.split(':')[1].strip().split()[0])
                return 0.0
            except (ValueError, IndexError):
                return 0.0
        
        # Parse GPU utilization
        current_gpu = None
        for line in result_util.stdout.splitlines():
            if line.startswith('GPU['):
                current_gpu = line.split('[')[1].split(']')[0]
                if current_gpu not in metrics:
                    metrics[current_gpu] = {}
            if current_gpu is not None and 'GPU use (%)' in line:
                metrics[current_gpu]['utilization'] = extract_gpu_usage(line)
        
        # Parse memory usage
        current_gpu = None
        for line in result_mem.stdout.splitlines():
            if line.startswith('GPU['):
                current_gpu = line.split('[')[1].split(']')[0]
                if current_gpu not in metrics:
                    metrics[current_gpu] = {}
            if current_gpu is not None and 'GPU Memory Allocated (VRAM%)' in line:
                metrics[current_gpu]['memory'] = extract_memory(line)
        
        # Parse power usage
        current_gpu = None
        for line in result_power.stdout.splitlines():
            if line.startswith('GPU['):
                current_gpu = line.split('[')[1].split(']')[0]
                if current_gpu not in metrics:
                    metrics[current_gpu] = {}
            if current_gpu is not None and 'Current Socket Graphics Package Power (W)' in line:
                metrics[current_gpu]['power'] = extract_power(line)
        
        self.logger.info(f"Collected metrics for {len(metrics)} GPUs: {metrics}")
        return metrics
            
    except Exception as e:
        self.logger.error(f"Error getting GPU metrics: {str(e)}")
        return {}
        
    # def get_gpu_metrics(self) -> Dict[str, Dict[str, float]]:
    #     """Get GPU metrics using rocm-smi."""
    #     try:
    #         # Get GPU utilization
    #         cmd_util = ["rocm-smi", "--showuse"]
    #         result_util = subprocess.run(cmd_util, capture_output=True, text=True)
            
    #         # Get memory usage
    #         cmd_mem = ["rocm-smi", "--showmemuse"]
    #         result_mem = subprocess.run(cmd_mem, capture_output=True, text=True)
            
    #         # Get power usage
    #         cmd_power = ["rocm-smi", "--showpower"]
    #         result_power = subprocess.run(cmd_power, capture_output=True, text=True)
            
    #         if any(r.returncode != 0 for r in [result_util, result_mem, result_power]):
    #             self.logger.error("Error running rocm-smi commands")
    #             return {}
            
    #         # Parse the output
    #         metrics = {}
            
    #         # Helper function to extract percentage from string
    #         def extract_percentage(line: str) -> float:
    #             try:
    #                 return float(re.search(r'(\d+(?:\.\d+)?)\s*%', line).group(1))
    #             except (AttributeError, ValueError):
    #                 return 0.0
            
    #         # Helper function to extract power value
    #         def extract_power(line: str) -> float:
    #             try:
    #                 return float(re.search(r'(\d+(?:\.\d+)?)\s*W', line).group(1))
    #             except (AttributeError, ValueError):
    #                 return 0.0
            
    #         # Parse GPU utilization
    #         gpu_counter = 0
    #         for line in result_util.stdout.splitlines():
    #             if 'GPU' in line and gpu_counter < 8:  # Only process 8 GPUs
    #                 gpu_id = str(gpu_counter)
    #                 metrics[gpu_id] = {'utilization': extract_percentage(line)}
    #                 gpu_counter += 1
            
    #         # Parse memory usage
    #         gpu_counter = 0
    #         for line in result_mem.stdout.splitlines():
    #             if 'GPU' in line and gpu_counter < 8:  # Only process 8 GPUs
    #                 gpu_id = str(gpu_counter)
    #                 if gpu_id not in metrics:
    #                     metrics[gpu_id] = {}
    #                 metrics[gpu_id]['memory'] = extract_percentage(line)
    #                 gpu_counter += 1
            
    #         # Parse power usage
    #         gpu_counter = 0
    #         for line in result_power.stdout.splitlines():
    #             if 'GPU' in line and gpu_counter < 8:  # Only process 8 GPUs
    #                 gpu_id = str(gpu_counter)
    #                 if gpu_id not in metrics:
    #                     metrics[gpu_id] = {}
    #                 metrics[gpu_id]['power'] = extract_power(line)
    #                 gpu_counter += 1
            
    #         self.logger.info(f"Collected metrics for {len(metrics)} GPUs")
    #         return metrics
            
    #     except Exception as e:
    #         self.logger.error(f"Error getting GPU metrics: {str(e)}")
    #         return {}

    def update_metrics(self, gpu_metrics: Dict[str, Dict[str, float]]):
        """Update Prometheus metrics with namespace awareness."""
        try:
            gpu_mappings = self.gpu_mapper.get_pod_gpu_mappings()
            
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
            
        except Exception as e:
            self.logger.error(f"Error updating metrics: {e}")
            self.metrics.collection_errors.labels(type='update_metrics').inc()

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

    def collect_metrics(self):
        """Collect and update GPU metrics."""
        try:
            self.logger.info("Starting metrics collection...")
            gpu_metrics = self.get_gpu_metrics()
            if gpu_metrics:
                self.update_metrics(gpu_metrics)
                self.logger.info("Metrics collection completed successfully")
            else:
                self.logger.error("Failed to collect GPU metrics")
        except Exception as e:
            self.logger.error(f"Error in collect_metrics: {e}")
            self.metrics.collection_errors.labels(type='collect_metrics').inc()

def main():
    try:
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
        )
        logger = logging.getLogger('k8s-gpu-exporter')

        # Get configuration from environment variables
        port = int(os.environ.get('EXPORTER_PORT', 9400))
        collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 300))
        
        # Get node name from environment or prompt user
        node_name = os.environ.get('NODE_NAME')
        if not node_name:
            # List available nodes
            config.load_kube_config()
            k8s_client = client.CoreV1Api()
            nodes = k8s_client.list_node()
            
            logger.info("\nAvailable nodes in cluster:")
            for node in nodes.items:
                logger.info(f"- {node.metadata.name}")
            
            # Prompt for node name
            logger.info("\nPlease set the NODE_NAME environment variable to one of the above nodes.")
            logger.info("Example: export NODE_NAME=node1")
            sys.exit(1)
        
        # Additional environment variables for k8s configuration
        os.environ.setdefault('KUBERNETES_HOST', 'https://kubernetes.default.svc')
        os.environ.setdefault('KUBERNETES_SKIP_SSL_VERIFY', 'false')

        logger.info(f"Starting namespace-aware GPU exporter on port {port}")
        logger.info(f"Collection interval: {collection_interval} seconds")
        logger.info(f"Using node name: {node_name}")
        
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
