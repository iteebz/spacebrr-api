import express from 'express'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { randomUUID } from 'crypto'
import path from 'path'
import fs from 'fs/promises'
import os from 'os'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const execFileAsync = promisify(execFile)
const app = express()

app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*')
  res.header('Access-Control-Allow-Methods', 'GET, POST, PATCH, OPTIONS')
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
  if (req.method === 'OPTIONS') return res.sendStatus(200)
  next()
})

app.use(express.json())

const PORT = process.env.PORT || 3000

const GITHUB_CLIENT_ID = process.env.GITHUB_CLIENT_ID
const GITHUB_CLIENT_SECRET = process.env.GITHUB_CLIENT_SECRET
const GITHUB_REDIRECT_URI = process.env.GITHUB_REDIRECT_URI || 'http://localhost:3000/auth/github/callback'

if (!GITHUB_CLIENT_ID || !GITHUB_CLIENT_SECRET) {
  throw new Error('GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET must be set')
}

const sessions = new Map<string, { token: string, githubUser: string }>()
const oauthStates = new Map<string, { created: number }>()

app.get('/auth/github', (req, res) => {
  const state = randomUUID()
  oauthStates.set(state, { created: Date.now() })
  const githubAuthUrl = `https://github.com/login/oauth/authorize?client_id=${GITHUB_CLIENT_ID}&redirect_uri=${GITHUB_REDIRECT_URI}&scope=repo&state=${state}`
  res.redirect(githubAuthUrl)
})

app.get('/auth/github/callback', async (req, res) => {
  const code = req.query.code as string
  const state = req.query.state as string
  
  if (!code) {
    return res.status(400).send('No code provided')
  }

  if (!state || !oauthStates.has(state)) {
    return res.status(400).send('Invalid or missing state parameter')
  }

  const stateData = oauthStates.get(state)!
  oauthStates.delete(state)
  
  if (Date.now() - stateData.created > 600000) {
    return res.status(400).send('State expired')
  }

  try {
    const tokenResponse = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        client_id: GITHUB_CLIENT_ID,
        client_secret: GITHUB_CLIENT_SECRET,
        code,
      }),
    })

    const tokenData = await tokenResponse.json()
    const accessToken = tokenData.access_token

    if (!accessToken) {
      return res.status(500).send('Failed to obtain access token')
    }

    const userResponse = await fetch('https://api.github.com/user', {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    const userData = await userResponse.json()
    const sessionId = randomUUID()
    sessions.set(sessionId, { token: accessToken, githubUser: userData.login })

    res.send(`
      <html>
        <body>
          <h1>Authentication successful</h1>
          <script>
            localStorage.setItem('session_id', '${sessionId}')
            window.location.href = '/select'
          </script>
        </body>
      </html>
    `)
  } catch (error) {
    res.status(500).send('Authentication failed')
  }
})

app.get('/api/repos', async (req, res) => {
  const sessionId = req.headers.authorization?.replace('Bearer ', '')
  const session = sessionId ? sessions.get(sessionId) : null
  
  if (!session) {
    return res.status(401).json({ error: 'Unauthorized' })
  }

  try {
    const response = await fetch('https://api.github.com/user/repos?per_page=100', {
      headers: { Authorization: `Bearer ${session.token}` },
    })
    const repos = await response.json()
    res.json(repos.map((r: any) => ({
      name: r.name,
      full_name: r.full_name,
      clone_url: r.clone_url,
      description: r.description,
    })))
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch repos' })
  }
})

const TEMPLATES: Record<string, string> = {
  testing: `## Vector

Comprehensive test coverage: unit tests for core logic, integration tests for workflows, property tests for edge cases.

## Constraints

- Tests break when behavior breaks, not when code changes
- Fast feedback: unit tests < 100ms, full suite < 30s
- Follow repo test conventions`,

  types: `## Vector

Strict type safety: eliminate any, fix type errors, add missing annotations, enable strict mode.

## Constraints

- Preserve runtime behavior
- Follow repo type conventions
- Incremental progress: fix one module at a time`,

  complexity: `## Vector

Reduce cognitive load: extract functions, eliminate deep nesting, simplify conditionals, remove duplication.

## Constraints

- Preserve functionality
- One refactor per commit
- Measure: cyclomatic complexity down, readability up`,

  docs: `## Vector

Clear documentation: README with setup/usage, inline comments for non-obvious code, architecture diagrams for system overview.

## Constraints

- Docs live close to code
- Examples are executable and tested
- Update docs when code changes`,

  security: `## Vector

Harden security: input validation, secret management, dependency updates, vulnerability patches.

## Constraints

- No breaking changes to public API
- Security fixes ship immediately
- Document threat model assumptions`,
}

app.get('/api/templates', (req, res) => {
  res.json(Object.keys(TEMPLATES).map(key => ({
    id: key,
    name: key.charAt(0).toUpperCase() + key.slice(1),
  })))
})

