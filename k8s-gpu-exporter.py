#!/usr/bin/env python3
import logging
from logging.handlers import RotatingFileHandler
from prometheus_client import start_http_server, Gauge, Counter, Summary
import time
import os
from kubernetes import client, config
import subprocess
import sys
import traceback
import re
from typing import Dict, Optional, Any
import json
from datetime import datetime
import signal
import threading

class MetricsLogger:
    def __init__(self, log_dir: str = "/var/log/gpu-exporter"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        # Configure main logger
        self.logger = logging.getLogger('k8s-gpu-exporter')
        self.logger.setLevel(logging.INFO)

        # Console handler with detailed formatting
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - [%(levelname)s] - %(thread)d - %(message)s'
        ))
        self.logger.addHandler(console_handler)

        # File handler with rotation
        file_handler = RotatingFileHandler(
            f"{log_dir}/gpu_metrics.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - [%(levelname)s] - %(thread)d - %(pathname)s:%(lineno)d - %(message)s'
        ))
        self.logger.addHandler(file_handler)

        # Error file handler
        error_handler = RotatingFileHandler(
            f"{log_dir}/gpu_metrics_error.log",
            maxBytes=10*1024*1024,
            backupCount=5
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - [%(levelname)s] - %(thread)d - %(pathname)s:%(lineno)d\n'
            'Message: %(message)s\nStack Trace: %(stack_info)s\n'
        ))
        self.logger.addHandler(error_handler)

