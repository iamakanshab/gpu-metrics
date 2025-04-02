#!/usr/bin/env python3
import pandas as pd
import os
import argparse
from datetime import datetime

def deduplicate_queue_data(input_file, output_file=None):
    """
    Deduplicate queue time data by keeping only the first occurrence of each unique pod.
    
    Args:
        input_file (str): Path to the input CSV file with queue time data
        output_file (str, optional): Path to save the deduplicated data. If None, will use input filename with '_deduped' suffix
    """
    print(f"Starting deduplication of file: {input_file}")
    
    # Default output file
    if output_file is None:
        base_name, ext = os.path.splitext(input_file)
        output_file = f"{base_name}_deduped{ext}"
    
    # Load the data
    try:
        df = pd.read_csv(input_file)
        original_row_count = len(df)
        print(f"Loaded {original_row_count} records from {input_file}")
    except Exception as e:
        print(f"Error loading data: {str(e)}")
        return
    
    # Check if PodUID column exists
    if 'PodUID' not in df.columns:
        print("Error: PodUID column not found in the data")
        return
    
    # Create backup of original file
    backup_file = f"{input_file}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        df.to_csv(backup_file, index=False)
        print(f"Created backup of original data at: {backup_file}")
    except Exception as e:
        print(f"Warning: Could not create backup: {str(e)}")
    
    # Perform deduplication
    # Keep only the first occurrence of each PodUID
    deduplicated = df.drop_duplicates(subset=['PodUID'], keep='first')
    
    # Calculate statistics
    dedup_count = len(deduplicated)
    duplicate_count = original_row_count - dedup_count
    duplicate_percent = (duplicate_count / original_row_count) * 100 if original_row_count > 0 else 0
    
    print(f"Found {duplicate_count} duplicate records ({duplicate_percent:.2f}%)")
    print(f"Reduced from {original_row_count} to {dedup_count} records")
    
    # Save deduplicated data
    try:
        deduplicated.to_csv(output_file, index=False)
        print(f"Saved deduplicated data to: {output_file}")
        
        # Create list of processed pod UIDs
        processed_pods_file = os.path.join(os.path.dirname(output_file), "processed_pods.txt")
        with open(processed_pods_file, 'w') as f:
            for pod_uid in deduplicated['PodUID'].unique():
                f.write(f"{pod_uid}\n")
        print(f"Saved {len(deduplicated['PodUID'].unique())} processed pod UIDs to: {processed_pods_file}")
        
        return True
    except Exception as e:
        print(f"Error saving deduplicated data: {str(e)}")
        return False

def analyze_queue_time_distributions(input_file):
    """
    Analyze the distribution of queue times in the data, before and after deduplication.
    
    Args:
        input_file (str): Path to the input CSV file with queue time data
    """
    print(f"\nAnalyzing queue time distributions for: {input_file}")
    
    try:
        df = pd.read_csv(input_file)
    except Exception as e:
        print(f"Error loading data for analysis: {str(e)}")
        return
    
    # Check if we have the right columns
    if 'QueueTime' not in df.columns or 'PodUID' not in df.columns:
        print("Error: Required columns (QueueTime, PodUID) not found")
        return
    
    # Original distribution
    print("\nOriginal Queue Time Distribution:")
    print(f"Count: {len(df)}")
    print(f"Mean: {df['QueueTime'].mean():.2f}s")
    print(f"Median: {df['QueueTime'].median():.2f}s")
    print(f"Min: {df['QueueTime'].min():.2f}s")
    print(f"Max: {df['QueueTime'].max():.2f}s")
    
    # Calculate percentiles
    percentiles = [25, 50, 75, 90, 95, 99]
    for p in percentiles:
        val = df['QueueTime'].quantile(p/100)
        print(f"{p}th percentile: {val:.2f}s")
    
    # Deduplicated distribution
    dedup_df = df.drop_duplicates(subset=['PodUID'], keep='first')
    
    print("\nDeduplicated Queue Time Distribution:")
    print(f"Count: {len(dedup_df)}")
    print(f"Mean: {dedup_df['QueueTime'].mean():.2f}s")
    print(f"Median: {dedup_df['QueueTime'].median():.2f}s")
    print(f"Min: {dedup_df['QueueTime'].min():.2f}s")
    print(f"Max: {dedup_df['QueueTime'].max():.2f}s")
    
    # Calculate percentiles for deduplicated data
    for p in percentiles:
        val = dedup_df['QueueTime'].quantile(p/100)
        print(f"{p}th percentile: {val:.2f}s")
    
    # Namespace analysis
    print("\nTop 5 Namespaces by Average Queue Time:")
    
    # Original
    orig_ns = df.groupby('Namespace')['QueueTime'].agg(['mean', 'count']).sort_values('mean', ascending=False).head(5)
    print("\nOriginal Data:")
    for i, (ns, row) in enumerate(orig_ns.iterrows(), 1):
        print(f"{i}. {ns}: {row['mean']:.2f}s (n={row['count']})")
    
    # Deduplicated
    dedup_ns = dedup_df.groupby('Namespace')['QueueTime'].agg(['mean', 'count']).sort_values('mean', ascending=False).head(5)
    print("\nDeduplicated Data:")
    for i, (ns, row) in enumerate(dedup_ns.iterrows(), 1):
        print(f"{i}. {ns}: {row['mean']:.2f}s (n={row['count']})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Deduplicate Kubernetes pod queue time data')
    parser.add_argument('input_file', help='Path to the input CSV file with queue time data')
    parser.add_argument('--output', '-o', help='Path to save the deduplicated data')
    parser.add_argument('--analyze', '-a', action='store_true', help='Perform detailed analysis of queue time distributions')
    
    args = parser.parse_args()
    
    # Run deduplication
    success = deduplicate_queue_data(args.input_file, args.output)
    
    # Perform analysis if requested
    if success and args.analyze:
        analyze_queue_time_distributions(args.input_file)
        
        # Also analyze the deduplicated file
        output_file = args.output if args.output else f"{os.path.splitext(args.input_file)[0]}_deduped{os.path.splitext(args.input_file)[1]}"
        analyze_queue_time_distributions(output_file)
