import sqlite3; 

def check_lease_contracts():
    conn = sqlite3.connect('backend/data/reposcroller_ledger.db'); 
    cur = conn.cursor(); 
    cur.execute('SELECT doc_type, count(*) FROM document_ledger WHERE text_snippet LIKE ? GROUP BY doc_type;', ('%[LEASE_CONTRACT]%',)); 
    lis = cur.fetchall()
    print(lis)
    conn.close()

def check_documents_by_storage_root():
    conn = sqlite3.connect('backend/data/reposcroller_ledger.db'); 
    cur = conn.cursor(); 
    cur.execute('''
        SELECT fl.storage_root, count(*) 
        FROM document_ledger dl 
        JOIN file_locations fl ON dl.sha256_hash = fl.sha256_hash 
        WHERE dl.doc_type = 'lease_contract' 
        GROUP BY fl.storage_root;'''); 
    print(cur.fetchall())
    conn.close()

check_lease_contracts()
check_documents_by_storage_root()