class MetricsCollector:
    """Handle GPU metrics collection and parsing."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.collection_duration = Summary(
            'gpu_metrics_collection_duration_seconds',
            'Time spent collecting GPU metrics'
        )
        self.parse_errors = Counter(
            'gpu_metrics_parse_errors_total',
            'Total number of GPU metric parsing errors'
        )
        self.command_errors = Counter(
            'gpu_metrics_command_errors_total',
            'Total number of rocm-smi command errors'
        )

    def _validate_metric_value(self, value: float, metric_name: str) -> Optional[float]:
        """Validate metric values are within expected ranges."""
        if metric_name in ['utilization', 'memory']:
            if 0 <= value <= 100:
                return value
            self.logger.warning(f"Invalid {metric_name} value: {value}")
            return None
        elif metric_name == 'power':
            if 0 <= value <= 1000:  # Assuming max 1000W per GPU
                return value
            self.logger.warning(f"Invalid power value: {value}")
            return None
        return value

    @collection_duration.time()
    def get_gpu_metrics(self) -> Optional[Dict[str, Dict[str, float]]]:
        """Get GPU metrics using rocm-smi with enhanced error handling."""
        try:
            # Run command with timeout
            result = subprocess.run(
                ['rocm-smi', '--showuse', '--showmemuse', '--showpower'],
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            if result.returncode != 0:
                self.command_errors.inc()
                self.logger.error(f"rocm-smi error: {result.stderr}")
                return None

            return self._parse_gpu_metrics(result.stdout)

        except subprocess.TimeoutExpired:
            self.command_errors.inc()
            self.logger.error("rocm-smi command timed out")
            return None
        except Exception as e:
            self.command_errors.inc()
            self.logger.error(f"Error collecting GPU metrics: {str(e)}", exc_info=True)
            return None

    def _parse_gpu_metrics(self, output: str) -> Dict[str, Dict[str, float]]:
        """Parse rocm-smi output with enhanced error handling."""
        metrics = {}
        current_gpu = None
        
        try:
            for line in output.split('\n'):
                line = line.strip()
                
                # Match GPU index
                gpu_match = re.match(r'GPU\[(\d+)\]', line)
                if gpu_match:
                    current_gpu = gpu_match.group(1)
                    if current_gpu not in metrics:
                        metrics[current_gpu] = {}
                    continue
                
                # Parse metrics only if we have a current GPU
                if current_gpu is not None:
                    self._parse_metric_line(line, current_gpu, metrics)

            # Validate we found all expected metrics
            self._validate_metrics_completeness(metrics)
            return metrics

        except Exception as e:
            self.parse_errors.inc()
            self.logger.error(f"Error parsing GPU metrics: {str(e)}", exc_info=True)
            return {}

    def _parse_metric_line(self, line: str, gpu_id: str, metrics: Dict[str, Dict[str, float]]):
        """Parse individual metric lines with validation."""
        try:
            if 'Current Socket Graphics Package Power (W):' in line:
                value = float(line.split(':')[1].strip())
                validated_value = self._validate_metric_value(value, 'power')
                if validated_value is not None:
                    metrics[gpu_id]['power'] = validated_value
                
            elif 'GPU use (%):' in line:
                value = float(line.split(':')[1].strip())
                validated_value = self._validate_metric_value(value, 'utilization')
                if validated_value is not None:
                    metrics[gpu_id]['utilization'] = validated_value
                
            elif 'GPU Memory Allocated (VRAM%):' in line:
                value = float(line.split(':')[1].strip())
                validated_value = self._validate_metric_value(value, 'memory')
                if validated_value is not None:
                    metrics[gpu_id]['memory'] = validated_value

        except ValueError as e:
            self.logger.warning(f"Error parsing value from line '{line}': {str(e)}")
            self.parse_errors.inc()

    def _validate_metrics_completeness(self, metrics: Dict[str, Dict[str, float]]):
        """Ensure all expected metrics are present for each GPU."""
        expected_metrics = {'power', 'utilization', 'memory'}
        for gpu_id, gpu_metrics in metrics.items():
            missing_metrics = expected_metrics - set(gpu_metrics.keys())
            if missing_metrics:
                self.logger.warning(f"Missing metrics {missing_metrics} for GPU {gpu_id}")

class K8sGPUMetrics:
    """Enhanced Prometheus metrics definitions."""
    
    def __init__(self):
        self.logger = logging.getLogger('k8s-gpu-exporter')
        self.logger.info("Initializing metrics...")
        
        # Basic metrics
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
        
        # Enhanced error tracking
        self.collection_errors = Counter(
            'k8s_gpu_collector_errors_total',
            'Total number of collection errors',
            ['type', 'error_message']
        )
        
        # Operational metrics
        self.last_collection_timestamp = Gauge(
            'k8s_gpu_last_collection_timestamp',
            'Timestamp of last successful metrics collection',
            ['node']
        )
        self.metrics_collection_duration = Summary(
            'k8s_gpu_metrics_collection_duration_seconds',
            'Time spent collecting GPU metrics'
        )
        
        self.logger.info("Metrics initialized successfully")

class K8sGPUExporter:
    """Enhanced GPU metrics exporter."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.logger.info("Initializing exporter...")
        
        self.metrics = K8sGPUMetrics()
        self.collector = MetricsCollector(logger)
        self.current_node = os.uname().nodename
        
        # Initialize kubernetes client with error handling
        self._init_kubernetes_client()
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)
        
        # Thread control
        self._stop_event = threading.Event()
        
        self.logger.info(f"Exporter initialized successfully on node: {self.current_node}")

    def _init_kubernetes_client(self):
        """Initialize Kubernetes client with error handling."""
        try:
            config.load_kube_config()
            self.k8s_client = client.CoreV1Api()
            
            # Test connection
            namespaces = self.k8s_client.list_namespace()
            self.logger.info(f"Connected to Kubernetes. Found {len(namespaces.items)} namespaces")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Kubernetes client: {str(e)}", exc_info=True)
            sys.exit(1)

    def _handle_sigterm(self, signum, frame):
        """Handle termination signals gracefully."""
        self.logger.info(f"Received signal {signum}. Starting graceful shutdown...")
        self._stop_event.set()

    @MetricsCollector.collection_duration.time()
    def update_metrics(self, gpu_metrics: Dict[str, Dict[str, float]]):
        """Update Prometheus metrics with enhanced error handling."""
        try:
            for gpu_id, metrics in gpu_metrics.items():
                self._update_gpu_metrics(gpu_id, metrics)
            
            # Update last successful collection timestamp
            self.metrics.last_collection_timestamp.labels(
                node=self.current_node
            ).set_to_current_time()
            
            self.logger.info(f"Successfully updated metrics for all GPUs")
            
        except Exception as e:
            self.logger.error(f"Error updating metrics: {str(e)}", exc_info=True)
            self.metrics.collection_errors.labels(
                type='update_metrics',
                error_message=str(e)
            ).inc()

    def _update_gpu_metrics(self, gpu_id: str, metrics: Dict[str, float]):
        """Update metrics for a single GPU with validation."""
        try:
            if 'utilization' in metrics:
                self.metrics.gpu_utilization.labels(
                    node=self.current_node,
                    gpu_id=gpu_id
                ).set(metrics['utilization'])
            
            if 'memory' in metrics:
                self.metrics.gpu_memory.labels(
                    node=self.current_node,
                    gpu_id=gpu_id
                ).set(metrics['memory'])
            
            if 'power' in metrics:
                self.metrics.gpu_power.labels(
                    node=self.current_node,
                    gpu_id=gpu_id
                ).set(metrics['power'])
                
            self.logger.debug(f"Updated metrics for GPU {gpu_id}: {metrics}")
            
        except Exception as e:
            self.logger.error(f"Error updating metrics for GPU {gpu_id}: {str(e)}")
            raise

    def collect_metrics(self):
        """Collect and update GPU metrics with enhanced error handling."""
        try:
            self.logger.info("Starting metrics collection...")
            
            # Get GPU metrics
            gpu_metrics = self.collector.get_gpu_metrics()
            if not gpu_metrics:
                self.logger.error("Failed to collect GPU metrics")
                return

            # Update Prometheus metrics
            self.update_metrics(gpu_metrics)
            self.logger.info("Metrics collection completed successfully")

        except Exception as e:
            self.logger.error(f"Error in collect_metrics: {str(e)}", exc_info=True)
            self.metrics.collection_errors.labels(
                type='collect_metrics',
                error_message=str(e)
            ).inc()

    def run(self, collection_interval: int):
        """Run the exporter with graceful shutdown."""
        while not self._stop_event.is_set():
            try:
                self.collect_metrics()
                # Use wait instead of sleep to respond to signals faster
                self._stop_event.wait(timeout=collection_interval)
            except Exception as e:
                self.logger.error(f"Error in collection loop: {str(e)}", exc_info=True)
                self._stop_event.wait(timeout=collection_interval)

def main():
    try:
        # Initialize logger
        logger_instance = MetricsLogger()
        logger = logger_instance.logger

        # Get configuration from environment
        port = int(os.environ.get('EXPORTER_PORT', 9400))
        collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 300))

        logger.info(f"Starting Kubernetes GPU exporter on port {port}")
        logger.info(f"Collection interval: {collection_interval} seconds")
        
        # Start metrics server
        start_http_server(port)
        
        # Initialize and run exporter
        exporter = K8sGPUExporter(logger)
        exporter.run(collection_interval)
        
    except Exception as e:
        logger.error(f"Fatal error in main: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
