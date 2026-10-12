"""Run inside the pinned AMD container; fail if a real GPU tensor operation fails."""
import json
import torch

assert torch.version.hip, 'Container does not contain ROCm torch'
assert torch.cuda.is_available(), 'GPU unavailable; inspect host amdgpu, /dev/kfd and group permissions'
device = torch.cuda.get_device_properties(0)
x = torch.ones((128, 128), device='cuda')
y = x @ x
torch.cuda.synchronize()
assert torch.all(y == 128).item(), 'GPU matrix multiplication produced unexpected results'
print(json.dumps({'torch': torch.__version__, 'hip': torch.version.hip, 'gpu': device.name,
                  'memory_bytes': device.total_memory, 'matrix_test': 'passed'}, indent=2))
