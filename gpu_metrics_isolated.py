import subprocess
import time
import requests
import pandas as pd
from datetime import datetime
import logging
from pathlib import Path
import socket
import docker
import sys
import os

class GPUMetricsSystem:
    def __init__(self, collection_interval: int = 60,
                 output_dir: str = "gpu_metrics"):
        """
        Initialize the GPU metrics system.
        
        Args:
            collection_interval: Time between collections in seconds
            output_dir: Directory to store metric files
        """
        self.collection_interval = collection_interval
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.hostname = socket.gethostname()
        self.docker_client = docker.from_env()
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.output_dir / 'gpu_metrics.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def check_docker_container(self) -> bool:
        """Check if metrics exporter container is running."""
        try:
            containers = self.docker_client.containers.list(
                filters={'name': 'device-metrics-exporter'}
            )
            return len(containers) > 0
        except docker.errors.APIError as e:
            self.logger.error(f"Docker API error: {e}")
            return False

    def start_docker_container(self) -> bool:
        """Start the metrics exporter container."""
        try:
            # Remove container if it exists but is not running
            try:
                old_container = self.docker_client.containers.get('device-metrics-exporter')
                old_container.remove(force=True)
                self.logger.info("Removed old container")
            except docker.errors.NotFound:
                pass

            # Start new container
            container = self.docker_client.containers.run(
                'rocm/device-metrics-exporter:v1.0.0',
                name='device-metrics-exporter',
                devices=['/dev/dri', '/dev/kfd'],
                ports={'5000/tcp': 5000},
                detach=True
            )
            self.logger.info("Started metrics exporter container")
            return True
        except docker.errors.APIError as e:
            self.logger.error(f"Failed to start container: {e}")
            return False

    def check_metrics_accessible(self) -> bool:
        """Check if metrics endpoint is accessible."""
        try:
            response = requests.get("http://localhost:5000/metrics", timeout=5)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException:
            return False

    def collect_metrics(self) -> dict:
        """Collect metrics from local GPU metrics exporter."""
        try:
            response = requests.get("http://localhost:5000/metrics", timeout=5)
            response.raise_for_status()
            return {
                'timestamp': datetime.now().isoformat(),
                'hostname': self.hostname,
                'metrics': response.text,
                'status': 'success'
            }
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to collect metrics: {str(e)}")
            return {
                'timestamp': datetime.now().isoformat(),
                'hostname': self.hostname,
                'error': str(e),
                'status': 'failed'
            }

    def parse_metrics(self, metrics_data: dict) -> dict:
        """Parse collected metrics into a structured format."""
        parsed_data = {
            'timestamp': metrics_data['timestamp'],
            'hostname': metrics_data['hostname'],
            'status': metrics_data['status']
        }
        
        if metrics_data['status'] == 'success':
            metric_lines = metrics_data['metrics'].split('\n')
            for line in metric_lines:
                if line and not line.startswith('#'):
                    try:
                        name, value = line.split(' ')
                        parsed_data[name] = float(value)
                    except ValueError:
                        continue
        else:
            parsed_data['error'] = metrics_data.get('error', 'Unknown error')
            
        return parsed_data

    def save_metrics(self, metrics: dict):
        """Save metrics to CSV file, appending if file exists."""
        current_date = datetime.now().strftime('%Y%m%d')
        csv_file = self.output_dir / f'gpu_metrics_{self.hostname}_{current_date}.csv'
        
        df = pd.DataFrame([metrics])
        
        if csv_file.exists():
            df.to_csv(csv_file, mode='a', header=False, index=False)
        else:
            df.to_csv(csv_file, index=False)
            
        self.logger.info(f"Saved metrics to {csv_file}")

    def setup_system(self) -> bool:
        """Setup the metrics collection system."""
        # Check if container is already running
        if not self.check_docker_container():
            self.logger.info("Metrics exporter container not running, starting it...")
            if not self.start_docker_container():
                self.logger.error("Failed to start metrics exporter container")
                return False
        
        # Wait for container to be ready
        retry_count = 0
        while not self.check_metrics_accessible():
            if retry_count >= 5:
                self.logger.error("Metrics endpoint not accessible after 5 retries")
                return False
            self.logger.info("Waiting for metrics endpoint to be accessible...")
            time.sleep(2)
            retry_count += 1
        
        self.logger.info("Metrics collection system ready")
        return True

    def run_collection(self, duration: int = None):
        """
        Run the metrics collection process.
        
        Args:
            duration: Optional duration in seconds to run the collection
        """
        if not self.setup_system():
            self.logger.error("Failed to setup metrics collection system")
            sys.exit(1)

        self.logger.info(f"Starting metrics collection on {self.hostname}")
        start_time = time.time()
        
        try:
            while True:
                # Check if we should stop
                if duration and (time.time() - start_time) > duration:
                    break
                    
                # Collect and save metrics
                metrics = self.collect_metrics()
                parsed_metrics = self.parse_metrics(metrics)
                self.save_metrics(parsed_metrics)
                
                time.sleep(self.collection_interval)
        except KeyboardInterrupt:
            self.logger.info("Stopping metrics collection...")
        finally:
            # Cleanup
            try:
                container = self.docker_client.containers.get('device-metrics-exporter')
                container.stop()
                container.remove()
                self.logger.info("Cleaned up metrics exporter container")
            except:
                pass

def main():
    # Check if running as root
    if os.geteuid() != 0:
        print("This script must be run as root (sudo) for Docker access")
        sys.exit(1)

    # Initialize and run collector
    collector = GPUMetricsSystem(
        collection_interval=60,  # Collect every minute
        output_dir="gpu_metrics"
    )
    
    # Run collection indefinitely (or specify duration in seconds)
    collector.run_collection()  # Run indefinitely
    # Or run for specific duration:
    # collector.run_collection(duration=24*60*60)  # 24 hours

if __name__ == "__main__":
    main()
