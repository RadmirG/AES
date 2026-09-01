# AES vLLM

The `vllm/` component owns cluster-native LLM serving for AES production
workloads. Local development continues to use Ollama; LangGraph can select
vLLM through the provider-neutral model client.

The first deployment is intentionally conservative:

- one vLLM replica,
- one A100-class NVIDIA GPU,
- the official Gemma 4 31B instruction-tuned W4A16 checkpoint,
- a persistent Hugging Face/vLLM cache,
- an internal `ClusterIP` Service,
- API-key authentication,
- bounded startup, readiness, and liveness probes,
- normal workload priority,
- an explicit idle-GPU-cleaner exemption for the persistent model service,
- no public Ingress in the base.

The official `vllm/vllm-openai` image serves an OpenAI-compatible API. AES uses
`/v1/chat/completions`; browser clients never call vLLM directly.

## Layout

```text
vllm/
  architecture.md
  README.md
  k8s/
    base/
      configmap.yaml
      deployment.yaml
      kustomization.yaml
      persistent-volume-claim.yaml
      service-account.yaml
      service.yaml
    ingress.example.yaml
    secret.example.yaml
```

## 1. Inspect The Cluster

Run these commands before applying the manifests:

```powershell
kubectl get nodes `
    -o custom-columns="NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory"

kubectl get storageclass
kubectl get resourcequota,limitrange --namespace=$namespace
```

If node listing is forbidden, ask the cluster administrator for the GPU model,
GPU resource name, available VRAM, required node labels/tolerations, default
StorageClass, and namespace quota.

## 2. Model And Resource Decision

AES serves `google/gemma-4-31B-it-qat-w4a16-ct`. This is Google's official
instruction-tuned quantization-aware checkpoint for vLLM/SGLang servers. It
keeps the Gemma 4 31B model class while fitting responsibly on one 40 GiB A100.

The full BF16 checkpoint needs approximately 69.9 GB for model loading before
KV cache and runtime overhead. It therefore does not fit safely on one 40 GiB
GPU and would require a later two-GPU tensor-parallel overlay. The W4A16/Q4
class is approximately 17.5 GB before KV cache and runtime overhead. AES starts
with an 8192-token model length and one GPU, then measures quality, throughput,
and VRAM before considering a larger context or BF16 deployment.

The base selects GPU capability with `gpu: a100`; it never pins a worker host
name. It requests one `nvidia.com/gpu`, 4 CPU cores, 32 GiB memory, and 4 GiB
ephemeral storage, with bounded limits. Model and compile caches live on the
PVC rather than the container root filesystem.

## 3. Create The Local Secret Manifest

Copy the example and replace the placeholder with a long random value:

```powershell
Copy-Item vllm/k8s/secret.example.yaml vllm/k8s/secret.local.yaml
```

`secret.local.yaml` is ignored by Git. Do not commit API keys or Hugging Face
tokens. Confirm that the account used for model download can access the model
repository. If a Hugging Face token is needed, create a second Secret named
`aes-huggingface` with key `HF_TOKEN`; the Deployment treats it as optional.

## 4. Deploy vLLM

Apply the local secret and the Kustomize base to the assigned namespace:

```powershell
kubectl apply `
    --namespace=$namespace `
    -f vllm/k8s/secret.local.yaml

kubectl apply `
    --namespace=$namespace `
    -k vllm/k8s/base
```

Watch startup. The first run downloads the model into the PVC and can take
several minutes:

```powershell
kubectl get pods,services,pvc `
    --namespace=$namespace `
    --watch
```

In another terminal:

```powershell
kubectl logs `
    --namespace=$namespace `
    deployment/aes-vllm `
    --follow
```

If the Pod remains `Pending`, inspect scheduling events:

```powershell
kubectl describe pod `
    --namespace=$namespace `
    -l app.kubernetes.io/name=aes-vllm
```

Typical causes are unavailable `nvidia.com/gpu`, insufficient namespace quota,
no schedulable node with label `gpu: a100`, a missing GPU toleration, or a PVC
without a usable default StorageClass.

Verify that the persistent service has the cluster idle-GPU exemption on both
the Deployment and its Pod template:

```powershell
kubectl get deployment aes-vllm `
    --namespace=$namespace `
    -o jsonpath='{.metadata.labels.gpu-cleaner}{"`n"}{.spec.template.metadata.labels.gpu-cleaner}{"`n"}'
```

