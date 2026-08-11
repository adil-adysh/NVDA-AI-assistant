from huggingface_hub import hf_hub_download
from safetensors import safe_open
path = hf_hub_download('microsoft/harrier-oss-v1-270m', 'model.safetensors')
print('Path:', path)
with safe_open(path, framework='pt') as sf:
    keys = list(sf.keys())
    print('Keys:', len(keys))
    print('First 5:', keys[:5])
    has_prefix = any(k.startswith('model.') for k in keys)
    print('Has model. prefix:', has_prefix)
