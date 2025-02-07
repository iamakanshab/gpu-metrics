#!/usr/bin/env python3

import sys
import subprocess
import time
import requests
import pandas as pd
from datetime import datetime
import logging
from pathlib import Path
import socket
import docker
import os
import json
from typing import Dict, List, Optional
import gzip

class GPUMetricsCollector:
    def __init__(self, collection_interval: int = 60,
                 output_dir: str = "/var/log/gpu-metrics",
                 retention_days: int = 7):
        """
        Initialize the GPU metrics collector.
        
        Args:
            collection_interval: Time between collections in seconds
            output_dir: Directory to store metric files
            retention_days: Number of days to keep historical data
        """
        self.collection_interval = collection_interval
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.hostname = socket.gethostname()
        self.retention_days = retention_days
        
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

    def collect_metrics(self) -> Optional[Dict]:
        """Collect metrics from the exporter."""
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

    def parse_prometheus_metrics(self, metrics_text: str) -> List[Dict]:
        """Parse Prometheus format metrics into structured data."""
        parsed_data = []
        current_metric = None
        
        for line in metrics_text.split('\n'):
            if not line or line.startswith('#'):
                continue
                
            try:
                # Split the line into name+labels and value
                metric_part, value = line.split(' ')
                
                # Parse the metric name and labels
                if '{' in metric_part:
                    metric_name = metric_part[:metric_part.index('{')]
                    labels_str = metric_part[metric_part.index('{')+1:metric_part.rindex('}')]
                    labels = dict(label.split('=') for label in labels_str.split(','))
                    labels = {k: v.strip('"') for k, v in labels.items()}
                else:
                    metric_name = metric_part
                    labels = {}
                
                metric_data = {
                    'name': metric_name,
                    'value': float(value),
                    'labels': labels
                }
                parsed_data.append(metric_data)
                
            except Exception as e:
                self.logger.warning(f"Failed to parse metric line: {line}, Error: {e}")
                continue
                
        return parsed_data

    def save_metrics(self, metrics: Dict):
        """Save metrics to compressed file."""
        current_date = datetime.now().strftime('%Y%m%d')
        current_hour = datetime.now().strftime('%H')
        
        # Create date directory if it doesn't exist
        date_dir = self.output_dir / current_date
        date_dir.mkdir(exist_ok=True)
        
        # Save to hourly file
        filename = f'gpu_metrics_{self.hostname}_{current_date}_{current_hour}.json.gz'
        filepath = date_dir / filename
        
        try:
            # If file exists, read existing data
            if filepath.exists():
                with gzip.open(filepath, 'rt') as f:
                    data = json.load(f)
                    if not isinstance(data, list):
                        data = [data]
            else:
                data = []
            
            # Append new metrics
            data.append(metrics)
            
            # Write back to file
            with gzip.open(filepath, 'wt') as f:
                json.dump(data, f)
                
            self.logger.info(f"Saved metrics to {filepath}")
            
        except Exception as e:
            self.logger.error(f"Failed to save metrics: {e}")

    def cleanup_old_data(self):
        """Remove data older than retention_days."""
        try:
            cutoff_date = (datetime.now().date() - pd.Timedelta(days=self.retention_days))
            
            for date_dir in self.output_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                    
                try:
                    dir_date = datetime.strptime(date_dir.name, '%Y%m%d').date()
                    if dir_date < cutoff_date:
                        for file in date_dir.iterdir():
                            file.unlink()
                        date_dir.rmdir()
                        self.logger.info(f"Removed old data directory: {date_dir}")
                except ValueError:
                    continue
                    
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    def run_collection(self):
        """Run the metrics collection process."""
        self.logger.info(f"Starting metrics collection on {self.hostname}")
        
        while True:
            try:
                # Collect metrics
                metrics = self.collect_metrics()
                if metrics['status'] == 'success':
                    # Parse and save metrics
                    parsed_metrics = self.parse_prometheus_metrics(metrics['metrics'])
                    metrics['parsed_metrics'] = parsed_metrics
                    self.save_metrics(metrics)
                
                # Cleanup old data daily
                if datetime.now().hour == 0 and datetime.now().minute < self.collection_interval:
                    self.cleanup_old_data()
                    
            except Exception as e:
                self.logger.error(f"Error in collection loop: {e}")
                
            time.sleep(self.collection_interval)

def main():
    # Initialize and run collector
    collector = GPUMetricsCollector(
        collection_interval=60,  # Collect every minute
        output_dir="/var/log/gpu-metrics",
        retention_days=7  # Keep 7 days of data
    )
    
    collector.run_collection()

if __name__ == "__main__":
    main()