Both lines must report `allow-gpu-idle`. Without that label, a cluster GPU
cleaner may remove the idle Pod and its owning Deployment after the configured
idle period. The PVC protects model-cache data, but it cannot recreate a
Deployment that the controller deleted.

## 5. Port-Forward And Smoke Test

Only after the Service and ready Pod exist, start the local tunnel:

```powershell
kubectl port-forward `
    --namespace=$namespace `
    service/aes-vllm `
    8000:8000
```

In another PowerShell window, load the same API key from the ignored local
Secret file or assign it explicitly to `$apiKey`, then test model discovery:

```powershell
$apiKey = "replace-with-the-value-from-secret.local.yaml"

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/v1/models" `
    -Headers @{ Authorization = "Bearer $apiKey" }
```

Test chat completion:

```powershell
$body = @{
    model = "aes-engineering-model"
    messages = @(
        @{
            role = "user"
            content = "Return only the word ready."
        }
    )
    max_tokens = 16
    temperature = 0
} | ConvertTo-Json -Depth 6

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/v1/chat/completions" `
    -Headers @{
        Authorization = "Bearer $apiKey"
        "Content-Type" = "application/json"
    } `
    -Body $body
```

Port forwarding is a developer test path only. It makes the Service reachable
from the machine running `kubectl`; it does not automatically make it reachable
from a separate Docker server running LangGraph.

## 6. Optional VPN-Restricted Ingress

The base intentionally contains only a `ClusterIP` Service. When an assigned
VPN-restricted hostname is available, copy the non-applied template:

```powershell
Copy-Item vllm/k8s/ingress.example.yaml vllm/k8s/ingress.local.yaml
```

Replace `replace-with-assigned-vpn-host.example.invalid` with the assigned
private hostname, review the cluster's active Ingress class and restrictions,
then apply it:

```powershell
kubectl apply `
    --namespace=$namespace `
    -f vllm/k8s/ingress.local.yaml
```

`ingress.local.yaml` is ignored by Git because hostnames and cluster-specific
annotations can be sensitive. The Ingress remains protected by the vLLM Bearer
API key. A VPN on the developer laptop is insufficient for server-to-cluster
traffic unless the machine or container running LangGraph also has a valid
route and DNS resolution to that private hostname.

## Configuration

The base ConfigMap contains bootstrap values:

| Setting | Default |
| --- | --- |
| Hugging Face model | `google/gemma-4-31B-it-qat-w4a16-ct` |
| served model name | `aes-engineering-model` |
| maximum model length | `8192` |
| tensor parallel size | `1` |
| GPU memory utilization | `0.90` |

The Deployment uses normal priority, one A100 selected by capability label, a
GPU-node toleration, 32/64 GiB requested/limited memory, 4/8 CPU cores, and
4/16 GiB ephemeral storage. The model cache requests 100 GiB persistent
storage. Confirm namespace `ResourceQuota`, `LimitRange`, and PVC binding before
assuming node-level capacity is available to the namespace.

Do not replace the Hugging Face model name with an Ollama tag such as
`gemma4:31b`. vLLM loads model repositories or compatible model paths, while
Ollama tags identify artifacts in Ollama's own model store.

## Current Boundary

Port forwarding is suitable for the first smoke test, not the permanent AES
production connection. The next deployment step is one of:

1. move LangGraph into the same cluster and call
   `http://aes-vllm.<namespace>.svc.cluster.local:8000/v1`, or
2. use the administrator-approved VPN-restricted Ingress from a LangGraph host
   that can route to and resolve it.

Never publish the raw vLLM endpoint to the Internet. Keep the API key enabled,
and add a cluster-specific NetworkPolicy once the Ingress controller namespace
labels and LangGraph placement are known.

## Primary References

- [vLLM Kubernetes deployment](https://docs.vllm.ai/en/latest/deployment/k8s/)
- [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)
- [vLLM official Docker image](https://docs.vllm.ai/en/latest/deployment/docker/)
- [vLLM supported models](https://docs.vllm.ai/en/stable/models/supported_models/)
- [Gemma 4 model overview and memory requirements](https://ai.google.dev/gemma/docs/core)
- [Gemma 4 31B instruction-tuned W4A16 checkpoint](https://huggingface.co/google/gemma-4-31B-it-qat-w4a16-ct)
