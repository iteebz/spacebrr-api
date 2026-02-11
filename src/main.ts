import './style.css'

document.querySelector<HTMLDivElement>('#app')!.innerHTML = `
  <div class="container">
    <h1>Space</h1>
    <p class="tagline">Connect a repo. Walk away. Come back to a better codebase.</p>
    <button id="connect-github" type="button">Connect GitHub</button>
  </div>
`

document.querySelector<HTMLButtonElement>('#connect-github')!.addEventListener('click', () => {
  window.location.href = '/auth/github'
})
