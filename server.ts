import express from 'express'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'
import fs from 'fs/promises'
import os from 'os'

const execAsync = promisify(exec)
const app = express()
app.use(express.json())

const PORT = process.env.PORT || 3000

const GITHUB_CLIENT_ID = process.env.GITHUB_CLIENT_ID || ''
const GITHUB_CLIENT_SECRET = process.env.GITHUB_CLIENT_SECRET || ''
const GITHUB_REDIRECT_URI = process.env.GITHUB_REDIRECT_URI || 'http://localhost:3000/auth/github/callback'

const sessions = new Map<string, { token: string, githubUser: string }>()

app.get('/auth/github', (req, res) => {
  const githubAuthUrl = `https://github.com/login/oauth/authorize?client_id=${GITHUB_CLIENT_ID}&redirect_uri=${GITHUB_REDIRECT_URI}&scope=repo`
  res.redirect(githubAuthUrl)
})

app.get('/auth/github/callback', async (req, res) => {
  const code = req.query.code as string
  
  if (!code) {
    return res.status(400).send('No code provided')
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
    const sessionId = Math.random().toString(36).substring(7)
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
    
    await execAsync(`git clone ${clone_url} ${repoPath}`)
    
    const provisionScript = path.join(__dirname, 'provision.py')
    const { stdout } = await execAsync(
      `python3 ${provisionScript} ${name} ${repoPath} ${session.githubUser} ${clone_url} ${template}`
    )
    const projectId = stdout.trim()
    
    res.json({ project_id: projectId, repo_path: repoPath, full_name })
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
})

app.get('/select', (req, res) => {
  res.sendFile(path.join(__dirname, 'select.html'))
})

app.get('/dashboard/:projectId', (req, res) => {
  res.send(`<h1>Dashboard</h1><p>Project: ${req.params.projectId}</p><p>Ledger will appear here.</p>`)
})

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`)
})