app.post('/api/provision', async (req, res) => {
  const sessionId = req.headers.authorization?.replace('Bearer ', '')
  const session = sessionId ? sessions.get(sessionId) : null
  
  if (!session) {
    return res.status(401).json({ error: 'Unauthorized' })
  }

  const { clone_url, name, template, full_name } = req.body
  if (!clone_url || !name || !template || !full_name) {
    return res.status(400).json({ error: 'Missing clone_url, name, template, or full_name' })
  }

  if (!TEMPLATES[template]) {
    return res.status(400).json({ error: 'Invalid template' })
  }

  try {
    const customerDir = path.join(os.homedir(), 'space', 'customers', session.githubUser)
    await fs.mkdir(customerDir, { recursive: true })
    const repoPath = path.join(customerDir, name)
    
    await execFileAsync('git', ['clone', clone_url, repoPath])
    
    const provisionScript = path.join(__dirname, 'provision.py')
    const { stdout } = await execFileAsync('python3', [
      provisionScript,
      name,
      repoPath,
      session.githubUser,
      clone_url,
      template,
    ])
    const projectId = stdout.trim()
    
    res.json({ project_id: projectId, repo_path: repoPath, full_name })
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/api/ledger/:projectId', async (req, res) => {
  const { projectId } = req.params
  const limit = parseInt(req.query.limit as string) || 50
  
  try {
    const ledgerScript = path.join(__dirname, 'ledger.py')
    const { stdout } = await execFileAsync('python3', [ledgerScript, projectId, String(limit)])
    res.json(JSON.parse(stdout))
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
})

app.patch('/api/tasks/:id/close', async (req, res) => {
  const authHeader = req.headers.authorization
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Unauthorized' })
  }
  
  const { id } = req.params
  if (!/^[a-f0-9]{8}$/.test(id)) {
    return res.status(400).json({ error: 'Invalid task ID' })
  }
  
  try {
    const closeScript = path.join(__dirname, 'close_task.py')
    await execFileAsync('python3', [closeScript, id])
    res.json({ success: true })
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/select', (req, res) => {
  res.sendFile(path.join(__dirname, 'select.html'))
})

app.get('/dashboard/:projectId', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Dashboard</title>
      <style>
        body { font-family: system-ui; max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
        h1 { margin-bottom: 2rem; }
        .ledger-item { border: 1px solid #ddd; padding: 1rem; margin-bottom: 1rem; border-radius: 4px; }
        .ledger-item h3 { margin: 0 0 0.5rem 0; }
        .meta { color: #666; font-size: 0.9rem; }
        .loading { text-align: center; padding: 2rem; }
      </style>
    </head>
    <body>
      <h1>Dashboard</h1>
      <div id="ledger" class="loading">Loading ledger...</div>
      <script>
        const projectId = '${req.params.projectId}'
        fetch('/api/ledger/' + projectId)
          .then(r => r.json())
          .then(items => {
            const ledger = document.getElementById('ledger')
            if (items.length === 0) {
              ledger.innerHTML = '<p>No ledger entries yet. Swarm is starting...</p>'
              return
            }
            ledger.className = ''
            ledger.innerHTML = items.map(item => \`
              <div class="ledger-item">
                <h3>\${item.type}: \${item.content.substring(0, 100)}\${item.content.length > 100 ? '...' : ''}</h3>
                <div class="meta">
                  \${item.identity} • \${new Date(item.created_at).toLocaleString()}
                  \${item.status ? ' • ' + item.status : ''}
                </div>
              </div>
            \`).join('')
          })
          .catch(err => {
            document.getElementById('ledger').innerHTML = '<p>Error loading ledger: ' + err.message + '</p>'
          })
      </script>
    </body>
    </html>
  `)
})

app.post('/api/webhook/github', async (req, res) => {
  const event = req.headers['x-github-event'] as string
  
  if (event !== 'pull_request') {
    return res.status(200).json({ message: 'Event ignored' })
  }
  
  const { action, pull_request, repository } = req.body
  if (!['opened', 'closed'].includes(action)) {
    return res.status(200).json({ message: 'Action ignored' })
  }
  
  const isMerged = action === 'closed' && pull_request.merged
  const eventType = action === 'opened' ? 'opened' : (isMerged ? 'merged' : 'closed')
  
  try {
    const webhookScript = path.join(__dirname, 'space', 'lib', 'webhook_pr.py')
    await execFileAsync('python3', [
      webhookScript,
      eventType,
      String(pull_request.number),
      repository.full_name,
      pull_request.user.login,
      pull_request.merged_by?.login || '',
      pull_request.created_at,
      pull_request.merged_at || '',
    ])
    res.json({ success: true })
  } catch (error: any) {
    console.error('Webhook processing failed:', error)
    res.status(500).json({ error: error.message })
  }
})

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`)
})
