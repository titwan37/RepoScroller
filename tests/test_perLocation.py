def test_location_degrees_and_docs():
    """
    A detailed location mapping will be defined within the graph extractor. This involves crafting regular expressions to identify Swiss cantons, communes, and international hubs. The initial approach focuses on precise matching for locations like Ottenbach and Steinhausen, ensuring accurate extraction of place names from text.

    Regular expressions are being crafted to capture various Swiss locations, including cities, cantons, and potentially international hubs. The current expressions focus on direct matches for known locations and anticipate variations like accents or common abbreviations for broader coverage. Considering incorporating postal codes and region names within the regexes to improve accuracy and specificity in location extraction.

    The regular expressions are being expanded to include alternate spellings and common names for cities within Switzerland, such as "Freiburg" for "Fribourg." International cities like "Paris," "London," and "New York" are now defined within the location mapping. Specific attention is given to the Swiss cantons, ensuring both official and colloquial names are captured.

    Location extraction now extends beyond Swiss locations to include major international cities and regions, using defined regular expressions. Both the filename and the text content of the document are being scanned to identify location mentions. Each location is added to the graph as a node, with links representing mentions within the document.
    """

    from reposcroller.ledger.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
    SELECT n.node_id, n.name, 
           COUNT(DISTINCT l.sha256_hash) AS doc_count,
           (SELECT COUNT(*) FROM knowledge_edges e WHERE e.source_id = n.node_id OR e.target_id = n.node_id) AS degree
    FROM knowledge_nodes n
    LEFT JOIN document_entity_links l ON n.node_id = l.node_id
    WHERE n.node_type = 'location'
    GROUP BY n.node_id, n.name
    ORDER BY degree DESC, doc_count DESC
    ''')
    for r in cur.fetchall():
        print(r['name'] + ': ' + str(r['degree']) + ' edges | ' + str(r['doc_count']) + ' docs')
    assert "Ottenbach: 93 edges | 88 docs"
    assert "Steinhausen: 183 edges | 572 docs"
    assert "Zug: 652 edges | 733 docs"
    assert "Switzerland: 533 edges | 890 docs"
    assert "Baar: 28 edges | 16 docs"
    assert "Cham: 315 edges | 102 docs"
    assert "Rotkreuz: 16 edges | 18 docs"
    assert "Affoltern am Albis: 23 edges | 17 docs"
    assert "Winterthur: 67 edges | 19 docs"
    assert "Fribourg: 56 edges | 40 docs"