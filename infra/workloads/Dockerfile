# syntax=docker/dockerfile:1.8.1@sha256:e87caa74dcb7d46cd820352bfea12591f3dba3ddc4285e19c7dcd13359f7cefd
ARG ROCM_IMAGE
FROM ${ROCM_IMAGE}
ARG COMFY_COMMIT
ARG COMFY_ARCHIVE_SHA256
ADD --checksum=sha256:${COMFY_ARCHIVE_SHA256} https://codeload.github.com/Comfy-Org/ComfyUI/tar.gz/${COMFY_COMMIT} /tmp/comfy.tar.gz
RUN mkdir /opt/comfyui && tar -xzf /tmp/comfy.tar.gz --strip-components=1 -C /opt/comfyui && rm /tmp/comfy.tar.gz
COPY requirements.lock /opt/comfy-requirements.lock
# Do not let PyPI substitute CUDA torch for the ROCm packages supplied by AMD.
RUN python3 -m pip install --no-cache-dir --require-hashes --no-deps -r /opt/comfy-requirements.lock && \
    python3 -c "import torch; assert torch.version.hip, 'ROCm torch required'"
WORKDIR /opt/comfyui
ENV HOME=/workspace
CMD ["python3", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--disable-auto-launch", "--base-directory", "/workspace"]
