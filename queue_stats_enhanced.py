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
    def __init__(self, duration_mins=5, interval_secs=60, output_dir=None, exclude_namespaces=None, kubeconfig=None):
        """
        Initialize the collector
        
        Args:
            duration_mins: Collection duration in minutes (default: 5)
            interval_secs: Interval between collections in seconds (default: 60)
            output_dir: Directory to store results (default: auto-generated)
            exclude_namespaces: List of namespaces to exclude (default: ['kube-system'])
            kubeconfig: Path to kubeconfig file (default: None, will use hardcoded path)
        """
        self.duration_mins = duration_mins
        self.interval_secs = interval_secs
        self.exclude_namespaces = exclude_namespaces or ['kube-system']
        
        # Hardcode the kubeconfig path to /root/.kube/config
        self.kubeconfig = "/root/.kube/config"
        
        # Verify kubeconfig exists
        if not os.path.exists(self.kubeconfig):
            print(f"WARNING: Kubeconfig file not found at {self.kubeconfig}")
        else:
            print(f"Using hardcoded kubeconfig: {self.kubeconfig}")
        
        # Create timestamp for output directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or f"queue_stats_{timestamp}"
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize DataFrame to store all collected data
        self.all_data = pd.DataFrame(columns=['Timestamp', 'Namespace', 'Pod', 'QueueTime', 'QueueTimeFormatted', 
                                             'Days', 'Hours', 'Minutes', 'Seconds'])
        
        print(f"Starting queue time statistics collection for {duration_mins} minutes.")
        print(f"Excluding namespaces: {', '.join(self.exclude_namespaces)}")
        print(f"Data will be saved to {self.output_dir}/")

    def format_time_components(self, seconds):
        """Convert seconds to days, hours, minutes, seconds format"""
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        return {
            'Days': int(days),
            'Hours': int(hours),
            'Minutes': int(minutes),
            'Seconds': round(seconds, 2),
            'Formatted': f"{int(days)}d {int(hours)}h {int(minutes)}m {round(seconds, 2)}s"
        }
    
    def collect_queue_times(self):
        """Run kubectl command and collect queue times for all namespaces (except excluded ones)"""
        try:
            # Build kubectl command with properly expanded kubeconfig path
            kubectl_cmd = ["kubectl", f"--kubeconfig={self.kubeconfig}", "get", "pods", "--all-namespaces", "-o", "json"]
            
            # Print the command for debugging
            print(f"DEBUG: Running command: {' '.join(kubectl_cmd)}")
            
            # Run kubectl command
            result = subprocess.run(
                kubectl_cmd,
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
                    
                    # Format queue time into components
                    time_components = self.format_time_components(queue_time)
                    
                    queue_times.append({
                        'Timestamp': timestamp,
                        'Namespace': namespace,
                        'Pod': pod_name,
                        'QueueTime': queue_time,
                        'QueueTimeFormatted': time_components['Formatted'],
                        'Days': time_components['Days'],
                        'Hours': time_components['Hours'],
                        'Minutes': time_components['Minutes'],
                        'Seconds': time_components['Seconds'],
                        'CreationTime': pod['metadata']['creationTimestamp'],
                        'StartTime': pod['status']['startTime']
                    })
            
            return pd.DataFrame(queue_times)
            
        except subprocess.CalledProcessError as e:
            print(f"Error running kubectl command: {e}")
            print(f"Command output: {e.stderr}")
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
                
                # Format times for display
                avg_formatted = self.format_time_components(avg_queue)['Formatted']
                max_formatted = self.format_time_components(max_queue)['Formatted']
                
                print(f"  Average queue time: {avg_formatted} ({avg_queue:.2f} seconds)")
                print(f"  Maximum queue time: {max_formatted} ({max_queue:.2f} seconds) in {max_ns}/{max_pod}")
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
        
        # Save raw data to CSV and Excel
        self.all_data.to_csv(os.path.join(self.output_dir, "all_queue_times.csv"), index=False)
        self.all_data.to_excel(os.path.join(self.output_dir, "all_queue_times.xlsx"), index=False, engine='openpyxl')
        
        # Calculate overall statistics
        print("\n=== OVERALL QUEUE TIME STATISTICS ===")
        total_pods = len(self.all_data['Pod'].unique())
        total_namespaces = len(self.all_data['Namespace'].unique())
        overall_avg = self.all_data['QueueTime'].mean()
        overall_max = self.all_data['QueueTime'].max()
        max_ns = self.all_data.loc[self.all_data['QueueTime'].idxmax(), 'Namespace'] if not self.all_data.empty else "N/A"
        max_pod = self.all_data.loc[self.all_data['QueueTime'].idxmax(), 'Pod'] if not self.all_data.empty else "N/A"
        
        # Format times for display
        avg_formatted = self.format_time_components(overall_avg)['Formatted']
        max_formatted = self.format_time_components(overall_max)['Formatted']
        
        print(f"Total unique pods: {total_pods}")
        print(f"Total namespaces: {total_namespaces}")
        print(f"Overall average queue time: {avg_formatted} ({overall_avg:.2f} seconds)")
        print(f"Overall maximum queue time: {max_formatted} ({overall_max:.2f} seconds) in {max_ns}/{max_pod}")
        
        # Calculate namespace-level statistics
        print("\n=== QUEUE TIME STATISTICS BY NAMESPACE ===")
        
        # Create a function to calculate formatted times for agg operations
        def format_time(seconds):
            return self.format_time_components(seconds)['Formatted']
        
        # Group by namespace and calculate stats
        ns_stats = self.all_data.groupby('Namespace').agg(
            PodCount=('Pod', 'nunique'),
            AvgQueueTime=('QueueTime', 'mean'),
            MaxQueueTime=('QueueTime', 'max'),
            MinQueueTime=('QueueTime', 'min'),
            StdQueueTime=('QueueTime', 'std')
        ).reset_index()
        
        # Add formatted time columns
        ns_stats['AvgQueueTimeFormatted'] = ns_stats['AvgQueueTime'].apply(format_time)
        ns_stats['MaxQueueTimeFormatted'] = ns_stats['MaxQueueTime'].apply(format_time)
        ns_stats['MinQueueTimeFormatted'] = ns_stats['MinQueueTime'].apply(format_time)
        
        # Create component columns for Excel
        for stat in ['AvgQueueTime', 'MaxQueueTime', 'MinQueueTime']:
            ns_stats[f'{stat}Days'] = ns_stats[stat].apply(lambda x: self.format_time_components(x)['Days'])
            ns_stats[f'{stat}Hours'] = ns_stats[stat].apply(lambda x: self.format_time_components(x)['Hours'])
            ns_stats[f'{stat}Minutes'] = ns_stats[stat].apply(lambda x: self.format_time_components(x)['Minutes'])
            ns_stats[f'{stat}Seconds'] = ns_stats[stat].apply(lambda x: self.format_time_components(x)['Seconds'])
        
        # Sort by average queue time (descending)
        ns_stats = ns_stats.sort_values('AvgQueueTime', ascending=False)
        
        # Create a formatted DataFrame for display
        display_cols = ['Namespace', 'PodCount', 'AvgQueueTimeFormatted', 'MaxQueueTimeFormatted', 'MinQueueTimeFormatted']
        print(ns_stats[display_cols].to_string(index=False))
        
        # Save namespace statistics
        ns_stats.to_csv(os.path.join(self.output_dir, "namespace_stats.csv"), index=False)
        ns_stats.to_excel(os.path.join(self.output_dir, "namespace_stats.xlsx"), index=False, engine='openpyxl')
        
        # Identify top pods with longest queue times
        print("\n=== TOP 10 PODS WITH LONGEST QUEUE TIMES ===")
        top_pods = self.all_data.sort_values('QueueTime', ascending=False).drop_duplicates(['Namespace', 'Pod']).head(10)
        
        # Display with formatted time
        top_pods_display = top_pods[['Namespace', 'Pod', 'QueueTimeFormatted', 'CreationTime', 'StartTime']].copy()
        print(top_pods_display.to_string(index=False))
        
        # Save top pods data
        top_pods.to_csv(os.path.join(self.output_dir, "top_pods.csv"), index=False)
        top_pods.to_excel(os.path.join(self.output_dir, "top_pods.xlsx"), index=False, engine='openpyxl')
    
    def generate_summary_report(self):
        """
        Generate a standalone summary Excel report based on the final printed statistics
        """
        # File path for the Excel report
        summary_file = os.path.join(self.output_dir, "queue_time_summary.xlsx")
        
        # Create a Pandas Excel writer using openpyxl as the engine
        with pd.ExcelWriter(summary_file, engine='openpyxl') as writer:
            # 1. Overall Statistics
            # Get the calculated values from instance variables
            total_pods = len(self.all_data['Pod'].unique())
            total_namespaces = len(self.all_data['Namespace'].unique())
            overall_avg = self.all_data['QueueTime'].mean()
            overall_max = self.all_data['QueueTime'].max()
            max_ns = self.all_data.loc[self.all_data['QueueTime'].idxmax(), 'Namespace'] if not self.all_data.empty else "N/A"
            max_pod = self.all_data.loc[self.all_data['QueueTime'].idxmax(), 'Pod'] if not self.all_data.empty else "N/A"
            
            # Format times for display
            avg_formatted = self.format_time_components(overall_avg)['Formatted']
            max_formatted = self.format_time_components(overall_max)['Formatted']
            
            overall_stats = pd.DataFrame([
                ["=== OVERALL QUEUE TIME STATISTICS ===", ""],
                ["Total unique pods", total_pods],
                ["Total namespaces", total_namespaces],
                ["Overall average queue time", f"{avg_formatted} ({overall_avg:.2f} seconds)"],
                ["Overall maximum queue time", f"{max_formatted} ({overall_max:.2f} seconds) in {max_ns}/{max_pod}"],
            ])
            overall_stats.to_excel(writer, sheet_name='Overall Statistics', index=False, header=False)
            
            # Auto-adjust column width for the overall stats sheet
            worksheet = writer.sheets['Overall Statistics']
            for idx, col in enumerate(overall_stats.columns):
                max_len = max(overall_stats[col].astype(str).map(len).max(), len(str(col)))
                worksheet.column_dimensions[chr(65 + idx)].width = max_len + 5
            
            # 2. Namespace Statistics
            # Get namespace stats from the grouped data
            ns_stats = self.all_data.groupby('Namespace').agg(
                PodCount=('Pod', 'nunique'),
                AvgQueueTime=('QueueTime', 'mean'),
                MaxQueueTime=('QueueTime', 'max'),
                MinQueueTime=('QueueTime', 'min')
            ).reset_index()
            
            # Add formatted time columns
            ns_stats['AvgQueueTimeFormatted'] = ns_stats['AvgQueueTime'].apply(
                lambda x: self.format_time_components(x)['Formatted'])
            ns_stats['MaxQueueTimeFormatted'] = ns_stats['MaxQueueTime'].apply(
                lambda x: self.format_time_components(x)['Formatted'])
            ns_stats['MinQueueTimeFormatted'] = ns_stats['MinQueueTime'].apply(
                lambda x: self.format_time_components(x)['Formatted'])
            
            # Sort by average queue time (descending)
            ns_stats = ns_stats.sort_values('AvgQueueTime', ascending=False)
            
            # Prepare the data for Excel - use only the formatted columns for display
            ns_display = ns_stats[['Namespace', 'PodCount', 'AvgQueueTimeFormatted', 
                                'MaxQueueTimeFormatted', 'MinQueueTimeFormatted']].copy()
            
            # Rename the columns to match the display format
            ns_display.columns = ['Namespace', 'PodCount', 'AvgQueueTime', 'MaxQueueTime', 'MinQueueTime']
            
            # Add a header row with the section title
            header_df = pd.DataFrame([["=== QUEUE TIME STATISTICS BY NAMESPACE ==="]], columns=["Namespace"])
            # Concatenate the header with the data
            empty_cols = {col: [""] for col in ns_display.columns[1:]}
            header_df = pd.concat([header_df, pd.DataFrame(empty_cols)], axis=1)
            ns_display = pd.concat([header_df, ns_display], ignore_index=True)
            
            ns_display.to_excel(writer, sheet_name='Namespace Statistics', index=False)
            
            # Auto-adjust column width for namespace stats
            worksheet = writer.sheets['Namespace Statistics']
            for idx, col in enumerate(ns_display.columns):
                max_len = max(ns_display[col].astype(str).map(len).max(), len(str(col)))
                worksheet.column_dimensions[chr(65 + idx)].width = max_len + 2
            
            # 3. Top 10 Pods
            # Get the top 10 pods with longest queue times
            top_pods = self.all_data.sort_values('QueueTime', ascending=False).drop_duplicates(['Namespace', 'Pod']).head(10)
            
            # Create display dataframe
            top_pods_display = top_pods[['Namespace', 'Pod', 'QueueTimeFormatted', 'CreationTime', 'StartTime']].copy()
            top_pods_display.columns = ['Namespace', 'Pod', 'MaxQueueTime', 'CreationTime', 'StartTime']
            
            # Add a header row with the section title
            header_df = pd.DataFrame([["=== TOP 10 PODS WITH LONGEST QUEUE TIMES ==="]], columns=["Namespace"])
            # Concatenate the header with the data
            empty_cols = {col: [""] for col in top_pods_display.columns[1:]}
            header_df = pd.concat([header_df, pd.DataFrame(empty_cols)], axis=1)
            top_pods_display = pd.concat([header_df, top_pods_display], ignore_index=True)
            
            top_pods_display.to_excel(writer, sheet_name='Top 10 Pods', index=False)
            
            # Auto-adjust column width for top pods
            worksheet = writer.sheets['Top 10 Pods']
            for idx, col in enumerate(top_pods_display.columns):
                max_len = max(top_pods_display[col].astype(str).map(len).max(), len(str(col)))
                worksheet.column_dimensions[chr(65 + idx)].width = max_len + 2
        
        print(f"\nSummary report generated: {summary_file}")
        return summary_file

    def run(self):
        """Run the entire collection and analysis process"""
        self.run_collection()
        self.generate_statistics()
        # Generate the summary report
        self.generate_summary_report()
        print("\nCollection and analysis complete!")
        print(f"Excel files are available in: {self.output_dir}/")


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
    
    # Explicitly unset KUBECONFIG environment variable to ensure our hardcoded path is used
    if 'KUBECONFIG' in os.environ:
        print(f"Unsetting KUBECONFIG environment variable to ensure hardcoded path is used")
        del os.environ['KUBECONFIG']
    
    # Create and run collector
    collector = QueueTimeStatsCollector(duration_mins=duration, interval_secs=interval)
    collector.run()
