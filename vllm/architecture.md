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
        service["aes-vllm ClusterIP Service"] --> pod["vLLM OpenAI server"]
        pod --> gpu["NVIDIA GPU"]
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
    pod --> gpu["nvidia.com/gpu: 1"]
    service["ClusterIP Service<br/>port 8000"] --> pod
    langgraph["LangGraph"] -->|"Bearer token + OpenAI API"| service
```

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
    Ready --> Terminating: rollout or deletion
    Terminating --> [*]
```

The startup probe allows a long first model download/load interval. Readiness
keeps traffic away until the engine responds. A `Recreate` deployment strategy
prevents two large model Pods from competing for a single GPU and a
ReadWriteOnce cache during rollout.

## Configuration Ownership

| Concern | Owner |
| --- | --- |
| model repository and served alias | `vllm/k8s/base/configmap.yaml` |
| vLLM image and process arguments | `vllm/k8s/base/deployment.yaml` |
| GPU/CPU/memory requests | Deployment resources |
| model and compile cache | `aes-vllm-cache` PVC |
| inference API key | ignored/local Kubernetes Secret |
| optional gated-model token | `aes-huggingface` Secret |
| model request/response parsing | LangGraph model-provider client |
| public user API | LangGraph `aes-agent`, never raw vLLM |

## Security Boundary

- The Service is `ClusterIP`; no public Ingress is created.
- vLLM requires a Bearer API key.
- The Pod does not receive a Kubernetes service-account token.
- The container runs as a non-root UID with privilege escalation disabled.
- Secrets are not stored in tracked manifests.
- Users and browsers call LangGraph, not vLLM.
- A later permanent route must add administrator-approved TLS, authentication,
  and NetworkPolicy controls.

## Scaling Direction

```mermaid
flowchart TD
    A["Measure one-GPU deployment"] --> B{"Model fits and latency is acceptable?"}
    B -->|yes| C["Keep tensor parallel size 1"]
    B -->|no, model fits across GPUs on one node| D["Add multi-GPU overlay<br/>tensor parallel size = GPU count"]
    B -->|no, multiple nodes required| E["Design distributed vLLM deployment"]
    E --> F["Validate NCCL and high-speed interconnect"]
    F --> G["Choose Ray/LWS/KubeRay or production-stack"]
```

Multi-GPU and multi-node manifests are intentionally deferred until the cluster
GPU topology, node labels, quotas, interconnect, and supported controller are
known. Guessing those values would create manifests that schedule incorrectly
or perform poorly.
