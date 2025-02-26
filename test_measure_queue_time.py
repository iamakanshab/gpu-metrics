#!/usr/bin/env python3
import subprocess
import json
import pandas as pd
import time
import os
import datetime
from pathlib import Path
import sys

class QueueTimeStatsCollector:
    def __init__(self, duration_mins=5, interval_secs=60, output_dir=None, exclude_namespaces=None):
        """
        Initialize the collector
        
        Args:
            duration_mins: Collection duration in minutes (default: 5)
            interval_secs: Interval between collections in seconds (default: 60)
            output_dir: Directory to store results (default: auto-generated)
            exclude_namespaces: List of namespaces to exclude (default: ['kube-system'])
        """
        self.duration_mins = duration_mins
        self.interval_secs = interval_secs
        self.exclude_namespaces = exclude_namespaces or ['kube-system']
        
        # Create timestamp for output directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or f"queue_stats_{timestamp}"
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize DataFrame to store all collected data
        self.all_data = pd.DataFrame(columns=['Timestamp', 'Namespace', 'Pod', 'QueueTime'])
        
        print(f"Starting queue time statistics collection for {duration_mins} minutes.")
        print(f"Excluding namespaces: {', '.join(self.exclude_namespaces)}")
        print(f"Data will be saved to {self.output_dir}/")
    
    def collect_queue_times(self):
        """Run kubectl command and collect queue times for all namespaces (except excluded ones)"""
        try:
            # Run kubectl command to get all pods across all namespaces
            result = subprocess.run(
                ["kubectl", "get", "pods", "--all-namespaces", "-o", "json"],
                capture_output=True, text=True, check=True
            )
            
            # Parse JSON output
            pods_data = json.loads(result.stdout)
            
            # Process pod data
            queue_times = []
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            for pod in pods_data['items']:
                namespace = pod['metadata']['namespace']
                
                # Skip excluded namespaces
                if namespace in self.exclude_namespaces:
                    continue
                    
                if pod.get('status', {}).get('startTime'):
                    pod_name = pod['metadata']['name']
                    
                    # Parse timestamps
                    created_time = pd.to_datetime(pod['metadata']['creationTimestamp'])
                    start_time = pd.to_datetime(pod['status']['startTime'])
                    
                    # Calculate queue time in seconds
                    queue_time = (start_time - created_time).total_seconds()
                    
                    # Skip unreasonable queue times (more than 30 days)
                    if queue_time > 30 * 24 * 60 * 60:
                        print(f"WARNING: Skipping pod {namespace}/{pod_name} with unreasonable queue time: {queue_time:.2f} seconds")
                        continue
                    
                    queue_times.append({
                        'Timestamp': timestamp,
                        'Namespace': namespace,
                        'Pod': pod_name,
                        'QueueTime': queue_time,
                        'CreationTime': pod['metadata']['creationTimestamp'],
                        'StartTime': pod['status']['startTime']
                    })
            
            return pd.DataFrame(queue_times)
            
        except subprocess.CalledProcessError as e:
            print(f"Error running kubectl command: {e}")
            return pd.DataFrame()
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON output: {e}")
            return pd.DataFrame()
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return pd.DataFrame()
    
    def run_collection(self):
        """Collect data at regular intervals for the specified duration"""
        # Calculate number of iterations
        iterations = int(self.duration_mins * 60 / self.interval_secs)
        
        for i in range(1, iterations + 1):
            print(f"[{i}/{iterations}] Collecting data...")
            
            # Collect data
            df = self.collect_queue_times()
            
            if not df.empty:
                # Add to overall dataset
                self.all_data = pd.concat([self.all_data, df], ignore_index=True)
                
                # Print current stats
                print(f"  Collected data for {len(df)} pods across {df['Namespace'].nunique()} namespaces")
                
                # Calculate and print overall stats for this iteration
                avg_queue = df['QueueTime'].mean()
                max_queue = df['QueueTime'].max()
                max_ns = df.loc[df['QueueTime'].idxmax(), 'Namespace'] if not df.empty else "N/A"
                max_pod = df.loc[df['QueueTime'].idxmax(), 'Pod'] if not df.empty else "N/A"
                
                print(f"  Average queue time: {avg_queue:.2f} seconds")
                print(f"  Maximum queue time: {max_queue:.2f} seconds (in {max_ns}/{max_pod})")
            else:
                print("  No data collected in this iteration")
            
            # Wait for next interval if not the last iteration
            if i < iterations:
                print(f"Waiting {self.interval_secs} seconds until next collection...")
                time.sleep(self.interval_secs)
    
    def generate_statistics(self):
        """Generate and print statistics from collected data"""
        if self.all_data.empty:
            print("No data collected, cannot generate statistics.")
            return
        
        # Save raw data
        self.all_data.to_csv(os.path.join(self.output_dir, "all_queue_times.csv"), index=False)
        
        # Calculate overall statistics
        print("\n=== OVERALL QUEUE TIME STATISTICS ===")
        total_pods = len(self.all_data['Pod'].unique())
        total_namespaces = len(self.all_data['Namespace'].unique())
        overall_avg = self.all_data['QueueTime'].mean()
        overall_max = self.all_data['QueueTime'].max()
        max_ns = self.all_data.loc[self.all_data['QueueTime'].idxmax(), 'Namespace'] if not self.all_data.empty else "N/A"
        max_pod = self.all_data.loc[self.all_data['QueueTime'].idxmax(), 'Pod'] if not self.all_data.empty else "N/A"
        
        print(f"Total unique pods: {total_pods}")
        print(f"Total namespaces: {total_namespaces}")
        print(f"Overall average queue time: {overall_avg:.2f} seconds")
        print(f"Overall maximum queue time: {overall_max:.2f} seconds (in {max_ns}/{max_pod})")
        
        # Calculate namespace-level statistics
        print("\n=== QUEUE TIME STATISTICS BY NAMESPACE ===")
        
        ns_stats = self.all_data.groupby('Namespace').agg(
            PodCount=('Pod', 'nunique'),
            AvgQueueTime=('QueueTime', 'mean'),
            MaxQueueTime=('QueueTime', 'max'),
            MinQueueTime=('QueueTime', 'min'),
            StdQueueTime=('QueueTime', 'std')
        ).reset_index()
        
        # Sort by average queue time (descending)
        ns_stats = ns_stats.sort_values('AvgQueueTime', ascending=False)
        
        # Create a formatted DataFrame for display
        display_df = ns_stats.copy()
        for col in ['AvgQueueTime', 'MaxQueueTime', 'MinQueueTime', 'StdQueueTime']:
            display_df[col] = display_df[col].round(2)
        
        # Display and save statistics
        print(display_df.to_string(index=False))
        ns_stats.to_csv(os.path.join(self.output_dir, "namespace_stats.csv"), index=False)
        
        # Identify top pods with longest queue times
        print("\n=== TOP 10 PODS WITH LONGEST QUEUE TIMES ===")
        top_pods = self.all_data.sort_values('QueueTime', ascending=False).drop_duplicates(['Namespace', 'Pod']).head(10)
        top_pods_display = top_pods[['Namespace', 'Pod', 'QueueTime', 'CreationTime', 'StartTime']].copy()
        top_pods_display['QueueTime'] = top_pods_display['QueueTime'].round(2)
        print(top_pods_display.to_string(index=False))
        top_pods.to_csv(os.path.join(self.output_dir, "top_pods.csv"), index=False)
        
        # Generate statistics report file
        report_file = os.path.join(self.output_dir, "queue_stats_report.txt")
        with open(report_file, 'w') as f:
            f.write("=== KUBERNETES POD QUEUE TIME STATISTICS ===\n\n")
            f.write(f"Report generated: {datetime.datetime.now()}\n")
            f.write(f"Collection period: {self.duration_mins} minutes\n")
            f.write(f"Collection interval: {self.interval_secs} seconds\n")
            f.write(f"Excluded namespaces: {', '.join(self.exclude_namespaces)}\n\n")
            
            f.write("=== OVERALL STATISTICS ===\n")
            f.write(f"Total unique pods: {total_pods}\n")
            f.write(f"Total namespaces: {total_namespaces}\n")
            f.write(f"Overall average queue time: {overall_avg:.2f} seconds\n")
            f.write(f"Overall maximum queue time: {overall_max:.2f} seconds (in {max_ns}/{max_pod})\n\n")
            
            f.write("=== STATISTICS BY NAMESPACE ===\n")
            f.write("Namespace, PodCount, AvgQueueTime, MaxQueueTime, MinQueueTime, StdQueueTime\n")
            for _, row in ns_stats.iterrows():
                f.write(f"{row['Namespace']}, {row['PodCount']}, {row['AvgQueueTime']:.2f}, {row['MaxQueueTime']:.2f}, {row['MinQueueTime']:.2f}, {row['StdQueueTime']:.2f}\n")
            
            f.write("\n=== TOP 10 PODS WITH LONGEST QUEUE TIMES ===\n")
            f.write("Namespace, Pod, QueueTime, CreationTime, StartTime\n")
            for _, row in top_pods.iterrows():
                f.write(f"{row['Namespace']}, {row['Pod']}, {row['QueueTime']:.2f}, {row['CreationTime']}, {row['StartTime']}\n")
        
        print(f"\nDetailed statistics report saved to: {report_file}")
    
    def run(self):
        """Run the entire collection and analysis process"""
        self.run_collection()
        self.generate_statistics()
        print("\nCollection and analysis complete!")


if __name__ == "__main__":
    # Parse command-line arguments
    duration = 5  # Default 5 minutes
    interval = 60  # Default 60 seconds
    
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            print(f"Invalid duration: {sys.argv[1]}. Using default: {duration} minutes.")
    
    if len(sys.argv) > 2:
        try:
            interval = int(sys.argv[2])
        except ValueError:
            print(f"Invalid interval: {sys.argv[2]}. Using default: {interval} seconds.")
    
    # Create and run collector
    collector = QueueTimeStatsCollector(duration_mins=duration, interval_secs=interval)
    collector.run()
