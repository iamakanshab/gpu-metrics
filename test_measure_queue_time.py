#!/usr/bin/env python3
import subprocess
import json
import pandas as pd
import time
import os
import datetime
from pathlib import Path
import sys

class PodQueueTimeCollector:
    def __init__(self, duration_mins=3, interval_secs=60, output_dir=None, debug=True):
        """
        Initialize the collector
        
        Args:
            duration_mins: Collection duration in minutes
            interval_secs: Interval between collections in seconds
            output_dir: Directory to store results (default: auto-generated)
            debug: Enable debug output
        """
        self.duration_mins = duration_mins
        self.interval_secs = interval_secs
        self.debug = debug
        
        # Create timestamp for output directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or f"pod_queue_times_{timestamp}"
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize dataframes
        self.summary_df = pd.DataFrame(columns=['Timestamp', 'Namespace', 'Pod', 'QueueTime'])
        
        # Create debug log file
        self.debug_log = os.path.join(self.output_dir, "debug.log")
        
        print(f"Starting collection of pod queue times for {duration_mins} minutes.")
        print(f"Data will be saved to {self.output_dir}/")
        
        if self.debug:
            with open(self.debug_log, 'w') as f:
                f.write(f"Debug log started at {datetime.datetime.now()}\n")
                f.write(f"Collection parameters: duration={duration_mins} mins, interval={interval_secs} secs\n")
    
    def log_debug(self, message):
        """Write debug message to log file"""
        if self.debug:
            with open(self.debug_log, 'a') as f:
                f.write(f"{datetime.datetime.now()}: {message}\n")
            print(f"DEBUG: {message}")
    
    def run_kubectl_command(self):
        """Run kubectl command and parse the output"""
        try:
            self.log_debug("Running kubectl command to get all pods...")
            
            # Run kubectl command
            result = subprocess.run(
                ["kubectl", "get", "pods", "--all-namespaces", "-o", "json"],
                capture_output=True, text=True, check=True
            )
            
            # Parse JSON output
            pods_data = json.loads(result.stdout)
            
            # Log namespace information
            all_namespaces = sorted(set(pod['metadata']['namespace'] for pod in pods_data['items']))
            self.log_debug(f"Found {len(all_namespaces)} namespaces: {all_namespaces}")
            
            # Process pod data
            queue_times = []
            namespaces_with_data = set()
            namespaces_pods_count = {}
            
            self.log_debug(f"Processing {len(pods_data['items'])} pods...")
            
            for pod in pods_data['items']:
                namespace = pod['metadata']['namespace']
                
                # Count pods per namespace
                namespaces_pods_count[namespace] = namespaces_pods_count.get(namespace, 0) + 1
                
                if pod.get('status', {}).get('startTime'):
                    pod_name = pod['metadata']['name']
                    
                    # Parse timestamps
                    created_time = pod['metadata']['creationTimestamp']
                    start_time = pod['status']['startTime']
                    
                    # Debug output for timestamp inspection
                    if namespace == 'silo-gen-models' or self.debug:
                        self.log_debug(f"Pod {namespace}/{pod_name}: created={created_time}, started={start_time}")
                    
                    # Convert to datetime for calculation
                    created_time_dt = pd.to_datetime(created_time)
                    start_time_dt = pd.to_datetime(start_time)
                    
                    # Calculate queue time in seconds
                    queue_time = (start_time_dt - created_time_dt).total_seconds()
                    
                    # Debug specific namespaces
                    if namespace == 'silo-gen-models':
                        self.log_debug(f"silo-gen-models pod {pod_name}: queue_time={queue_time}")
                    
                    queue_times.append({
                        'Namespace': namespace,
                        'Pod': pod_name,
                        'QueueTime': queue_time,
                        'CreationTimestamp': created_time,
                        'StartTime': start_time
                    })
                    
                    # Track which namespaces have data
                    namespaces_with_data.add(namespace)
            
            # Log summary of data collection
            self.log_debug(f"Collected queue times for {len(queue_times)} pods")
            self.log_debug(f"Namespaces with queue time data: {sorted(namespaces_with_data)}")
            self.log_debug(f"Namespaces pod counts: {namespaces_pods_count}")
            
            # Check for missing namespaces
            missing_namespaces = set(all_namespaces) - namespaces_with_data
            if missing_namespaces:
                self.log_debug(f"WARNING: No queue time data for namespaces: {sorted(missing_namespaces)}")
                
                # Check why namespaces are missing
                for ns in missing_namespaces:
                    ns_pods = [pod for pod in pods_data['items'] if pod['metadata']['namespace'] == ns]
                    self.log_debug(f"Namespace {ns} has {len(ns_pods)} pods but no queue times. Checking why...")
                    
                    for pod in ns_pods:
                        pod_name = pod['metadata']['name']
                        start_time = pod.get('status', {}).get('startTime')
                        phase = pod.get('status', {}).get('phase', 'Unknown')
                        reason = pod.get('status', {}).get('reason', 'None')
                        
                        self.log_debug(f"  Pod {ns}/{pod_name} - Phase: {phase}, Reason: {reason}, StartTime: {start_time}")
            
            return queue_times
        
        except subprocess.CalledProcessError as e:
            self.log_debug(f"Error running kubectl command: {e}")
            self.log_debug(f"Error output: {e.stderr}")
            return []
        except json.JSONDecodeError as e:
            self.log_debug(f"Error parsing JSON output: {e}")
            return []
        except Exception as e:
            self.log_debug(f"Unexpected error: {str(e)}")
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
            self.log_debug(f"Starting collection iteration {i}/{iterations}")
            
            # Create snapshot file
            snapshot_file = Path(self.output_dir) / f"snapshot_{timestamp_file}.txt"
            with open(snapshot_file, 'w') as f:
                f.write(f"# Pod Queue Times - {timestamp_str}\n\n")
            
            # Collect data
            queue_data = self.run_kubectl_command()
            
            # Save raw data to snapshot file
            with open(snapshot_file, 'a') as f:
                f.write(f"# Raw Data\n")
                for item in queue_data:
                    f.write(f"{item['Namespace']} {item['Pod']} {item['QueueTime']:.2f} seconds (Created: {item['CreationTimestamp']}, Started: {item['StartTime']})\n")
                
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
                
                # Select only the columns we want to keep in the summary
                df_summary = df[['Timestamp', 'Namespace', 'Pod', 'QueueTime']]
                
                # Safely concatenate
                if self.summary_df.empty:
                    self.summary_df = df_summary
                else:
                    self.summary_df = pd.concat([self.summary_df, df_summary], ignore_index=True)
            
            # Wait for next interval if not the last iteration
            if i < iterations:
                print(f"Waiting {self.interval_secs} seconds until next collection...")
                time.sleep(self.interval_secs)
        
        # Save final dataframes
        self.summary_df.to_csv(Path(self.output_dir) / "summary.csv", index=False)
        
        # Save by-namespace summary
        if not self.summary_df.empty:
            namespace_summary = self.summary_df.groupby(['Timestamp', 'Namespace']).agg(
                PodCount=('Pod', 'count'),
                AvgQueueTime=('QueueTime', 'mean'),
                MaxQueueTime=('QueueTime', 'max'),
                MinQueueTime=('QueueTime', 'min')
            ).reset_index()
            
            namespace_summary.to_csv(Path(self.output_dir) / "namespace_summary.csv", index=False)
        
        print(f"Collection complete! Results saved to {self.output_dir}/")
    
    def generate_report(self):
        """Generate a comprehensive final report"""
        if self.summary_df.empty:
            print("No data collected, cannot generate report.")
            self.log_debug("No data collected, skipping report generation")
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
            
            # Overall stats
            total_pods = len(self.summary_df['Pod'].unique())
            total_namespaces = len(self.summary_df['Namespace'].unique())
            f.write(f"Total unique pods: {total_pods}\n")
            f.write(f"Total namespaces: {total_namespaces}\n\n")
            
            # Overall statistics by namespace
            f.write("## Overall Queue Time Statistics By Namespace\n\n")
            f.write("Namespace, TotalPods, MinQueueTime(s), MaxQueueTime(s), AvgQueueTime(s)\n")
            
            # Calculate overall stats
            overall_stats = self.summary_df.groupby('Namespace').agg(
                TotalPods=('Pod', 'nunique'),
                MinQueueTime=('QueueTime', 'min'),
                MaxQueueTime=('QueueTime', 'max'),
                AvgQueueTime=('QueueTime', 'mean')
            ).reset_index()
            
            # Write to file
            for _, row in overall_stats.iterrows():
                f.write(f"{row['Namespace']}, {row['TotalPods']}, {row['MinQueueTime']:.2f}, {row['MaxQueueTime']:.2f}, {row['AvgQueueTime']:.2f}\n")
            
            # Top 10 pods with longest queue times
            f.write("\n## Top 10 Pods With Longest Queue Times\n\n")
            f.write("Namespace, Pod, QueueTime(s), Timestamp\n")
            top_pods = self.summary_df.sort_values('QueueTime', ascending=False).head(10)
            for _, row in top_pods.iterrows():
                f.write(f"{row['Namespace']}, {row['Pod']}, {row['QueueTime']:.2f}, {row['Timestamp']}\n")
            
            # Queue time trend analysis
            f.write("\n## Queue Time Trend Analysis\n")
            f.write("Timestamp, AvgQueueTime(s), TotalPods\n")
            
            trend_data = self.summary_df.groupby('Timestamp').agg(
                AvgQueueTime=('QueueTime', 'mean'),
                TotalPods=('Pod', 'nunique')
            ).reset_index()
            
            for _, row in trend_data.iterrows():
                f.write(f"{row['Timestamp']}, {row['AvgQueueTime']:.2f}, {row['TotalPods']}\n")
        
        print(f"Comprehensive report saved to {report_file}")
        self.log_debug(f"Report generation complete")
    
    def run(self):
        """Run the entire collection and analysis process"""
        try:
            self.collect_data()
            self.generate_report()
            
            # Print a sample of the collected data
            print("\nSample of collected data:")
            if not self.summary_df.empty:
                # Try to find any data from silo-gen-models to verify it's captured
                silo_data = self.summary_df[self.summary_df['Namespace'] == 'silo-gen-models']
                if not silo_data.empty:
                    print("Data from silo-gen-models namespace:")
                    print(silo_data.head().to_string())
                else:
                    print(self.summary_df.head().to_string())
                
                # Summary stats
                print("\nSummary by namespace:")
                namespace_counts = self.summary_df['Namespace'].value_counts()
                print(namespace_counts.to_string())
            else:
                print("No data was collected.")
            
            print(f"\nCheck {self.debug_log} for detailed debug information.")
            print("All done!")
        except Exception as e:
            self.log_debug(f"Error during execution: {str(e)}")
            print(f"Error: {str(e)}")
            print(f"Check {self.debug_log} for more information.")


# Run script
if __name__ == "__main__":
    # Allow adjusting parameters via command line
    duration = 3  # Default 3 minutes for testing
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
    
    collector = PodQueueTimeCollector(duration_mins=duration, interval_secs=interval)
    collector.run()
