import urllib.request, ssl, json
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
url = 'https://afastudio.ch/reposcroller/api/v1/documents/ledger?limit=100'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        data = json.loads(r.read().decode('utf-8'))
    docs = data.get('items', [])
    print('Total docs returned:', len(docs))
    for d in docs:
        name = d.get('canonical_filename', '')
        if "'" in name or '"' in name:
            print('Doc with quote:', d.get('sha256_hash'), name)
except Exception as e:
    print('Error:', e)
