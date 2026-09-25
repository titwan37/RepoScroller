import os, glob
from reposcroller.ai.analyzer import DocumentAnalyzer

def test_local_ollama_server():
    paths = [
    os.path.expandvars(r'%LOCALAPPDATA%\Ollama\server.log'),
    os.path.expandvars(r'%USERPROFILE%\.ollama\logs\server.log'),
    os.path.expandvars(r'%LOCALAPPDATA%\Programs\Ollama\server.log')
    ]
    for p in paths:
        print(p, 'exists:', os.path.exists(p), 'size:', os.path.getsize(p) if os.path.exists(p) else 0)
        assert os.path.exists(p) and os.path.getsize(p) > 0

    da = DocumentAnalyzer()
    res = da.analyze('Employment Agreement between Swisscom AG and John Doe in Zurich', 'contract_swisscom.pdf')
    print('Analysis result:', res.document_category, res.title, res.parties_involved)
    assert res.title == 'Employment Agreement between Swisscom AG and John Doe in Zurich'
    assert res.document_category == 'Labor Contract'
    assert res.parties_involved == ['Swisscom AG', 'John Doe']
