import express from 'express'

const app = express()
const PORT = process.env.PORT || 3000

const GITHUB_CLIENT_ID = process.env.GITHUB_CLIENT_ID || ''
const GITHUB_CLIENT_SECRET = process.env.GITHUB_CLIENT_SECRET || ''
const GITHUB_REDIRECT_URI = process.env.GITHUB_REDIRECT_URI || 'http://localhost:3000/auth/github/callback'

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

    res.send(`
      <html>
        <body>
          <h1>Authentication successful</h1>
          <p>Access token: ${accessToken.slice(0, 10)}...</p>
          <script>
            window.location.href = '/dashboard'
          </script>
        </body>
      </html>
    `)
  } catch (error) {
    res.status(500).send('Authentication failed')
  }
})

app.get('/dashboard', (req, res) => {
  res.send('<h1>Dashboard</h1><p>Your swarm will appear here.</p>')
})

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`)
})
