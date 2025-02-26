#!/usr/bin/env python3
import subprocess
import json
import pandas as pd
import time
import os
import datetime
from pathlib import Path

class PodQueueTimeCollector:
    def __init__(self, duration_mins=3, interval_secs=60, output_dir=None):
        """
        Initialize the collector
        
        Args:
            duration_mins: Collection duration in minutes (default: 3 for testing)
            interval_secs: Interval between collections in seconds (default: 60 for testing)
            output_dir: Directory to store results (default: auto-generated)
        """
        self.duration_mins = duration_mins
        self.interval_secs = interval_secs
        
        # Create timestamp for output directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or f"pod_queue_times_test_{timestamp}"
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize dataframes
        self.summary_df = pd.DataFrame(columns=['Timestamp', 'Namespace', 'Pod', 'QueueTime'])
        self.aggregated_df = pd.DataFrame(columns=['Timestamp', 'Namespace', 'PodCount', 'MinQueueTime', 'MaxQueueTime', 'AvgQueueTime'])
        
        print(f"Starting TEST collection of pod queue times for {duration_mins} minutes.")
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
                
                # Add namespace stats to snapshot file
                if queue_data:
                    f.write("\n# Stats by Namespace\n")
                    f.write("Namespace, PodCount, MinQueueTime, MaxQueueTime, AvgQueueTime\n")
                    
                    df = pd.DataFrame(queue_data)
                    namespace_stats = df.groupby('Namespace').agg(
                        PodCount=('Pod', 'count'),
                        MinQueueTime=('QueueTime', 'min'),
                        MaxQueueTime=('QueueTime', 'max'),
                        AvgQueueTime=('QueueTime', 'mean')
                    ).reset_index()
                    
                    for _, row in namespace_stats.iterrows():
                        f.write(f"{row['Namespace']}, {row['PodCount']}, {row['MinQueueTime']:.2f}, {row['MaxQueueTime']:.2f}, {row['AvgQueueTime']:.2f}\n")
            
            # Add data to summary DataFrame
            if queue_data:
                df = pd.DataFrame(queue_data)
                df['Timestamp'] = timestamp_str
                self.summary_df = pd.concat([self.summary_df, df], ignore_index=True)
            
            # Wait for next interval if not the last iteration
            if i < iterations:
                print(f"Waiting {self.interval_secs} seconds until next collection...")
                time.sleep(self.interval_secs)
        
        # Save final dataframes
        self.summary_df.to_csv(Path(self.output_dir) / "summary.csv", index=False)
        
        print(f"Collection complete! Results saved to {self.output_dir}/")
        
        # Display sample of collected data
        print("\nSample of collected data:")
        if not self.summary_df.empty:
            print(self.summary_df.head(5).to_string())
        else:
            print("No data was collected.")
    
    def generate_report(self):
        """Generate a simple final report"""
        if self.summary_df.empty:
            print("No data collected, cannot generate report.")
            return
        
        # Prepare final report file
        report_file = Path(self.output_dir) / "test_report.txt"
        
        with open(report_file, 'w') as f:
            f.write("# Pod Queue Time - Test Report\n")
            
            # Collection period info
            start_time = self.summary_df['Timestamp'].min()
            end_time = self.summary_df['Timestamp'].max()
            f.write(f"Collection period: {start_time} to {end_time}\n")
            f.write(f"Total snapshots: {self.summary_df['Timestamp'].nunique()}\n\n")
            
            # Overall statistics
            f.write("## Overall Stats\n\n")
            total_pods = len(self.summary_df['Pod'].unique())
            avg_queue_time = self.summary_df['QueueTime'].mean()
            max_queue_time = self.summary_df['QueueTime'].max()
            min_queue_time = self.summary_df['QueueTime'].min()
            
            f.write(f"Total unique pods: {total_pods}\n")
            f.write(f"Average queue time: {avg_queue_time:.2f} seconds\n")
            f.write(f"Maximum queue time: {max_queue_time:.2f} seconds\n")
            f.write(f"Minimum queue time: {min_queue_time:.2f} seconds\n\n")
            
            # Namespace breakdown
            f.write("## Namespace Breakdown\n\n")
            f.write("Namespace, PodCount, AvgQueueTime(s)\n")
            
            namespace_stats = self.summary_df.groupby('Namespace').agg(
                PodCount=('Pod', 'nunique'),
                AvgQueueTime=('QueueTime', 'mean')
            ).reset_index()
            
            for _, row in namespace_stats.iterrows():
                f.write(f"{row['Namespace']}, {row['PodCount']}, {row['AvgQueueTime']:.2f}\n")
        
        print(f"Test report saved to {report_file}")
    
    def run(self):
        """Run the test collection and analysis process"""
        self.collect_data()
        self.generate_report()
        print("Test complete!")


if __name__ == "__main__":
    # Test with short duration
    collector = PodQueueTimeCollector()  # Defaults to 3 minutes with 60-second intervals
    collector.run()
