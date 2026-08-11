import torch
from transformers import AutoTokenizer, AutoModel
import embedding_engine

tokenizer = AutoTokenizer.from_pretrained('microsoft/harrier-oss-v1-270m')

text = 'hello'

# Python tokenization
enc = tokenizer(text, return_tensors='pt', add_special_tokens=True)
ids = enc['input_ids'][0].tolist()
tokens = tokenizer.convert_ids_to_tokens(ids)
print(f'Python: ids={ids}, tokens={tokens}')

# Get the embedding weight from the PyTorch model
model = AutoModel.from_pretrained('microsoft/harrier-oss-v1-270m', torch_dtype=torch.float32)
model.eval()
embed_weight = model.get_input_embeddings().weight  # (262144, 640)
print(f'Embed weight shape: {embed_weight.shape}')

# Get the PyTorch embedding for the first input
emb = embed_weight[ids]  # (3, 640)
print(f'PyTorch embeddings shape: {emb.shape}')

# Scale by sqrt(hidden_size) as Gemma3 does
emb_scaled = emb * (640 ** 0.5)
print(f'PyTorch scaled embeddings norm: {emb_scaled.norm(dim=-1).tolist()}')
print(f'PyTorch embeddings[0][:5]: {emb[0,:5].tolist()}')
print(f'PyTorch scaled embeddings[0][:5]: {emb_scaled[0,:5].tolist()}')
print()

# Now compute the first decoder layer output manually
layer0 = model.layers[0]
attn = layer0.self_attn

# Get Q/K/V projections
q_proj_weight = attn.q_proj.weight  # (1024, 640)
k_proj_weight = attn.k_proj.weight  # (256, 640)
v_proj_weight = attn.v_proj.weight  # (256, 640)
o_proj_weight = attn.o_proj.weight  # (640, 1024)
q_norm_weight = attn.q_norm.weight  # (256,)
k_norm_weight = attn.k_norm.weight  # (256,)

print(f'q_proj: {q_proj_weight.shape}')
print(f'k_proj: {k_proj_weight.shape}')
print(f'v_proj: {v_proj_weight.shape}')
print(f'o_proj: {o_proj_weight.shape}')
print(f'q_norm: {q_norm_weight.shape}')
print(f'k_norm: {k_norm_weight.shape}')

# Print first few values of q_proj weight
print(f'q_proj[0,:5]: {q_proj_weight[0,:5].tolist()}')
print(f'q_norm[:5]: {q_norm_weight[:5].tolist()}')
