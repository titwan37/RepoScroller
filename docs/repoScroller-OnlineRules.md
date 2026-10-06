Viewed app.js:150-200
Ran command: `python -c "
with open('frontend/app.js', 'r', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f, 1):
        if '11434' in line:
            print(f'{i}: {line.strip()[:100]}')
"`
Used tool: manage_task
Viewed app.js:4560-4590
Ran command: `python -c "
with open('frontend/app.js', 'r', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f, 1):
        if 'API_BASE' in line:
            print(f'{i}: {line.strip()[:100]}')
"`
Viewed hub.conf:285-315
Viewed app.js:4630-4740
Ran command: `python -c "
with open('frontend/app.js', 'r', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f, 1):
        if 'EventSource' in line:
            print(f'{i}: {line.strip()[:100]}')
"`
Viewed app.js:2915-2935
Ran command: `python -c "
with open('frontend/app.js', 'r', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f, 1):
        if '/api/v1' in line and not line.strip().startswith('//'):
            print(f'{i}: {line.strip()[:100]}')
"`
Used tool: manage_task
Viewed app.js:3030-3100
Viewed app.js:3110-3235
Edited app.js
Edited app.js
Viewed app.js:3040-3090
Edited app.js
Edited app.js
Viewed app.js:3115-3235
Edited app.js
Edited app.js
Viewed app.js:4555-4580
Edited app.js
Ran command: `node --check frontend/app.js`
Viewed index.html:10-25
Viewed index.html:1840-1850
Edited index.html
Edited index.html
Ran command: `git status -s`
Used tool: manage_task

Voici l'explication technique exacte des erreurs 404 et du blocage CORS que vous avez constatés après le déploiement :

---

### 1. Pourquoi toutes les requêtes API renvoyaient 404 (`https://afastudio.ch/api/v1/...`) ?

#### La cause dans le code

Dans [frontend/app.js](file:///c:/Dev/RepoScroller/frontend/app.js#L159-L173), l'intercepteur `window.fetch` contenait ce bloc :

```javascript
window.fetch = async function (...args) {
  let [resource, config] = args;
  if (typeof resource === "string" && resource.startsWith("/api/v1")) {
    resource = API_PREFIX + resource; // <-- modifiait la variable locale `resource`
  }
  // Mais la ligne suivante appelait l'API avec `args` NON MODIFIÉ :
  const response = await _rawFetch.apply(this, args); // <-- `args[0]` valait toujours "/api/v1/..." !
```

- L'URL dans `args[0]` n'était jamais remplacée par la version préfixée.
- Par conséquent, le navigateur envoyait les requêtes à :
  `https://afastudio.ch/api/v1/diagnostics/health` (qui n'existe pas sur le domaine principal, d'où le **404**)
  au lieu de :
  `https://afastudio.ch/reposcroller/api/v1/diagnostics/health` (qui est la route Nginx routant vers FastAPI sur le port 3739).
- De plus, les fonctions de monitoring (`fetchDiagnosticLogs`, `fetchDiagnosticHealth`, `reportFrontendIssueToBackend`, `clearDiagnosticLogs`) appelaient directement `_rawFetch("/api/v1/...")` en contournant l'intercepteur.

#### La correction appliquée

1. Dans l'intercepteur `window.fetch`, `args[0] = resource;` est maintenant explicitement assigné : chaque appel fetch relatif est automatiquement réécrit en `/reposcroller/api/v1/...`.
2. Tous les appels directs `_rawFetch` ont été préfixés avec `${API_PREFIX}`.

---

### 2. Pourquoi l'erreur CORS et Forbidden 403 sur `http://127.0.0.1:11434/api/ps` ?

#### La cause

Dans `pollOllamaProcessInspector`, le frontend tentait de contacter directement `http://127.0.0.1:11434/api/ps` depuis le navigateur :

- Lorsque vous êtes sur `https://afastudio.ch/reposcroller/`, le navigateur bloque les requêtes directes vers `http://127.0.0.1` pour cause de **Mixed Content** (HTTPS vers HTTP non sécurisé) et de restriction **CORS**.
- Sur un serveur en ligne, le navigateur de l'utilisateur n'a pas accès au localhost de la machine hôte.

#### La correction appliquée

La tentative de fetch direct sur `http://127.0.0.1:11434` n'a lieu qu'en **développement local** (`localhost` ou `127.0.0.1` en `http:`). En production en ligne, le frontend bascule automatiquement et de manière transparente sur le proxy backend sécurisé :
`/reposcroller/api/v1/diagnostics/ollama/ps?node=pc1`.

---

### 3. Cache buster incrémenté à `v=31`

Dans [frontend/index.html](file:///c:/Dev/RepoScroller/frontend/index.html#L17-L1847), les balises ont été passées à `v=31` :

- `<link rel="stylesheet" href="style.css?v=31">`
- `<script src="app.js?v=31"></script>`

Cela garantit que votre navigateur rechargera immédiatement le code corrigé sans garder l'ancienne version en cache.

---

### 🚀 Pour mettre en ligne les correctifs

Dans votre terminal dans `C:\dev\hub` :

```powershell
.\deploy_menu.ps1
```

*(Sélectionner l'option RepoScroller)*. Dès le déploiement terminé, faites `Ctrl + F5` sur `https://afastudio.ch/reposcroller/` : tous les endpoints répondront en 200 OK.
