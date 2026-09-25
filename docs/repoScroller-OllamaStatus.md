Windows PowerShell
Copyright (C) Microsoft Corporation. All rights reserved.

PS C:\WINDOWS\system32> cd C:\dev\RepoScroller
PS C:\dev\RepoScroller> .\start_pc2_cuda_node.bat
================================================================
   RepoScroller - PC2 CUDA GPU Server Launcher (RTX 3060)
================================================================

================================================================
   RepoScroller - PC2 CUDA GPU Inference Node Launcher
================================================================

[1/4] Checking NVIDIA RTX 3060 GPU...
  -> GPU: NVIDIA GeForce RTX 3060 Laptop GPU, 6144 MiB, 610.88

[2/4] Checking Ollama Server on port 11434...
  -> Ollama Server is ONLINE (0.0.0.0:11434)

[3/4] Pre-warming embedding model 'snowflake-arctic-embed2:latest' into VRAM...
  -> Embedding model loaded (1024-dim, warm-up took 277ms)

[4/4] Pre-warming chat model 'llama3.2:3b' into VRAM...
  -> Chat model 'llama3.2:3b' loaded into VRAM (took 341ms)

================================================================
   PC2 CUDA GPU NODE IS ACTIVE & READY FOR PC1 REQUESTS
================================================================
 Endpoints listening on LAN:
   -> http://192.168.192.37:11434
   -> http://192.168.192.9:11434

 Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     2048       24 hours from now

 Press [Ctrl+C] to exit or leave this window open.
================================================================

[19:05:01] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     2048       24 hours from now
[19:06:01] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     2048       24 hours from now
[19:07:01] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     2048       24 hours from now
[19:08:01] Active Models in VRAM:
NAME                             ID              SIZE      PROCESSOR    CONTEXT    UNTIL
nomic-embed-text:latest          0a109f422b47    323 MB    100% GPU     2048       24 hours from now
snowflake-arctic-embed:latest    21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                      a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:09:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:10:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:11:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:12:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:13:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:14:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:15:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:16:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:17:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:18:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:19:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:20:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:21:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:22:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:23:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:24:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
snowflake-arctic-embed:latest     21ab8b9b0545    618 MB    100% GPU     512        24 hours from now
llama3.2:3b                       a80c4f17acd5    3.1 GB    100% GPU     2048       24 hours from now
[19:25:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:26:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:27:02] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:28:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:29:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:30:03] Active Models in VRAM:
NAME           ID              SIZE      PROCESSOR    CONTEXT    UNTIL
llama3.2:3b    a80c4f17acd5    4.0 GB    100% GPU     4096       Stopping...
[19:31:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:32:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:33:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:34:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:35:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:36:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:37:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:38:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:39:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:40:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:41:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:42:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:43:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:44:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:45:03] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:46:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:47:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:48:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:49:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:50:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:51:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:52:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:53:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:54:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:55:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:56:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:57:04] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:58:05] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[19:59:05] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[20:00:05] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[20:01:05] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[20:02:05] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now
[20:03:37] Active Models in VRAM:
NAME                              ID              SIZE      PROCESSOR    CONTEXT    UNTIL
snowflake-arctic-embed2:latest    5de93a84837d    664 MB    100% GPU     4096       24 hours from now