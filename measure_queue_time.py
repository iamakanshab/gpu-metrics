#!/usr/bin/env python3
import subprocess
import json
import pandas as pd
import numpy as np
import time
import os
import datetime
import matplotlib.pyplot as plt
from pathlib import Path

class PodQueueTimeCollector:
    def __init__(self, duration_mins=120, interval_secs=300, output_dir=None):
        """
        Initialize the collector
        
        Args:
            duration_mins: Collection duration in minutes
            interval_secs: Interval between collections in seconds
            output_dir: Directory to store results (default: auto-generated)
        """
        self.duration_mins = duration_mins
        self.interval_secs = interval_secs
        
        # Create timestamp for output directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or f"pod_queue_times_{timestamp}"
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize dataframes
        self.summary_df = pd.DataFrame(columns=['Timestamp', 'Namespace', 'Pod', 'QueueTime'])
        self.aggregated_df = pd.DataFrame(columns=['Timestamp', 'Namespace', 'PodCount', 'MinQueueTime', 'MaxQueueTime', 'AvgQueueTime'])
        
        print(f"Starting collection of pod queue times for {duration_mins} minutes.")
        print(f"Data will be saved to {self.output_dir}/")
    
    def run_kubectl_command(self):
        """Run kubectl command and parse the output"""
        try:
            # Run kubectl command
            result = subprocess.run(
                ["kubectl", "get", "pods", "--all-namespaces", "-o", "json"],
                capture_output=True, text=True, check=True
            )
            
            # Parse JSON output
            pods_data = json.loads(result.stdout)
            
            # Process pod data
            queue_times = []
            for pod in pods_data['items']:
                if pod.get('status', {}).get('startTime'):
                    namespace = pod['metadata']['namespace']
                    pod_name = pod['metadata']['name']
                    
                    # Parse timestamps
                    created_time = pd.to_datetime(pod['metadata']['creationTimestamp'])
                    start_time = pd.to_datetime(pod['status']['startTime'])
                    
                    # Calculate queue time in seconds
                    queue_time = (start_time - created_time).total_seconds()
                    
                    queue_times.append({
                        'Namespace': namespace,
                        'Pod': pod_name,
                        'QueueTime': queue_time
                    })
                    
            return queue_times
        
        except subprocess.CalledProcessError as e:
            print(f"Error running kubectl command: {e}")
            return []
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON output: {e}")
            return []
    
    def calculate_namespace_stats(self, queue_data, timestamp):
        """Calculate statistics per namespace from queue data"""
        if not queue_data:
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(queue_data)
        
        # Group by namespace and calculate statistics
        namespace_stats = df.groupby('Namespace').agg(
            PodCount=('Pod', 'count'),
            MinQueueTime=('QueueTime', 'min'),
            MaxQueueTime=('QueueTime', 'max'),
            AvgQueueTime=('QueueTime', 'mean')
        ).reset_index()
        
        # Add timestamp
        namespace_stats['Timestamp'] = timestamp
        
        return namespace_stats
    
    def collect_data(self):
        """Collect data at regular intervals for the specified duration"""
        # Calculate number of iterations
        iterations = int(self.duration_mins * 60 / self.interval_secs)
        
        for i in range(1, iterations + 1):
            # Get current timestamp
            timestamp = datetime.datetime.now()
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            timestamp_file = timestamp.strftime("%Y%m%d_%H%M%S")
            
            print(f"[{i}/{iterations}] Collecting data at {timestamp_str}...")
            
            # Create snapshot file
            snapshot_file = Path(self.output_dir) / f"snapshot_{timestamp_file}.txt"
            with open(snapshot_file, 'w') as f:
                f.write(f"# Pod Queue Times - {timestamp_str}\n\n")
            
            # Collect data
            queue_data = self.run_kubectl_command()
            
            # Save raw data to snapshot file
            with open(snapshot_file, 'a') as f:
                for item in queue_data:
                    f.write(f"{item['Namespace']} {item['Pod']} {item['QueueTime']:.2f} seconds\n")
                
                # Add simple stats
                f.write(f"\n# Summary Stats\n")
                f.write(f"Total pods analyzed: {len(queue_data)}\n")
            
            # Add data to summary DataFrame
            if queue_data:
                df = pd.DataFrame(queue_data)
                df['Timestamp'] = timestamp_str
                self.summary_df = pd.concat([self.summary_df, df], ignore_index=True)
                
                # Calculate and store namespace statistics
                namespace_stats = self.calculate_namespace_stats(queue_data, timestamp_str)
                self.aggregated_df = pd.concat([self.aggregated_df, namespace_stats], ignore_index=True)
            
            # Wait for next interval if not the last iteration
            if i < iterations:
                print(f"Waiting {self.interval_secs} seconds until next collection...")
                time.sleep(self.interval_secs)
        
        # Save final dataframes
        self.summary_df.to_csv(Path(self.output_dir) / "summary.csv", index=False)
        self.aggregated_df.to_csv(Path(self.output_dir) / "aggregated_stats.csv", index=False)
        
        print(f"Collection complete! Results saved to {self.output_dir}/")
    
    def generate_report(self):
        """Generate a comprehensive final report"""
        if self.summary_df.empty:
            print("No data collected, cannot generate report.")
            return
        
        # Prepare final report file
        report_file = Path(self.output_dir) / "final_report.txt"
        
        with open(report_file, 'w') as f:
            f.write("# Pod Queue Time - Final Report\n")
            
            # Collection period info
            start_time = self.summary_df['Timestamp'].min()
            end_time = self.summary_df['Timestamp'].max()
            f.write(f"Collection period: {start_time} to {end_time}\n")
            f.write(f"Total snapshots: {self.summary_df['Timestamp'].nunique()}\n\n")
            
            # Overall statistics by namespace
            f.write("## Overall Queue Time Statistics By Namespace\n\n")
            f.write("Namespace,TotalPods,MinQueueTime(s),MaxQueueTime(s),AvgQueueTime(s)\n")
            
            # Calculate overall stats
            overall_stats = self.summary_df.groupby('Namespace').agg(
                TotalPods=('Pod', 'nunique'),
                MinQueueTime=('QueueTime', 'min'),
                MaxQueueTime=('QueueTime', 'max'),
                AvgQueueTime=('QueueTime', 'mean')
            ).reset_index()
            
            # Write to file
            for _, row in overall_stats.iterrows():
                f.write(f"{row['Namespace']},{row['TotalPods']},{row['MinQueueTime']:.2f},{row['MaxQueueTime']:.2f},{row['AvgQueueTime']:.2f}\n")
            
            # Top 10 pods with longest queue times
            f.write("\n## Top 10 Pods With Longest Queue Times\n\n")
            top_pods = self.summary_df.sort_values('QueueTime', ascending=False).drop_duplicates(['Namespace', 'Pod']).head(10)
            for _, row in top_pods.iterrows():
                f.write(f"{row['Namespace']},{row['Pod']},{row['QueueTime']:.2f} seconds\n")
            
            # Queue time trend analysis
            f.write("\n## Queue Time Trend Analysis\n")
            f.write("Average queue time by collection interval:\n")
            
            trend_data = self.summary_df.groupby('Timestamp')['QueueTime'].mean().reset_index()
            for _, row in trend_data.iterrows():
                f.write(f"{row['Timestamp']},{row['QueueTime']:.2f}\n")
        
        print(f"Comprehensive report saved to {report_file}")
    
    
    def run(self):
        """Run the entire collection and analysis process"""
        self.collect_data()
        self.generate_report()
        
        print("All done!")


if __name__ == "__main__":
    # For testing, you can use a shorter duration
    collector = PodQueueTimeCollector(duration_mins=3, interval_secs=60)
    
    # For regular use
    # collector = PodQueueTimeCollector(duration_mins=720, interval_secs=300)
    collector.run()
