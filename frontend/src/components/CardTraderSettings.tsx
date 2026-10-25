import { useEffect, useState } from 'react'
import { api, type CardTraderStatus } from '../api/client'
import { t } from '../i18n'

/** Settings › CardTrader: the user's API token (from their CardTrader profile), kept on this computer. */
export function CardTraderSettings() {
  const [state, setState] = useState<CardTraderStatus | null>(null)
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    api.cardtrader().then(setState, () => setState(null))
  }, [])

  const connect = async () => {
    setBusy(true)
    setMessage(null)
    try {
      setState(await api.setCardTraderToken(token))
      setToken('')
      setMessage({ ok: true, text: t.cardtrader.connected })
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const changeLanguage = async (language: string | null) => {
    setMessage(null)
    try {
      setState(await api.setCardTraderLanguage(language))
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    }
  }

  const disconnect = async () => {
    setMessage(null)
    try {
      await api.forgetCardTraderToken()
      setState({ connected: false, app_name: null })
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    }
  }

  return (
    <section className="panel">
      <h2>CardTrader</h2>
      <p className="muted small">{t.cardtrader.intro}</p>
      {state?.connected ? (
        <>
          <div className="actions">
            <span>{t.cardtrader.connectedAs(state.app_name ?? null)}</span>
            <button className="button" onClick={disconnect}>
              {t.cardtrader.disconnect}
            </button>
          </div>
          <label className="checkbox">
            {t.cardtrader.language}
            <select
              className="select small"
              value={state.language ?? ''}
              onChange={(e) => changeLanguage(e.target.value || null)}
            >
              <option value="">{t.cardtrader.anyLanguage}</option>
              {Object.entries(t.cardtrader.languages).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </>
      ) : (
        <div className="actions">
          <input
            className="input"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder={t.cardtrader.tokenPlaceholder}
            aria-label={t.cardtrader.tokenPlaceholder}
          />
          <button className="button primary" disabled={!token.trim() || busy} onClick={connect}>
            {busy ? t.cardtrader.checking : t.cardtrader.connect}
          </button>
        </div>
      )}
      {message && <p className={`status ${message.ok ? 'ok' : 'error'}`}>{message.text}</p>}
    </section>
  )
}
