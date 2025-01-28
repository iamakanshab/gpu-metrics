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
import socket

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('k8s-gpu-exporter')

def check_port_availability(port):
    """Check if port is available and log network info."""
    try:
        # Log all network interfaces
        interfaces_output = subprocess.run(['ip', 'addr'], capture_output=True, text=True)
        logger.info(f"Network interfaces:\n{interfaces_output.stdout}")
        
        # Try binding to the port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('0.0.0.0', port))
        sock.close()
        logger.info(f"Port {port} is available")
        return True
    except Exception as e:
        logger.error(f"Port check failed: {e}")
        return False

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

def main():
    try:
        port = int(os.environ.get('EXPORTER_PORT', 9400))
        collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 30))

        logger.info(f"Starting Kubernetes GPU exporter on port {port}")
        logger.info(f"Collection interval: {collection_interval} seconds")
        
        # Check port availability
        if not check_port_availability(port):
            logger.error(f"Port {port} is not available")
            sys.exit(1)
        
        # Log network info before starting server
        logger.info("Starting HTTP server...")
        try:
            start_http_server(port, addr='0.0.0.0')
            logger.info(f"HTTP server started successfully on port {port}")
        except Exception as e:
            logger.error(f"Failed to start HTTP server: {e}")
            sys.exit(1)
        
        # Log successful startup
        logger.info("Server started successfully")
        
        # Test the metrics endpoint
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.connect(('127.0.0.1', port))
            test_socket.close()
            logger.info("Metrics endpoint is accessible locally")
        except Exception as e:
            logger.error(f"Metrics endpoint test failed: {e}")
        
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
