import os
import pytest
from reposcroller.ai.analyzer import DocumentAnalyzer


def test_local_ollama_server():
    """Verify local Ollama server log file exists and DocumentAnalyzer extracts intelligence."""
    paths = [
        os.path.expandvars(r'%LOCALAPPDATA%\Ollama\server.log'),
        os.path.expandvars(r'%USERPROFILE%\.ollama\logs\server.log'),
        os.path.expandvars(r'%LOCALAPPDATA%\Programs\Ollama\server.log')
    ]
    valid_logs = [p for p in paths if os.path.exists(p) and os.path.getsize(p) > 0]
    print(f"\nFound {len(valid_logs)} valid Ollama log path(s): {valid_logs}")
    assert len(valid_logs) > 0, "No Ollama server.log file found with non-zero size."

    da = DocumentAnalyzer()
    res = da.analyze('Employment Agreement between Swisscom AG and John Doe in Zurich', 'contract_swisscom.pdf')
    print('Analysis result:', res.document_category, res.title, res.parties_involved)
    assert 'Swisscom AG' in res.parties_involved or 'Swisscom' in str(res.parties_involved)
    assert any(cat in res.document_category.lower() for cat in ['contract', 'labor', 'employment', 'legal'])
    assert len(res.title) > 0


# def test_profile_console():

#     powershell -NoProfile -Command "
# \$sampleLogs = @(
#     '[GIN] 2026/09/25 - 11:51:08 | 200 |     12.9059ms |             ::1 | POST     \"/api/chat\"',
#     '[GIN] 2026/09/25 - 11:51:10 | 200 |      1.4502ms |             ::1 | POST     \"/api/embed\"',
#     '[GIN] 2026/09/25 - 11:51:12 | 404 |     15.3203ms |             ::1 | POST     \"/api/chat\"',
#     'time=2026-09-25T11:51:14.000Z level=INFO msg=\"llama runner started\"'
# )

# foreach (\$line in \$sampleLogs) {
#     if (\$line -match '\[GIN\]\s+\S+\s+-\s+(\d{2}:\d{2}:\d{2})\s+\|\s+(\d{3})\s+\|\s+([0-9\.\w]+)\s+\|\s+\S+\s+\|\s+(\w+)\s+\"([^\"]+)\"') {
#         \$time = \$matches[1]
#         \$code = [int]\$matches[2]
#         \$lat = \$matches[3].Trim()
#         \$method = \$matches[4]
#         \$path = \$matches[5]

#         \$codeColor = if (\$code -eq 200) { 'Green' } elseif (\$code -eq 404) { 'Yellow' } else { 'Red' }
#         \$icon = if (\$path -like '*chat*') { '💬' } elseif (\$path -like '*embed*') { '🧠' } else { '⚡' }
#         \$pathColor = if (\$path -like '*chat*') { 'Cyan' } elseif (\$path -like '*embed*') { 'Magenta' } else { 'White' }

#         Write-Host \"[\$time] \" -ForegroundColor DarkGray -NoNewline
#         Write-Host \"[\$code] \" -ForegroundColor \$codeColor -NoNewline
#         Write-Host \"(\$lat) \" -ForegroundColor DarkYellow -NoNewline
#         Write-Host \"\$icon \$method \$path\" -ForegroundColor \$pathColor
#     } else {
#         Write-Host \$line -ForegroundColor Gray
#     }
# }

