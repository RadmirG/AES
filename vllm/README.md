# AES vLLM

The `vllm/` component owns cluster-native LLM serving for AES production
workloads. Local development continues to use Ollama; LangGraph can select
vLLM through the provider-neutral model client.

The first deployment is intentionally conservative:

- one vLLM replica,
- one NVIDIA GPU,
- a persistent Hugging Face/vLLM cache,
- an internal `ClusterIP` Service,
- API-key authentication,
- bounded startup, readiness, and liveness probes,
- no public Ingress.

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

## 2. Create The Local Secret Manifest

Copy the example and replace the placeholder with a long random value:

```powershell
Copy-Item vllm/k8s/secret.example.yaml vllm/k8s/secret.local.yaml
```

`secret.local.yaml` is ignored by Git. Do not commit API keys or Hugging Face
tokens.

The default bootstrap model, `Qwen/Qwen3-8B`, is public and does not require a
Hugging Face token. For gated models, create a second Secret named
`aes-huggingface` with key `HF_TOKEN`; the Deployment treats that Secret as
optional.

## 3. Deploy vLLM

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
or a PVC without a usable default StorageClass.

## 4. Port-Forward And Smoke Test

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

## Configuration

The base ConfigMap contains bootstrap values:

| Setting | Default |
| --- | --- |
| Hugging Face model | `Qwen/Qwen3-8B` |
| served model name | `aes-engineering-model` |
| maximum model length | `8192` |
| tensor parallel size | `1` |
| GPU memory utilization | `0.90` |

The Deployment requests one `nvidia.com/gpu`, 4 CPU cores, and 16 GiB memory;
it limits itself to 8 CPU cores and 32 GiB memory. Adjust these values only
after checking cluster quotas and the selected model's requirements.

Do not replace the Hugging Face model name with an Ollama tag such as
`gemma4:31b`. vLLM loads model repositories or compatible model paths, while
Ollama tags identify artifacts in Ollama's own model store.

## Current Boundary

Port forwarding is suitable for the first smoke test, not the permanent AES
production connection. The next deployment step is one of:

1. move LangGraph into the same cluster and call
   `http://aes-vllm.<namespace>.svc.cluster.local:8000/v1`, or
2. obtain an administrator-approved private Ingress/Gateway with TLS and
   authentication in front of vLLM.

Never publish the raw vLLM endpoint without authentication and network policy.

## Primary References

- [vLLM Kubernetes deployment](https://docs.vllm.ai/en/latest/deployment/k8s/)
- [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)
- [vLLM official Docker image](https://docs.vllm.ai/en/latest/deployment/docker/)
- [Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B)
