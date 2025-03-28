#!/usr/bin/env python3
import subprocess
import json
import pandas as pd
import time
import os
import datetime
from pathlib import Path
import sys

class QueueTimeCollector:
    def __init__(self, output_dir=None, exclude_namespaces=None):
        """Initialize the collector with simplified parameters"""
        self.exclude_namespaces = exclude_namespaces or ['kube-system']
        
        # Hardcode the kubeconfig path
        self.kubeconfig = "/root/.kube/config"
        
        # Set up storage directory with timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d")
        self.output_dir = output_dir or f"queue_stats_{timestamp}"
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Path for persistent data
        self.persistent_db_path = os.path.join(self.output_dir, "queue_time_history.csv")
        
        # Load existing data or create new dataframe
        if os.path.exists(self.persistent_db_path):
            self.historical_data = pd.read_csv(self.persistent_db_path)
            print(f"Loaded {len(self.historical_data)} historical queue time records")
        else:
            self.historical_data = pd.DataFrame(columns=[
                'Timestamp', 'Namespace', 'Pod', 'PodUID', 'QueueTime', 
                'CreationTime', 'StartTime'
            ])
            print("Created new persistent queue time database")
    
    def format_time(self, seconds):
        """Format seconds into days, hours, minutes, seconds"""
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(days)}d {int(hours)}h {int(minutes)}m {round(seconds, 2)}s"
    
    def collect_queue_times(self):
        """Collect current queue times from the cluster"""
        try:
            # Run kubectl command
            kubectl_cmd = ["kubectl", f"--kubeconfig={self.kubeconfig}", "get", "pods", "--all-namespaces", "-o", "json"]
            result = subprocess.run(kubectl_cmd, capture_output=True, text=True, check=True)
            
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
                    pod_uid = pod['metadata']['uid']
                    
                    # Parse timestamps
                    created_time = pd.to_datetime(pod['metadata']['creationTimestamp'])
                    start_time = pd.to_datetime(pod['status']['startTime'])
                    
                    # Calculate queue time in seconds
                    queue_time = (start_time - created_time).total_seconds()
                    
                    # Skip unreasonable queue times
                    if queue_time > 30 * 24 * 60 * 60:
                        continue
                    
                    queue_times.append({
                        'Timestamp': timestamp,
                        'Namespace': namespace,
                        'Pod': pod_name,
                        'PodUID': pod_uid,
                        'QueueTime': queue_time,
                        'CreationTime': pod['metadata']['creationTimestamp'],
                        'StartTime': pod['status']['startTime']
                    })
            
            return pd.DataFrame(queue_times)
            
        except Exception as e:
            print(f"Error collecting queue times: {str(e)}")
            return pd.DataFrame()
    
    def update_persistent_storage(self, new_data):
        """Update persistent storage with new data and maintain 7-day window"""
        if not new_data.empty:
            # Add new data
            self.historical_data = pd.concat([self.historical_data, new_data], ignore_index=True)
            
            # Keep only last 7 days of data
            self.historical_data['Timestamp'] = pd.to_datetime(self.historical_data['Timestamp'])
            cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=7)
            self.historical_data = self.historical_data[self.historical_data['Timestamp'] >= cutoff_date]
            
            # Convert back to string for storage
            self.historical_data['Timestamp'] = self.historical_data['Timestamp'].dt.strftime("%Y-%m-%d %H:%M:%S")
            
            # Save to disk
            self.historical_data.to_csv(self.persistent_db_path, index=False)
            print(f"Updated persistent storage with {len(new_data)} new records")
            print(f"Total records in 7-day window: {len(self.historical_data)}")
    
    def generate_quick_stats(self):
        """Generate quick stats for current collection"""
        if self.historical_data.empty:
            print("No data available for statistics")
            return
        
        # Convert timestamps to datetime
        self.historical_data['Timestamp'] = pd.to_datetime(self.historical_data['Timestamp'])
        
        # Get last collection
        latest_timestamp = self.historical_data['Timestamp'].max()
        latest_data = self.historical_data[self.historical_data['Timestamp'] == latest_timestamp]
        
        print("\n=== LATEST COLLECTION STATISTICS ===")
        print(f"Timestamp: {latest_timestamp}")
        print(f"Pods collected: {len(latest_data)}")
        print(f"Namespaces: {latest_data['Namespace'].nunique()}")
        
        avg_queue = latest_data['QueueTime'].mean()
        max_queue = latest_data['QueueTime'].max()
        print(f"Average queue time: {self.format_time(avg_queue)} ({avg_queue:.2f}s)")
        print(f"Maximum queue time: {self.format_time(max_queue)} ({max_queue:.2f}s)")
        
        # Get 7-day statistics
        window_start = pd.Timestamp.now() - pd.Timedelta(days=7)
        window_data = self.historical_data[self.historical_data['Timestamp'] >= window_start]
        
        print("\n=== 7-DAY STATISTICS ===")
        print(f"Collection runs: {window_data['Timestamp'].nunique()}")
        print(f"Unique pods: {window_data['PodUID'].nunique()}")
        print(f"Namespaces: {window_data['Namespace'].nunique()}")
        
        avg_queue_7d = window_data['QueueTime'].mean()
        max_queue_7d = window_data['QueueTime'].max()
        print(f"7-day average queue time: {self.format_time(avg_queue_7d)} ({avg_queue_7d:.2f}s)")
        print(f"7-day maximum queue time: {self.format_time(max_queue_7d)} ({max_queue_7d:.2f}s)")
        
        # Top 3 namespaces by average queue time
        ns_stats = window_data.groupby('Namespace')['QueueTime'].mean().sort_values(ascending=False).head(3)
        print("\nTop 3 namespaces by average queue time:")
        for ns, avg in ns_stats.items():
            print(f"  {ns}: {self.format_time(avg)} ({avg:.2f}s)")
    
    def generate_namespace_7day_window(self):
        """Generate 7-day window statistics for each namespace"""
        if self.historical_data.empty:
            print("No data available for namespace statistics")
            return
        
        # Ensure timestamp is datetime
        self.historical_data['Timestamp'] = pd.to_datetime(self.historical_data['Timestamp'])
        
        # Get 7-day window
        window_start = pd.Timestamp.now() - pd.Timedelta(days=7)
        window_data = self.historical_data[self.historical_data['Timestamp'] >= window_start]
        
        if window_data.empty:
            print("No data in the 7-day window")
            return
        
        print("\n=== 7-DAY WINDOW STATISTICS BY NAMESPACE ===")
        
        # Get list of namespaces
        namespaces = window_data['Namespace'].unique()
        
        # Create a dictionary to store daily averages by namespace
        daily_stats = {}
        
        # Add collection date column
        window_data['Date'] = window_data['Timestamp'].dt.date
        
        # Process each namespace
        for namespace in namespaces:
            # Get data for this namespace
            ns_data = window_data[window_data['Namespace'] == namespace]
            
            # Calculate daily statistics
            daily_avg = ns_data.groupby('Date')['QueueTime'].mean()
            daily_max = ns_data.groupby('Date')['QueueTime'].max()
            daily_count = ns_data.groupby('Date')['QueueTime'].count()
            
            # Store in dictionary
            daily_stats[namespace] = {
                'daily_avg': daily_avg,
                'daily_max': daily_max,
                'daily_count': daily_count,
                'overall_avg': ns_data['QueueTime'].mean(),
                'overall_max': ns_data['QueueTime'].max(),
                'unique_pods': ns_data['PodUID'].nunique()
            }
        
        # Create output directory for namespace reports
        ns_report_dir = os.path.join(self.output_dir, "namespace_reports")
        os.makedirs(ns_report_dir, exist_ok=True)
        
        # Print and save statistics for each namespace
        for namespace, stats in daily_stats.items():
            print(f"\nNamespace: {namespace}")
            print(f"  7-day Average Queue Time: {self.format_time(stats['overall_avg'])} ({stats['overall_avg']:.2f}s)")
            print(f"  7-day Maximum Queue Time: {self.format_time(stats['overall_max'])} ({stats['overall_max']:.2f}s)")
            print(f"  Unique Pods in 7 days: {stats['unique_pods']}")
            
            print("  Daily Averages:")
            for date, avg in stats['daily_avg'].items():
                print(f"    {date}: {self.format_time(avg)} ({avg:.2f}s) - {stats['daily_count'][date]} samples")
            
            # Create a dataframe for this namespace's daily stats
            ns_daily_df = pd.DataFrame({
                'Date': stats['daily_avg'].index,
                'AvgQueueTime': stats['daily_avg'].values,
                'MaxQueueTime': stats['daily_max'].values,
                'SampleCount': stats['daily_count'].values
            })
            
            # Add formatted columns
            ns_daily_df['AvgQueueTime_Fmt'] = ns_daily_df['AvgQueueTime'].apply(self.format_time)
            ns_daily_df['MaxQueueTime_Fmt'] = ns_daily_df['MaxQueueTime'].apply(self.format_time)
            
            # Save to CSV
            ns_file = os.path.join(ns_report_dir, f"{namespace}_7day_stats.csv")
            ns_daily_df.to_csv(ns_file, index=False)
        
        print(f"\nDetailed namespace reports saved to: {ns_report_dir}")
    
    def run_collection(self):
        """Run a single collection cycle"""
        print(f"Starting collection at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Collect data
        new_data = self.collect_queue_times()
        
        if not new_data.empty:
            # Update storage
            self.update_persistent_storage(new_data)
            
            # Generate statistics
            self.generate_quick_stats()
        else:
            print("No data collected in this run")
        self.generate_namespace_7day_window()
        
        print(f"\nCollection complete. Next scheduled run: {(datetime.datetime.now() + datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Data stored in: {self.persistent_db_path}")
        

# Main execution
if __name__ == "__main__":
    collector = QueueTimeCollector()
    collector.run_collection()
