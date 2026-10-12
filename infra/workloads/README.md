# Optional AMD jobs on machine 2

The primary stack stays in LocalAI. These profiles reserve the R9700 for interactive image work or training without making them always-on infrastructure.

* ComfyUI source is pinned to v0.39.0's exact Git commit with an archive checksum. Its Python dependencies are locked with hashes. PyTorch/torchvision/torchaudio/triton remain supplied by the pinned AMD ROCm image; PyPI must not replace them with CUDA builds.
* `gpu-probe` imports ROCm torch and runs a real GPU matrix multiplication. Passing container configuration is insufficient to prove host compatibility.
* `training` is an offline one-off Python workspace on the same pinned AMD runtime. It mounts datasets/models read-only and outputs writable. It does not install an unchosen trainer, download a model, or promise a fine-tuning recipe works on RDNA4. Select a framework/model and lock its dependencies before adding a real tracked `train.py`.

```bash
python3 infra/workloads/jobs.py --state-dir /srv/nexus/workloads init --platform-project nexus-platform
python3 infra/workloads/jobs.py --state-dir /srv/nexus/workloads validate
# Stop the machine-2 LocalAI worker and verify no other process is using the GPU first.
python3 infra/workloads/jobs.py --state-dir /srv/nexus/workloads probe --gpu-reserved
python3 infra/workloads/jobs.py --state-dir /srv/nexus/workloads build
python3 infra/workloads/jobs.py --state-dir /srv/nexus/workloads image-up --gpu-reserved
python3 infra/workloads/jobs.py --state-dir /srv/nexus/workloads image-down
```

Use `https://images.lab.home.arpa` after the platform is running and the power user belongs to `homelab-admins`. ComfyUI has no direct published port; Caddy handles authentication and WebSockets on the shared AI network. If the image profile is stopped, its route is unavailable. This browser endpoint is not an unauthenticated LocalAI backend; API automation must use an authorized IdP flow or a separate explicitly protected machine endpoint.

Put diffusion checkpoints in `comfyui/models`, workflows/settings in `comfyui/user`, and images in `comfyui/output`. The package disables automatic launch but does not install ComfyUI Manager or arbitrary custom nodes; add required nodes through reviewed, versioned builds. Starting a profile doesn't coordinate VRAM with LocalAI. `--gpu-reserved` is an operator assertion, not a scheduler or GPU lock. Restart the LocalAI worker after releasing image/training jobs.

The AMD base image is large. Budget disk for image layers, build cache and diffusion weights before downloading on a 1 TB NVMe. Build once, record the resulting image ID and archive/mirror it when needed. Source digest and Python hashes pin inputs, while Docker build tooling and package registries must remain available to rebuild. Host GPU/driver tests and the ComfyUI build still require acceptance on machine 2.

To update the Python lock intentionally, fetch requirements from the pinned source commit, remove the direct torch/torchvision/torchaudio entries supplied by AMD, then run:

```bash
uv pip compile infra/workloads/requirements.in --excludes infra/workloads/rocm-provided.txt --python-version 3.12 --python-platform x86_64-manylinux_2_39 --generate-hashes --only-binary :all: --no-header --no-annotate --output-file infra/workloads/requirements.lock
```

Inspect the lock for replacement torch/triton or `nvidia-*` packages before building. Validate host support against the selected [AMD compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/native_linux/native_linux_compatibility.html) and [official container tags](https://hub.docker.com/r/rocm/pytorch/). [ComfyUI upstream](https://github.com/Comfy-Org/ComfyUI) supplies the application; this repository supplies the deployment wrapper.
