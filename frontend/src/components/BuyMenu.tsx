import { useEffect, useRef, useState } from 'react'
import { api, type PurchaseLink } from '../api/client'
import { t } from '../i18n'

/** "Buy ▾": the card's search at every enabled shop (Settings › Where to buy), opened in the browser. */
export function BuyMenu({ cardId, className = 'link-button small' }: { cardId: string; className?: string }) {
  const [links, setLinks] = useState<PurchaseLink[] | null>(null)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = () => {
    if (!open) {
      setError(null)
      api.cardPurchaseLinks(cardId).then(setLinks, (e: Error) => setError(e.message))
    }
    setOpen(!open)
  }

  return (
    <span className="buy-menu" ref={ref}>
      <button className={className} onClick={toggle} title={t.buy.title} aria-expanded={open}>
        {t.buy.button}
      </button>
      {open && (
        <div className="context-menu" role="menu">
          {error ? (
            <p className="status error small">{error}</p>
          ) : !links ? (
            <p className="muted small">{t.common.loading}</p>
          ) : links.length === 0 ? (
            <p className="muted small">{t.buy.noSources}</p>
          ) : (
            links.map((link) => (
              <a
                key={link.source_id}
                className="buy-menu-link"
                href={link.url}
                target="_blank"
                rel="noreferrer"
                role="menuitem"
                onClick={() => setOpen(false)}
              >
                {t.buy.searchAt(link.name)}
              </a>
            ))
          )}
        </div>
      )}
    </span>
  )
}
