import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { loadPrefs } from './prefs'

// Preferences first: the language (and with it every text) is picked when the app's modules load.
loadPrefs().then(async () => {
  const { default: App } = await import('./App.tsx')
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
