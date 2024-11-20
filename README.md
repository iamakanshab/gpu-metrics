# GPU Monitoring Stack with Grafana
Kubernetes-based monitoring solution for AMD GPUs using Grafana, Prometheus, and ROCm metrics.

## Prerequisites

- Kubernetes cluster
- kubectl CLI tool
- AMD GPUs with ROCm drivers
- ROCm SMI tools installed on GPU nodes

## AMD-specific metrics:

- GPU utilization
- Memory usage
- Temperature
- Power consumption

## Architecture
```
GPU Nodes → ROCm Exporter → Prometheus → Grafana
```

## Quick Start

1. Create namespace:
```bash
kubectl create namespace metrics
```

2. Deploy ROCm SMI Exporter:
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: rocm-smi-exporter
  namespace: metrics
spec:
  selector:
    matchLabels:
      app: rocm-smi-exporter
  template:
    metadata:
      labels:
        app: rocm-smi-exporter
    spec:
      containers:
      - name: rocm-smi-exporter
        image: ubuntu:20.04
        command:
        - bash
        - -c
        args:
        - |
          apt-get update && \
          DEBIAN_FRONTEND=noninteractive apt-get install -y curl && \
          curl -fsSL https://repo.radeon.com/rocm/rocm.gpg.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/rocm.gpg && \
          echo 'deb [arch=amd64] https://repo.radeon.com/rocm/apt/5.4.3 ubuntu main' | tee /etc/apt/sources.list.d/rocm.list && \
          apt-get update && \
          DEBIAN_FRONTEND=noninteractive apt-get install -y rocm-smi && \
          while true; do
            for gpu in $(rocm-smi --listnodes 2>/dev/null || echo ""); do
              echo "# HELP amd_gpu_utilization GPU Utilization percentage"
              utilization=$(rocm-smi -d $gpu --showuse | grep "GPU use" | awk '{print $4}')
              echo "amd_gpu_utilization{gpu=\"$gpu\"} ${utilization:-0}"
              
              echo "# HELP amd_gpu_memory_used_mb GPU Memory Used in MB"
              memory=$(rocm-smi -d $gpu --showmemuse | grep "GPU memory use" | awk '{print $5}')
              echo "amd_gpu_memory_used_mb{gpu=\"$gpu\"} ${memory:-0}"
              
              echo "# HELP amd_gpu_temperature_celsius GPU Temperature"
              temp=$(rocm-smi -d $gpu --showtemp | grep "Temperature" | awk '{print $2}')
              echo "amd_gpu_temperature_celsius{gpu=\"$gpu\"} ${temp:-0}"
            done
            sleep 15
          done
        securityContext:
          privileged: true
        volumeMounts:
        - name: dev
          mountPath: /dev
        - name: sys
          mountPath: /sys
      volumes:
      - name: dev
        hostPath:
          path: /dev
      - name: sys
        hostPath:
          path: /sys
EOF
```

3. Deploy Grafana with GPU dashboard:
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboards
  namespace: metrics
data:
  gpu-dashboard.json: |
    {
      "title": "GPU Metrics Dashboard",
      "panels": [
        {
          "title": "GPU Utilization",
          "targets": [
            {
              "expr": "amd_gpu_utilization",
              "legendFormat": "GPU {{gpu}}"
            }
          ],
          "type": "timeseries"
        },
        {
          "title": "Memory Usage",
          "targets": [
            {
              "expr": "amd_gpu_memory_used_mb",
              "legendFormat": "GPU {{gpu}}"
            }
          ],
          "type": "timeseries"
        },
        {
          "title": "Temperature",
          "targets": [
            {
              "expr": "amd_gpu_temperature_celsius",
              "legendFormat": "GPU {{gpu}}"
            }
          ],
          "type": "timeseries"
        }
      ]
    }
EOF
```

## Available Metrics

### GPU Core Metrics
- `amd_gpu_utilization`: GPU utilization percentage
- `amd_gpu_memory_used_mb`: Memory usage in MB
- `amd_gpu_temperature_celsius`: GPU temperature

### ROCm-smi Commands
```bash
# List GPUs
rocm-smi --listnodes

# Show GPU usage
rocm-smi --showuse

# Show memory usage
rocm-smi --showmemuse

# Show temperature
rocm-smi --showtemp
```

## Dashboard Configuration

### Default GPU Dashboard
- Utilization panel with 80% threshold alert
- Memory usage trend
- Temperature monitoring
- Auto-refresh every 5s

### Custom Queries
```promql
# GPU Utilization Rate
rate(amd_gpu_utilization[5m])

# Memory Usage Change
delta(amd_gpu_memory_used_mb[1h])

# High Temperature Alert
amd_gpu_temperature_celsius > 80
```

## Troubleshooting

### ROCm Exporter Issues
```bash
# Check ROCm-smi installation
kubectl exec -it -n metrics <pod-name> -- rocm-smi --version

# Verify GPU detection
kubectl exec -it -n metrics <pod-name> -- rocm-smi --listnodes

# Check metrics output
kubectl logs -n metrics -l app=rocm-smi-exporter
```

### Common Problems

1. No GPU metrics:
```bash
# Verify ROCm driver installation
kubectl exec -it -n metrics <pod-name> -- ls -l /dev/kfd /dev/dri

# Check ROCm-smi access
kubectl exec -it -n metrics <pod-name> -- rocm-smi
```

2. Permission issues:
```bash
# Check pod security context
kubectl get pod <pod-name> -n metrics -o yaml | grep -A 5 securityContext
```

## Resource Requirements

ROCm Exporter:
```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 200m
    memory: 256Mi
```

## Security

1. ROCm-smi requires privileged access
2. Secure metrics endpoint
3. Implement RBAC
4. Use secrets for credentials

## Cleanup
```bash
kubectl delete namespace metrics
```
