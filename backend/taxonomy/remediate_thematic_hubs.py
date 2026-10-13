"""Remediates thematic hubs, removes hallucinated nodes, and binds documents to Level 0 Macro Themes."""

import sqlite3
from pathlib import Path
from backend.config import settings
from backend.ai.taxonomy import DEFAULT_TAXONOMY

def remediate():
    db_path = Path(settings.DB_PATH)
    print(f"Target Database: {db_path}")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("BEGIN TRANSACTION;")

    try:
        # --- 1. Update global_taxonomy hierarchy ---
        print("\n1. Updating global_taxonomy category parent_ids...")
        for item in DEFAULT_TAXONOMY:
            cur.execute("""
                UPDATE global_taxonomy
                SET parent_id = ?
                WHERE category_id = ?;
            """, (item["parent_id"], item["category_id"]))

        # --- 2. Purge hallucinated / orphaned categories from global_taxonomy ---
        print("2. Purging hallucinated categories from global_taxonomy...")
        hallucinated_cats = [
            "hard-real-time-systems",
            "software-engineering",
            "IT-Operations",
            "household-violence"
        ]
        cur.executemany("DELETE FROM global_taxonomy WHERE category_id = ?;", [(c,) for c in hallucinated_cats])

        # --- 3. Re-link minor ad-hoc themes (security, procedural-intelligence, household-violence) ---
        print("3. Re-linking minor ad-hoc themes to macro themes...")
        cur.execute("""
            UPDATE document_ledger
            SET doc_type = 'court_order'
            WHERE doc_type = 'household-violence';
        """)
        cur.execute("""
            UPDATE document_entity_links
            SET node_id = 'theme_technical_architecture'
            WHERE node_id IN ('theme_security', 'theme_repo_scroller_procedural_intelligence');
        """)
        cur.execute("""
            UPDATE document_entity_links
            SET node_id = 'theme_legal_justice'
            WHERE node_id = 'theme_household_violence';
        """)
        cur.execute("DELETE FROM global_taxonomy WHERE category_id IN ('security', 'repo-scroller-procedural-intelligence', 'household-violence');")

        # --- 4. Remap document_entity_links to the 11 Macro Solar Hubs ---
        print("4. Remapping document_entity_links to the 11 Macro Themes...")
        # A. Career research -> theme_career_employment
        cur.execute("UPDATE document_entity_links SET node_id = 'theme_career_employment' WHERE node_id = 'theme_career_research';")

        # B. Financial banking -> theme_banking_finance
        cur.execute("UPDATE document_entity_links SET node_id = 'theme_banking_finance' WHERE node_id = 'theme_financial_banking';")

        # C. Invoices & tax -> theme_taxation_accounting
        cur.execute("UPDATE document_entity_links SET node_id = 'theme_taxation_accounting' WHERE node_id IN ('theme_financial_invoice', 'theme_tax_assessment');")

        # D. Insurance -> theme_insurance_social_security
        cur.execute("UPDATE document_entity_links SET node_id = 'theme_insurance_social_security' WHERE node_id = 'theme_insurance_policy';")

        # E. Public administration -> theme_public_administration
        cur.execute("UPDATE document_entity_links SET node_id = 'theme_public_administration' WHERE node_id = 'theme_administrative_order';")

        # F. Corporate governance -> theme_corporate_business
        cur.execute("UPDATE document_entity_links SET node_id = 'theme_corporate_business' WHERE node_id = 'theme_corporate_governance';")

        # G. Education & qualifications -> theme_education_training
        cur.execute("UPDATE document_entity_links SET node_id = 'theme_education_training' WHERE node_id IN ('theme_identity_credentials', 'theme_technical_reference');")

        # H. Legal & Justice (court order, formal correspondence, statute legislation)
        cur.execute("UPDATE document_entity_links SET node_id = 'theme_legal_justice' WHERE node_id IN ('theme_court_order', 'theme_formal_correspondence', 'theme_statute_legislation');")

        # I. Legal contracts: separate lease contracts -> theme_real_estate_housing, rest -> theme_legal_justice
        # Identify lease_contract hashes
        cur.execute("SELECT sha256_hash FROM document_ledger WHERE doc_type = 'lease_contract';")
        lease_hashes = [r[0] for r in cur.fetchall()]
        if lease_hashes:
            cur.executemany("""
                UPDATE document_entity_links
                SET node_id = 'theme_real_estate_housing'
                WHERE node_id = 'theme_legal_contract' AND sha256_hash = ?;
            """, [(h,) for h in lease_hashes])

        # Remaining legal contracts -> theme_legal_justice
        cur.execute("UPDATE document_entity_links SET node_id = 'theme_legal_justice' WHERE node_id = 'theme_legal_contract';")

        # --- 5. Update knowledge_edges target_ids to the 11 Macro Themes ---
        print("5. Remapping knowledge_edges CATEGORIZED_AS targets...")
        edge_remaps = [
            ('theme_financial_banking', 'theme_banking_finance'),
            ('theme_financial_invoice', 'theme_taxation_accounting'),
            ('theme_tax_assessment', 'theme_taxation_accounting'),
            ('theme_career_research', 'theme_career_employment'),
            ('theme_legal_contract', 'theme_legal_justice'),
            ('theme_formal_correspondence', 'theme_legal_justice'),
            ('theme_identity_credentials', 'theme_education_training'),
            ('theme_security', 'theme_technical_architecture'),
            ('theme_repo_scroller_procedural_intelligence', 'theme_technical_architecture'),
            ('theme_household_violence', 'theme_legal_justice'),
            ('theme_theme_career_employment', 'theme_career_employment'),
            ('theme_theme_legal_justice', 'theme_legal_justice'),
            ('theme_theme_education_training', 'theme_education_training'),
            ('theme_theme_taxation_accounting', 'theme_taxation_accounting'),
        ]
        for old_t, new_t in edge_remaps:
            cur.execute("UPDATE document_entity_links SET node_id = ? WHERE node_id = ?;", (new_t, old_t))
            cur.execute("""
                UPDATE OR IGNORE knowledge_edges
                SET target_id = ?
                WHERE target_id = ?;
            """, (new_t, old_t))
            cur.execute("DELETE FROM knowledge_edges WHERE target_id = ?;", (old_t,))

        # Delete edges targeting orphaned / hallucinated themes
        cur.execute("""
            DELETE FROM knowledge_edges
            WHERE target_id IN ('theme_hard_real_time_systems', 'theme_software_engineering', 'theme_household_violence')
               OR source_id IN ('document_category_hard_real_time_systems', 'document_category_software_engineering', 'theme_household_violence');
        """)

        # --- 6. Purge redundant and hallucinated nodes from knowledge_nodes ---
        print("6. Purging redundant category-level and hallucinated theme nodes from knowledge_nodes...")
        legacy_theme_nodes = [
            'theme_financial_banking',
            'theme_career_research',
            'theme_legal_contract',
            'theme_court_order',
            'theme_formal_correspondence',
            'theme_financial_invoice',
            'theme_tax_assessment',
            'theme_insurance_policy',
            'theme_administrative_order',
            'theme_corporate_governance',
            'theme_identity_credentials',
            'theme_technical_reference',
            'theme_statute_legislation',
            'theme_security',
            'theme_repo_scroller_procedural_intelligence',
            'theme_hard_real_time_systems',
            'theme_software_engineering',
            'theme_household_violence',
            'theme_theme_career_employment',
            'theme_theme_legal_justice',
            'theme_theme_education_training',
            'theme_theme_taxation_accounting',
            'document_category_hard_real_time_systems',
            'document_category_software_engineering'
        ]
        cur.executemany("DELETE FROM knowledge_nodes WHERE node_id = ?;", [(n,) for n in legacy_theme_nodes])

        # Commit all changes
        conn.commit()
        print("Remediation successfully committed!\n")

    except Exception as e:
        conn.rollback()
        print(f"Error during remediation! Rolled back. Details: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    remediate()
