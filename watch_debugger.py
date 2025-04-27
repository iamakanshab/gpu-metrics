import time
import logging
import threading
from kubernetes import client, watch, config
import os

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('watch-debugger')

# Create heartbeat thread
def heartbeat_thread():
    count = 0
    while True:
        count += 1
        logger.info(f'Heartbeat #{count}: Script still running')
        time.sleep(30)  # Log every 30 seconds

# Start heartbeat in background
thread = threading.Thread(target=heartbeat_thread, daemon=True)
thread.start()

# Load local kubeconfig
try:
    # Try to load from environment variable first
    config.load_kube_config(os.getenv('KUBECONFIG'))
except:
    # Fall back to default location
    config.load_kube_config()

# Test function to simulate a watch that might get stuck
def test_watch(timeout=300):
    try:
        v1 = client.CoreV1Api()
        w = watch.Watch()
        logger.info('Starting watch stream test...')
        
        # Add timeout to demonstrate what happens when a watch times out
        for event in w.stream(v1.list_pod_for_all_namespaces, timeout_seconds=timeout):
            pod_name = event['object'].metadata.name
            logger.debug(f'Received event: {event["type"]} for {pod_name}')
            
    except Exception as e:
        logger.error(f'Watch exception: {type(e).__name__}: {e}')
    finally:
        logger.info('Watch stream ended')
        w.stop()

# Main
if __name__ == '__main__':
    logger.info("Starting watch debugger")
    
    # Test with normal timeout
    test_watch()
    
    # Allow heartbeat to continue
    while True:
        time.sleep(1)
