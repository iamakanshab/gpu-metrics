# AMD GPU Monitoring Solution for Multi-Cluster Kubernetes

## Overview
This solution provides comprehensive GPU monitoring for AMD GPUs across multiple Kubernetes clusters (OCI and bare metal) with metrics visualization in AWS-hosted Grafana. It supports namespace-level segregation for tenant-specific monitoring and utilization tracking.

## Directory Structure

```
k8s-gpu-metrics/
├── README.md                       # Project overview and setup instructions
├── CONTRIBUTING.md                 # Guidelines for contributing to the project
├── LICENSE                        # Project license
├── setup.py                       # Python package setup file
├── requirements.txt               # Python dependencies
│
├── deploy/                        # Kubernetes deployment manifests
│   ├── base/                      # Base Kustomize configurations
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── rbac/
│   │   │   ├── serviceaccount.yaml
│   │   │   ├── clusterrole.yaml
│   │   │   └── clusterrolebinding.yaml
│   │   ├── configmap.yaml        # Exporter script ConfigMap
│   │   ├── daemonset.yaml        # GPU metrics collector DaemonSet
│   │   └── service.yaml          # Metrics endpoint Service
│   │
│   ├── overlays/                  # Environment-specific configurations
│   │   ├── dev/
│   │   │   ├── kustomization.yaml
│   │   │   └── patch.yaml
│   │   └── prod/
│   │       ├── kustomization.yaml
│   │       └── patch.yaml
│   │
│   └── prometheus/               # Prometheus configurations
│       ├── servicemonitor.yaml
│       └── rules.yaml           # Prometheus alerting rules
│
├── src/                          # Source code
│   └── gpu_exporter/
│       ├── __init__.py
│       ├── main.py              # Main exporter script
│       ├── collector.py         # GPU metrics collection logic
│       ├── metrics.py           # Prometheus metrics definitions
│       └── utils/
│           ├── __init__.py
│           ├── gpu.py           # GPU interaction utilities
│           └── kubernetes.py    # Kubernetes client utilities
│
├── dashboards/                   # Grafana dashboards
│   ├── gpu-metrics.json         # Main GPU metrics dashboard
│   └── alerts.json              # Alerting dashboard
│
├── docs/                         # Documentation
│   ├── design.md                # System design document
│   ├── metrics.md               # Metrics documentation
│   ├── deployment.md            # Deployment guide
│   └── troubleshooting.md       # Troubleshooting guide
│
└── tests/                        # Test suite
    ├── unit/
    │   ├── __init__.py
    │   ├── test_collector.py
    │   └── test_metrics.py
    └── integration/
        ├── __init__.py
        └── test_exporter.py
```

## Directory Components Explanation

### Root Directory
- `README.md`: Project overview, quick start guide, and basic documentation
- `CONTRIBUTING.md`: Guidelines for contributing to the project
- `LICENSE`: Project license file
- `setup.py`: Python package configuration
- `requirements.txt`: Python package dependencies

### deploy/
Contains all Kubernetes deployment configurations using Kustomize for environment management.

#### base/
- Basic Kubernetes manifests that are common across all environments
- RBAC configurations for service accounts and permissions
- Core DaemonSet and Service configurations

#### overlays/
- Environment-specific configurations (dev, prod)
- Allows for different resource limits, logging levels, etc.

#### prometheus/
- Prometheus integration configurations
- Alert rules for GPU metrics

### src/
Contains the main Python application code.

#### gpu_exporter/
- `main.py`: Entry point for the exporter
- `collector.py`: GPU metrics collection implementation
- `metrics.py`: Prometheus metrics definitions
- `utils/`: Helper functions and utilities

### dashboards/
Grafana dashboard configurations in JSON format.

### docs/
Comprehensive documentation for the system.
- Design documents
- Metrics specifications
- Deployment guides
- Troubleshooting guides

### tests/
Test suite for the application.
- Unit tests for individual components
- Integration tests for the complete system

## Usage

1. Clone the repository:
```bash
git clone https://github.com/your-org/k8s-gpu-metrics.git
cd k8s-gpu-metrics
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Deploy to Kubernetes:
```bash
# For development environment
kubectl apply -k deploy/overlays/dev

# For production environment
kubectl apply -k deploy/overlays/prod
```

4. Import Grafana dashboards:
```bash
# Using grafana API or UI
kubectl port-forward svc/grafana 3000:3000 -n monitoring
# Then import dashboards/gpu-metrics.json through the Grafana UI
```
