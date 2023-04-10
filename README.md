# k8s-node-pinger-exporter use utils fping 
Idea from [deckhouse repo](https://github.com/deckhouse/deckhouse/tree/main/modules/340-monitoring-ping)

# How use it
1. On node-exporter you should enable [--collector.textfile.directory](https://github.com/prometheus/node_exporter#textfile-collector) flag  
- example for [prometheus-operator-stack](https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/values.yaml#:~:text=prometheus%2Dnode%2Dexporter%3A)
```
prometheus-node-exporter:
  extraArgs:
  - --collector.textfile.directory=/host/textfile
  extraHostVolumeMounts:
    - name: textfile
      hostPath: /var/run/node-exporter-textfile
      mountPath: /host/textfile
      readOnly: true
```
2. Build docker image
- command for mac M1 proc
`docker build --progress=plain --platform=linux/amd64 -t <you registry tag> -f Dockerfile .`
3. Add map values for helm values.yaml
- example values.yaml
```
nodePing:
  nodes:
    cluster_targets:
      master-node-1: 100.126.10.100
      master-node-2: 100.126.10.101
      master-node-3: 100.126.10.102
      worker-node-1: 100.126.11.100
      worker-node-2: 100.126.11.101
      worker-node-3: 100.126.11.103
```
4. Helm install
```
helm upgrade --install ping-exporter k8s/helm
```