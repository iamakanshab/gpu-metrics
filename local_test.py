from kubernetes import client, watch, config
from prometheus_client import start_http_server, Histogram
import time
import logging
from urllib3.exceptions import ProtocolError
from kubernetes.client.rest import ApiException

# Configure logging
# logging.basicConfig(level=logging.INFO, 
#                     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('queue-time-exporter')

# Start Prometheus HTTP server
start_http_server(8000)

# Create metrics
pod_queue_time = Histogram('pod_queue_time_seconds', 'Time between pod creation and pod running', 
                           ['namespace', 'pod_name', 'node'])

# Configure Kubernetes client
try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

def watch_pods_with_retry(max_retries=None):
    """Watch pods with automatic reconnection on errors."""
    retry_count = 0
    backoff_time = 1  # Start with 1 second backoff
    
    while max_retries is None or retry_count < max_retries:
        try:
            v1 = client.CoreV1Api()
            w = watch.Watch()
            logger.info("Starting pod watch stream")
            
            # Set a resource_version timeout to avoid long history fetches
            # and use a timeout parameter to avoid infinite blocking
            for event in w.stream(v1.list_pod_for_all_namespaces, 
                                 timeout_seconds=300):  # 5-minute watch timeout
                process_pod_event(event)
                
                # Reset backoff on successful iteration
                backoff_time = 1
                
        except ProtocolError as e:
            retry_count += 1
            logger.warning(f"Connection reset (attempt {retry_count}): {e}")
            # Exponential backoff
            logger.info(f"Waiting {backoff_time} seconds before reconnecting...")
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, 60)  # Double the backoff, max 60 seconds
            
        except ApiException as e:
            retry_count += 1
            logger.warning(f"API error (attempt {retry_count}): {e}")
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, 60)
            
        except Exception as e:
            retry_count += 1
            logger.error(f"Unexpected error (attempt {retry_count}): {e}")
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, 60)
            
        finally:
            # Always close the watch to prevent resource leaks
            try:
                w.stop()
                logger.info("Watch stream closed")
            except:
                pass

def process_pod_event(event):
    """Process a single pod event."""
    logger.debug(f"Received {event['type']} event for pod {event['object'].metadata.namespace}/{event['object'].metadata.name}")
    if event['type'] in ['ADDED','MODIFIED']:
        pod = event['object']
        logger.debug(f"Received MODIFIED event for pod {pod.metadata.namespace}/{pod.metadata.name}")
        try:
            # Log basic pod phase info
            logger.debug(f"Pod phase: {pod.status.phase}, Start time: {pod.status.start_time}, Creation time: {pod.metadata.creation_timestamp}")
            
            # Check if pod just transitioned to running
            if pod.status.phase == 'Running' and pod.status.start_time:
                creation_time = pod.metadata.creation_timestamp
                start_time = pod.status.start_time

                # Calculate queue time
                queue_time = (start_time - creation_time).total_seconds()

                logger.debug(f"Calculated queue time: {queue_time} seconds")

                # Record the metric
                pod_queue_time.labels(
                    namespace=pod.metadata.namespace,
                    pod_name=pod.metadata.name,
                    node=pod.spec.node_name if pod.spec.node_name else "unknown"
                ).observe(queue_time)

                logger.info(f"Pod {pod.metadata.namespace}/{pod.metadata.name} queue time: {queue_time}s")
        except Exception as e:
            logger.error(f"Error processing pod {pod.metadata.namespace}/{pod.metadata.name}: {e}")

def main():
    """Main entry point with overall exception handling."""
    logger.info("Queue time exporter started")
    try:
        # Keep watching pods forever with retry mechanism
        watch_pods_with_retry()
    except Exception as e:
        logger.critical(f"Fatal error in main loop: {e}")
        # Sleep before exiting to prevent rapid restarts
        time.sleep(10)
        raise

if __name__ == '__main__':
    main()
