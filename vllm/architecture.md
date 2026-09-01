# vLLM Architecture

The `vllm/` component is the AES production model-serving boundary for a
Kubernetes cluster. It is separate from LangGraph orchestration and from local
Ollama development.

## Component Position

```mermaid
flowchart LR
    subgraph LOCAL["Local Development"]
        ollama["Ollama"]
    end

    subgraph CLUSTER["Kubernetes Compute Plane"]
        ingress["Optional VPN-restricted Ingress"] --> service
        service["aes-vllm ClusterIP Service"] --> pod["vLLM OpenAI server"]
        pod --> gpu["One A100 GPU"]
        pod --> cache[("Persistent model and compile cache")]
    end

    subgraph AES["AES Control Plane"]
        client["Model-provider client"] --> workflow["LangGraph nodes"]
    end

    ollama --> client
    service --> client
```

Only one backend is selected for a LangGraph process. Ollama remains the
default for the Docker Compose development stack. vLLM is selected for cluster
production through environment configuration.

## Kubernetes Topology

```mermaid
flowchart TD
    secret["aes-vllm-secrets<br/>VLLM_API_KEY"] --> deployment["Deployment aes-vllm"]
    hfsecret["optional aes-huggingface<br/>HF_TOKEN"] --> deployment
    config["ConfigMap<br/>model and engine settings"] --> deployment
    pvc[("PVC aes-vllm-cache")] --> deployment
    account["ServiceAccount<br/>no API token mounted"] --> deployment
    deployment --> pod["vLLM Pod"]
    cleaner["GPU idle cleaner"] -->|"exempt by label"| deployment
    scheduler["Scheduler<br/>gpu=a100, normal priority"] --> pod
    pod --> gpu["nvidia.com/gpu: 1<br/>A100 capability"]
    service["ClusterIP Service<br/>port 8000"] --> pod
    langgraph["LangGraph"] -->|"Bearer token + OpenAI API"| service
    ingress["Optional VPN Ingress<br/>local manifest"] --> service
```

The Ingress path is optional and deliberately excluded from the Kustomize
base. Its hostname and cluster annotations belong in ignored
`vllm/k8s/ingress.local.yaml`. Same-cluster LangGraph uses Service DNS instead.

## Model And Resource Contract

```mermaid
flowchart TD
    request["Gemma 4 31B for AES reasoning and code"] --> memory{"Precision choice"}
    memory -->|"BF16: about 69.9 GB weights"| multi["Later two-A100 benchmark<br/>plus KV/runtime headroom"]
    memory -->|"Official W4A16: about 17.5 GB weights"| baseline["Current one-A100 baseline"]
    baseline --> context["8192-token context"]
    baseline --> pvc[("100 GiB model cache PVC")]
    baseline --> limits["4-8 CPU<br/>32-64 GiB RAM<br/>4-16 GiB ephemeral storage"]
```

The base serves `google/gemma-4-31B-it-qat-w4a16-ct` under the stable alias
`aes-engineering-model`. The official W4A16 checkpoint is preferred over BF16
for the first shared-cluster deployment because it fits one 40 GiB A100 with
room for KV cache and runtime overhead. The model context remains intentionally
below its architectural maximum until VRAM and latency are measured.

Node-level hardware capacity does not imply namespace quota. Deployment is
still conditional on one allocatable `nvidia.com/gpu`, CPU/memory quota, and a
bound PVC. The scheduler selects `gpu: a100`, never a physical worker name.

## Request Sequence

```mermaid
sequenceDiagram
    participant G as LangGraph
    participant S as aes-vllm Service
    participant V as vLLM Pod
    participant GPU as NVIDIA GPU
    participant PVC as Model Cache PVC

    G->>S: POST /v1/chat/completions
    Note over G,S: Bearer API key, served model aes-engineering-model
    S->>V: Route to ready Pod
    V->>PVC: Read cached model/tokenizer/compile data
    V->>GPU: Batched inference
    GPU-->>V: Generated tokens
    V-->>G: OpenAI-compatible completion
```

## Deployment Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Pending
    Pending --> Downloading: Pod scheduled and cache empty
    Downloading --> Loading: model files available
    Loading --> Ready: startup probe succeeds
    Ready --> NotReady: readiness probe fails
    NotReady --> Ready: engine recovers
    Ready --> Idle: no inference traffic
    Idle --> Ready: new inference request
    Idle --> Protected: gpu-cleaner=allow-gpu-idle
    Protected --> Ready: service remains deployed
    Ready --> Terminating: rollout or deletion
    Terminating --> [*]
```

The startup probe allows a long first model download/load interval. Readiness
keeps traffic away until the engine responds. A `Recreate` deployment strategy
prevents two large model Pods from competing for a single GPU and a
ReadWriteOnce cache during rollout. The idle exemption is required because an
always-on inference server can legitimately hold its GPU while waiting for AES
requests; if the cluster cleaner removes both Pod and Deployment, Kubernetes
has no remaining controller that can recreate the service. Model data survives
in the PVC, but availability does not.

## Configuration Ownership

| Concern | Owner |
| --- | --- |
| model repository and served alias | `vllm/k8s/base/configmap.yaml` |
| vLLM image and process arguments | `vllm/k8s/base/deployment.yaml` |
| GPU/CPU/memory requests | Deployment resources |
| GPU capability and toleration | Deployment Pod scheduling policy |
| workload priority | cluster `normal` PriorityClass |
| idle-GPU lifecycle exemption | `gpu-cleaner: allow-gpu-idle` labels |
| model and compile cache | `aes-vllm-cache` PVC |
| inference API key | ignored/local Kubernetes Secret |
| optional gated-model token | `aes-huggingface` Secret |
| VPN hostname and Ingress annotations | ignored `ingress.local.yaml` |
| model request/response parsing | LangGraph model-provider client |
| public user API | LangGraph `aes-agent`, never raw vLLM |

## Security Boundary

- The base Service is `ClusterIP`; no public Ingress is created.
- The optional Ingress is private/VPN-restricted and remains outside the base.
- vLLM requires a Bearer API key.
- The Pod does not receive a Kubernetes service-account token.
- The container runs as a non-root UID with privilege escalation disabled.
- Secrets are not stored in tracked manifests.
- Users and browsers call LangGraph, not vLLM.
- A cluster-specific NetworkPolicy remains pending until the Ingress controller
  namespace labels and LangGraph placement are known.

## Scaling Direction

```mermaid
flowchart TD
    A["Measure one-GPU deployment"] --> B{"Model fits and latency is acceptable?"}
    B -->|yes| C["Keep tensor parallel size 1"]
    B -->|quality needs BF16| D["Add two-A100 BF16 overlay<br/>tensor parallel size 2"]
    B -->|no, quantized model does not fit| D
    B -->|no, multiple nodes required| E["Design distributed vLLM deployment"]
    E --> F["Validate NCCL and high-speed interconnect"]
    F --> G["Choose Ray/LWS/KubeRay or production-stack"]
```

The known A100 capability makes a later same-node two-GPU experiment plausible,
but namespace quota and observed W4A16 quality must justify it first.
InfiniBand is unnecessary for the current single-GPU Pod. Multi-node manifests
remain deferred until quota, topology, NCCL/RDMA resources, and the supported
distributed controller are verified.
