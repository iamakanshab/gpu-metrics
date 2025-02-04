We have replaced existing ROCm Exporters with AMD Device Metrics Exporter running as a DaemonSet on all Kubernetes clusters (both OCI and bare metal)
Each exporter pod consists of:
- Main container running rocm/device-metrics-exporter for GPU metrics collection
- Sidecar container handling metric pushing to maintain existing push-based architecture
Data flow remains unchanged:
GPU Node → Device Metrics Exporter → Prometheus Pushgateway → TimescaleDB → Grafana
- Deployment is standardized across all cluster types using Kubernetes,
- Node selection for AMD GPU hosts and necessary device mounts (/dev/dri, /dev/kfd) for GPU access.
