"""Robust document date extraction from filename prefix, content, and file modification time."""

import re
from datetime import datetime
from typing import Optional, Tuple


def extract_document_date(
    filename: Optional[str],
    text: Optional[str] = None,
    mtime: Optional[float] = None
) -> Tuple[Optional[str], str]:
    """
    Extract the substantive date of the document itself.
    
    Priority order:
    1. Filename PREFIX date (e.g. 05.08.25-..., 2024-03-15_..., 16102025-...)
    2. Date inside document text content (e.g. from document body/headers)
    3. Filename other date patterns (anywhere in filename)
    4. File OS last-modified time (mtime)
    
    Returns:
        (date_str_yyyy_mm_dd, source_type) where source_type is:
        'filename_prefix', 'content', 'filename', 'mtime', or 'unknown'
    """
    if filename:
        clean_fn = filename.strip()

        # -----------------------------------------------------------
        # 1. FILENAME PREFIX PATTERNS (Highest priority: document author's prefix)
        # -----------------------------------------------------------

        # Prefix European: DD.MM.YYYY or DD.MM.YY (e.g. 05.08.25-..., 20.10.2024_...)
        m_pref_eur = re.match(
            r'^(0[1-9]|[12]\d|3[01])[-_.](0[1-9]|1[0-2])[-_.](20\d{2}|19\d{2}|\d{2})(?:[-_\s.]|$)',
            clean_fn
        )
        if m_pref_eur:
            d, m, y = m_pref_eur.group(1), m_pref_eur.group(2), m_pref_eur.group(3)
            if len(y) == 2:
                y = ("19" if int(y) > 70 else "20") + y
            return f"{y}-{m}-{d}", "filename_prefix"

        # Prefix ISO: YYYY[-_.]MM[-_.]DD (e.g. 2024-03-15_..., 1999_05_10_...)
        m_pref_iso = re.match(
            r'^(19\d{2}|20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?:[-_\s.]|$)',
            clean_fn
        )
        if m_pref_iso:
            return f"{m_pref_iso.group(1)}-{m_pref_iso.group(2)}-{m_pref_iso.group(3)}", "filename_prefix"

        # Prefix 8-digit compact European: DDMMYYYY (e.g. 16102025-...)
        m_pref_dmy = re.match(
            r'^(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])(19\d{2}|20\d{2})(?:[-_\s.]|$)',
            clean_fn
        )
        if m_pref_dmy:
            return f"{m_pref_dmy.group(3)}-{m_pref_dmy.group(2)}-{m_pref_dmy.group(1)}", "filename_prefix"

        # Prefix 8-digit compact ISO: YYYYMMDD (e.g. 20231016_...)
        m_pref_ymd = re.match(
            r'^(19\d{2}|20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[-_\s.]|$)',
            clean_fn
        )
        if m_pref_ymd:
            return f"{m_pref_ymd.group(1)}-{m_pref_ymd.group(2)}-{m_pref_ymd.group(3)}", "filename_prefix"

        # Prefix Year only (e.g. 2002_xx_xx...)
        m_pref_yr = re.match(r'^(19\d{2}|20\d{2})[-_.]', clean_fn)
        if m_pref_yr:
            return f"{m_pref_yr.group(1)}-01-01", "filename_prefix"

    # -----------------------------------------------------------
    # 2. DATE INSIDE DOCUMENT TEXT CONTENT
    # -----------------------------------------------------------
    if text:
        sample_text = text[:4000]
        # Text ISO: YYYY-MM-DD or YYYY/MM/DD or YYYY.MM.DD
        mT1 = re.search(r'\b(19\d{2}|20\d{2})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b', sample_text)
        if mT1:
            return f"{mT1.group(1)}-{mT1.group(2)}-{mT1.group(3)}", "content"

        # Text European: DD.MM.YYYY or DD/MM/YYYY
        mT2 = re.search(r'\b(0[1-9]|[12]\d|3[01])[-/.](0[1-9]|1[0-2])[-/.](19\d{2}|20\d{2})\b', sample_text)
        if mT2:
            return f"{mT2.group(3)}-{mT2.group(2)}-{mT2.group(1)}", "content"

    # -----------------------------------------------------------
    # 3. FILENAME ANYWHERE PATTERNS (Substrings within filename)
    # -----------------------------------------------------------
    if filename:
        clean_fn = filename.strip()
        # Anywhere ISO: YYYY[-_.]MM[-_.]DD
        m_any_iso = re.search(r'(?:^|[\s_.-])(19\d{2}|20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?:[\s_.-]|$)', clean_fn)
        if m_any_iso:
            return f"{m_any_iso.group(1)}-{m_any_iso.group(2)}-{m_any_iso.group(3)}", "filename"

        # Anywhere European: DD.MM.YYYY or DD.MM.YY
        m_any_eur = re.search(r'(?:^|[\s_.-])(0[1-9]|[12]\d|3[01])[-_.](0[1-9]|1[0-2])[-_.](20\d{2}|19\d{2}|\d{2})(?:[\s_.-]|$)', clean_fn)
        if m_any_eur:
            d, m, y = m_any_eur.group(1), m_any_eur.group(2), m_any_eur.group(3)
            if len(y) == 2:
                y = ("19" if int(y) > 70 else "20") + y
            return f"{y}-{m}-{d}", "filename"

        # Anywhere 8-digit compact
        m_any_ymd = re.search(r'(?:^|[\s_.-])(19\d{2}|20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', clean_fn)
        if m_any_ymd:
            return f"{m_any_ymd.group(1)}-{m_any_ymd.group(2)}-{m_any_ymd.group(3)}", "filename"

    # -----------------------------------------------------------
    # 4. FILE LAST MODIFIED TIME (mtime from OS / filesystem)
    # -----------------------------------------------------------
    if mtime and mtime > 0:
        try:
            return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d"), "mtime"
        except (ValueError, OSError):
            pass

    return None, "unknown"
