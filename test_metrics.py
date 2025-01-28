#!/usr/bin/env python3
import requests
import time
from datetime import datetime
import json

def fetch_metrics(url="http://localhost:9400/metrics"):
    """Fetch metrics from the collector."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching metrics: {e}")
        return None

def parse_metrics(metrics_text):
    """Parse Prometheus metrics text format."""
    gpu_metrics = {
        'utilization': [],
        'memory': [],
        'power': [],
        'namespaces': set()
    }
    
    for line in metrics_text.split('\n'):
        if line.startswith('#'):
            continue
            
        if 'k8s_gpu_utilization' in line:
            parts = line.split()
            labels = parts[0].split('{')[1].split('}')[0]
            value = float(parts[1])
            namespace = [l.split('=')[1].strip('"') for l in labels.split(',') if 'namespace=' in l][0]
            gpu_metrics['utilization'].append((namespace, value))
            gpu_metrics['namespaces'].add(namespace)
            
        elif 'k8s_gpu_memory' in line:
            parts = line.split()
            labels = parts[0].split('{')[1].split('}')[0]
            value = float(parts[1])
            namespace = [l.split('=')[1].strip('"') for l in labels.split(',') if 'namespace=' in l][0]
            gpu_metrics['memory'].append((namespace, value))
            
        elif 'k8s_gpu_power' in line:
            parts = line.split()
            labels = parts[0].split('{')[1].split('}')[0]
            value = float(parts[1])
            namespace = [l.split('=')[1].strip('"') for l in labels.split(',') if 'namespace=' in l][0]
            gpu_metrics['power'].append((namespace, value))
    
    return gpu_metrics

def print_metrics_summary(metrics):
    """Print a summary of the collected metrics."""
    print("\n=== GPU Metrics Summary ===")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nNamespaces with GPU usage:")
    for namespace in sorted(metrics['namespaces']):
        print(f"\nNamespace: {namespace}")
        
        # Utilization
        util_metrics = [m[1] for m in metrics['utilization'] if m[0] == namespace]
        if util_metrics:
            avg_util = sum(util_metrics) / len(util_metrics)
            print(f"  GPU Utilization: {avg_util:.2f}%")
            
        # Memory
        mem_metrics = [m[1] for m in metrics['memory'] if m[0] == namespace]
        if mem_metrics:
            avg_mem = sum(mem_metrics) / len(mem_metrics)
            print(f"  Memory Usage: {avg_mem:.2f}%")
            
        # Power
        power_metrics = [m[1] for m in metrics['power'] if m[0] == namespace]
        if power_metrics:
            avg_power = sum(power_metrics) / len(power_metrics)
            print(f"  Power Usage: {avg_power:.2f}W")
    
    print("\n=========================")

def main():
    print("Starting GPU metrics verification...")
    collection_duration = 300  # 5 minutes
    interval = 30  # 30 seconds
    
    start_time = time.time()
    while time.time() - start_time < collection_duration:
        print(f"\nCollecting metrics... (Elapsed: {int(time.time() - start_time)}s)")
        
        metrics_text = fetch_metrics()
        if metrics_text:
            metrics = parse_metrics(metrics_text)
            print_metrics_summary(metrics)
        
        time.sleep(interval)
    
    print("\nMetrics collection completed!")

if __name__ == "__main__":
    main()
