import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/cinzel'
import './index.css'
import { loadPrefs } from './prefs'
import { applyTheme } from './theme'

// Preferences first: the language (and with it every text) is picked when the app's modules load.
loadPrefs().then(async () => {
  applyTheme()
  // Skins name themselves in the UI's language: loaded once prefs (and so the language) are known.
  const [{ applySkin }, { default: App }] = await Promise.all([import('./skins'), import('./App.tsx')])
  applySkin()
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
