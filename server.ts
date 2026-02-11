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

app.post('/api/provision', async (req, res) => {
  const sessionId = req.headers.authorization?.replace('Bearer ', '')
  const session = sessionId ? sessions.get(sessionId) : null
  
  if (!session) {
    return res.status(401).json({ error: 'Unauthorized' })
  }

  const { clone_url, name } = req.body
  if (!clone_url || !name) {
    return res.status(400).json({ error: 'Missing clone_url or name' })
  }

  try {
    const customerDir = path.join(os.homedir(), 'space', 'customers', session.githubUser)
    await fs.mkdir(customerDir, { recursive: true })
    const repoPath = path.join(customerDir, name)
    
    await execAsync(`git clone ${clone_url} ${repoPath}`)
    
    const spaceTemplate = `## Vector

Improve code quality: reduce complexity, add tests, fix type errors.

## Constraints

- Preserve existing functionality
- Follow repo conventions
`
    await fs.writeFile(path.join(repoPath, 'SPACE.md'), spaceTemplate)
    
    const provisionScript = path.join(__dirname, 'provision.py')
    const { stdout } = await execAsync(`python3 ${provisionScript} ${name} ${repoPath}`)
    const projectId = stdout.trim()
    
    res.json({ project_id: projectId, repo_path: repoPath })
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
