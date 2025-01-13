# AMD GPU Monitoring Solution for Multi-Cluster Kubernetes

## Overview
This solution provides comprehensive GPU monitoring for AMD GPUs across multiple Kubernetes clusters (OCI and bare metal) with metrics visualization in AWS-hosted Grafana. It supports namespace-level segregation for tenant-specific monitoring and utilization tracking.

## Architecture
```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ OCI Cluster  │    │ OCI Cluster  │    │ Bare Metal   │
│ ROCm Exporter│    │ ROCm Exporter│    │ ROCm Exporter│
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                    │
       │                   │                    │
┌──────┼───────────────────┼────────────────────┼───────┐
│      │                   │                    │       │
│   ┌──┴───────────────────┴────────────────────┴──┐   │
│   │           Prometheus Remote Write            │   │
│   └──────────────────────┬─────────────────────┬─┘   │
│                          │                     │      │
│                          │                     │      │
└──────────────────────────┼─────────────────────┼──────┘
                           │                     │
                     ┌─────┴─────────────────────┴────┐
                     │     AWS-hosted Grafana         │
                     └────────────────────────────────┘
```

## Prerequisites
- Kubernetes clusters (OCI or bare metal) with AMD GPUs
- ROCm driver installed on GPU nodes
- Prometheus Operator installed
- Existing Grafana instance in AWS
- Network connectivity between clusters and AWS
- `kubectl` and `envsubst` installed locally

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/iamakanshab/gpu-monitoring.git
cd gpu-monitoring
```

### 2. Configure Environment Variables
Create an environment file for each cluster:
```bash
cat > cluster-env.sh << EOF
export CLUSTER_NAME="cluster-name"
export ENVIRONMENT="production"
export GRAFANA_USER="your-grafana-user"
export GRAFANA_API_KEY="your-api-key"
export BASE64_GRAFANA_USER=$(echo -n $GRAFANA_USER | base64)
export BASE64_GRAFANA_API_KEY=$(echo -n $GRAFANA_API_KEY | base64)
EOF
```

### 3. Deploy Monitoring Stack
```bash
# Source environment variables
source cluster-env.sh

# Apply configurations
kubectl create namespace monitoring
envsubst < prometheus-values.yaml | kubectl apply -f -
kubectl apply -f rocm-exporter.yaml
```

### 4. Verify Installation
```bash
# Check if pods are running
kubectl get pods -n monitoring

# Verify metrics collection
kubectl port-forward svc/rocm-exporter 9400:9400 -n monitoring
curl localhost:9400/metrics
```

## Configuration

### Namespace Configuration
Update the `rocm-exporter-config` ConfigMap to include your namespaces:
```yaml
data:
  config.yaml: |
    namespaces:
      - namespace1
      - namespace2
      - namespace3
```

### Network Configuration
1. **AWS VPC Configuration**
   - Configure security groups to allow inbound traffic from cluster IPs
   - Set up VPC peering or VPN if required

2. **OCI Network Setup**
   - Configure security lists to allow egress to AWS Grafana
   - Set up FastConnect or VPN if required

3. **Bare Metal Configuration**
   - Configure firewall rules for Grafana connectivity
   - Set up appropriate routing for AWS access

## Metrics and Alerts

### Available Metrics
- `GPU_UTILIZATION`: GPU utilization percentage
- `GPU_MEMORY_USED`: Used GPU memory in bytes
- `GPU_MEMORY_TOTAL`: Total GPU memory in bytes
- `GPU_POWER_USAGE`: Power usage in watts

### Example PromQL Queries
```promql
# Namespace GPU Utilization
avg(GPU_UTILIZATION) by (namespace, cluster)

# Memory Usage per Namespace
sum(GPU_MEMORY_USED) by (namespace, cluster) / sum(GPU_MEMORY_TOTAL) by (namespace, cluster) * 100

# Power Usage Trends
rate(GPU_POWER_USAGE[5m])
```

### Default Alerts
- High GPU Utilization (>90% for 10m)
- High Memory Usage (>90% for 10m)

## Troubleshooting

### Common Issues
1. **Metrics Not Showing in Grafana**
   - Verify remote write configuration
   - Check network connectivity
   - Validate Grafana API credentials

2. **ROCm Exporter Issues**
   - Verify ROCm driver installation
   - Check pod logs for errors
   - Validate node selector configuration

3. **Network Connectivity**
   - Verify security group configurations
   - Check VPC/VPN connectivity
   - Validate firewall rules

### Debugging Commands
```bash
# Check ROCm exporter logs
kubectl logs -l app=rocm-exporter -n monitoring

# Verify Prometheus remote write
kubectl logs -l app=prometheus -n monitoring | grep "remote write"

# Test network connectivity
kubectl run nettest --rm -it --image=busybox -- ping grafana.aws.example.com
```

## Security Considerations
- Use TLS for all metric transport
- Implement network policies
- Regularly rotate Grafana API keys
- Use least privilege RBAC configurations
- Secure sensitive configuration data in Secrets

## Support and Maintenance
- For issues, please create a ticket in the repository
- Regular updates recommended for security patches
- Monitor Prometheus remote write performance
- Keep ROCm drivers and exporter up to date

## License
[Add your license information here]
