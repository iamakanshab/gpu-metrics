class K8sGPUExporter:
    def __init__(self):
        self.logger = logging.getLogger('k8s-gpu-exporter')
        self.logger.info("Initializing namespace-aware exporter...")
        
        self.metrics = K8sGPUMetrics()
        self.current_node = os.uname().nodename
        
        # Initialize Kubernetes client with fallback options
        try:
            # Try in-cluster config first
            config.load_incluster_config()
            self.logger.info("Successfully loaded in-cluster configuration")
        except config.ConfigException:
            try:
                # Fallback to kubeconfig
                self.logger.info("Not in cluster, trying kubeconfig...")
                config.load_kube_config()
                self.logger.info("Successfully loaded kubeconfig configuration")
            except Exception as e:
                # Final fallback to explicit configuration
                self.logger.warning(f"Failed to load kubeconfig: {e}")
                self.logger.info("Falling back to explicit k8s configuration")
                
                # Get these values from environment variables or use defaults
                k8s_host = os.getenv('KUBERNETES_HOST', 'https://kubernetes.default.svc')
                k8s_token = os.getenv('KUBERNETES_TOKEN', '')
                
                if not k8s_token and os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token'):
                    with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
                        k8s_token = f.read().strip()
                
                configuration = client.Configuration()
                configuration.host = k8s_host
                configuration.api_key = {"authorization": f"Bearer {k8s_token}"}
                
                # Skip SSL verification if needed
                if os.getenv('KUBERNETES_SKIP_SSL_VERIFY', 'false').lower() == 'true':
                    configuration.verify_ssl = False
                
                client.Configuration.set_default(configuration)
                self.logger.info(f"Using explicit configuration with host: {k8s_host}")
        
        self.k8s_client = client.CoreV1Api()
        self.gpu_mapper = GPUPodMapper(self.k8s_client)
        self.logger.info(f"Exporter initialized on node: {self.current_node}")

def main():
    try:
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
        )
        logger = logging.getLogger('k8s-gpu-exporter')

        # Get configuration from environment variables
        port = int(os.environ.get('EXPORTER_PORT', 9400))
        collection_interval = int(os.environ.get('COLLECTION_INTERVAL', 300))
        
        # Additional environment variables for k8s configuration
        os.environ.setdefault('KUBERNETES_HOST', 'https://kubernetes.default.svc')
        os.environ.setdefault('KUBERNETES_SKIP_SSL_VERIFY', 'false')

        logger.info(f"Starting namespace-aware GPU exporter on port {port}")
        logger.info(f"Collection interval: {collection_interval} seconds")
        
        start_http_server(port)
        exporter = K8sGPUExporter()
        
        while True:
            try:
                exporter.collect_metrics()
                time.sleep(collection_interval)
            except Exception as e:
                logger.error(f"Error in collection loop: {e}")
                time.sleep(collection_interval)
                
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
