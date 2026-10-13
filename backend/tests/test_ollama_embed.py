
# curl.exe -s http://localhost:11434/api/tags | Select-String -Pattern "models"
# curl.exe -s http://localhost:11434/api/tags | Select-String -Pattern "models" | python -m json.tool


from backend.ai.embeddings import EmbeddingAdapter
adapter = EmbeddingAdapter()

v = adapter.embed_text('Testing RepoScroller EmbeddingAdapter resilience on localhost')
print('Success! Vector length:', len(v), 'Dimension:', len(v), 'Sample:', v[:3])

res = adapter.embed_batch(['First chunk test', 'Second chunk test'])
print('Batch success! Chunks count:', len(res), 'Dimensions:', [len(v) for v in res])