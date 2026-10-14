curl.exe -s -X POST http://127.0.0.1:11434/api/embed -H "Content-Type: application/json" -d "{\"model\": \"snowflake-arctic-embed2:latest\", \"input\": \"Hello world test\"}"
Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/embed" -Method Post -Body (@{model = "snowflake-arctic-embed2:latest"; input = "Hello world test" } | ConvertTo-Json) -ContentType "application/json" | Select-Object model, @{Name = "Dims"; Expression = { $_.embeddings[0].Count } }

Get-Process *llama*, *ollama* -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, CPU

Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 Id, ProcessName, @{Name = "WorkingSet_MB"; Expression = { [math]::Round($_.WorkingSet64 / 1MB, 1) } }

ollama show snowflake-arctic-embed2:latest

Get-Process *llama*, *ollama* -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, CPU