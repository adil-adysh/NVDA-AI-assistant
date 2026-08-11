import embedding_engine
import sys
print('Python executable:', sys.executable, file=sys.stderr)
e = embedding_engine.EmbeddingEngine('harrier-oss-v1-270m')
v = e.embed('hello world')
print('ok', len(v))
