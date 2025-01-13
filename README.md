# AMD GPU Monitoring Solution for Multi-Cluster Kubernetes

## Overview
This solution provides comprehensive GPU monitoring for AMD GPUs across multiple Kubernetes clusters (OCI and bare metal) with metrics visualization in AWS-hosted Grafana. It supports namespace-level segregation for tenant-specific monitoring and utilization tracking.

## Directory Structure
```
gpu-monitoring/
├── README.md                 # Project overview and main documentation
├── LICENSE                   # Project license information
├── .gitignore               # Git ignore patterns
├── examples/                 # Example configurations and queries
│   ├── grafana-dashboards/  # Sample Grafana dashboard templates
│   │   ├── namespace-overview.json
│   │   ├── cluster-overview.json
│   │   └── alerts-dashboard.json
│   └── queries/             # Example PromQL queries
│       └── example-queries.md
├── deploy/                  # Deployment configurations
│   ├── base/               # Base Kubernetes manifests
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── rocm-exporter/  # ROCm exporter configurations
│   │   │   ├── daemonset.yaml
│   │   │   ├── service.yaml
│   │   │   ├── serviceaccount.yaml
│   │   │   ├── configmap.yaml
│   │   │   └── rbac.yaml
│   │   └── prometheus/     # Prometheus configurations
│   │       ├── prometheus-config.yaml
│   │       ├── remote-write-secret.yaml
│   │       └── recording-rules.yaml
│   ├── overlays/          # Environment-specific overlays
│   │   ├── oci/          # Oracle Cloud Infrastructure specific
│   │   │   ├── kustomization.yaml
│   │   │   └── cluster-specific-values.yaml
│   │   └── baremetal/    # Bare metal specific
│   │       ├── kustomization.yaml
│   │       └── cluster-specific-values.yaml
│   └── network/          # Network configurations
│       ├── aws-security-groups/
│       │   └── grafana-inbound.tf
│       ├── oci-security-lists/
│       │   └── prometheus-outbound.tf
│       └── vpn/
│           └── site-to-site-vpn.tf
├── scripts/             # Utility scripts
│   ├── install.sh      # Installation script
│   ├── uninstall.sh    # Uninstallation script
│   ├── update-grafana-key.sh
│   └── verify-installation.sh
├── docs/               # Documentation
│   ├── architecture.md
│   ├── installation.md
│   ├── configuration.md
│   ├── networking.md
│   ├── security.md
│   ├── troubleshooting.md
│   └── images/        # Documentation images
│       ├── architecture-diagram.png
│       └── network-flow.png
└── monitoring/        # Monitoring configurations
    ├── alerts/       # Prometheus alert rules
    │   ├── gpu-utilization.yaml
    │   └── memory-usage.yaml
    ├── dashboards/   # Grafana dashboard configurations
    │   ├── namespace-metrics.json
    │   └── cluster-overview.json
    └── recording-rules/
        └── gpu-metrics.yaml
```

## Directory Overview

### `/examples`
Contains example configurations and queries to help users get started:
- `grafana-dashboards/`: Pre-configured Grafana dashboard templates
- `queries/`: Example PromQL queries for common monitoring scenarios

### `/deploy`
Deployment configurations and manifests:
- `base/`: Base Kubernetes configurations using Kustomize
- `overlays/`: Environment-specific configurations for OCI and bare metal
- `network/`: Network configurations for different cloud providers

### `/scripts`
Utility scripts for managing the monitoring stack:
- `install.sh`: Installation script for the monitoring stack
- `uninstall.sh`: Clean removal of the monitoring stack
- `update-grafana-key.sh`: Script to update Grafana API keys
- `verify-installation.sh`: Verification of the installation

### `/docs`
Comprehensive documentation:
- Architecture details
- Installation guides
- Configuration instructions
- Network setup
- Security considerations
- Troubleshooting guides
- Visual diagrams and flowcharts

### `/monitoring`
Monitoring configurations:
- `alerts/`: Prometheus alerting rules
- `dashboards/`: Grafana dashboard configurations
- `recording-rules/`: Prometheus recording rules

## Quick Start

1. Clone the repository:
```bash
git clone <repository-url>
cd gpu-monitoring
```

2. Configure your environment:
```bash
cp deploy/overlays/oci/cluster-specific-values.yaml.example deploy/overlays/oci/cluster-specific-values.yaml
# Edit the values file with your configuration
```

3. Run the installation script:
```bash
./scripts/install.sh
```

4. Verify the installation:
```bash
./scripts/verify-installation.sh
```

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a new Pull Request

## License

This project is licensed under the [LICENSE](LICENSE) - see the LICENSE file for details.

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
