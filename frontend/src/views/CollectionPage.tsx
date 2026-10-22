import { useState, type ReactNode } from 'react'
import { ProxyDialog } from '../components/ProxyDialog'
import { usePrintQueue } from '../printQueue'
import { t } from '../i18n'

export type CollectionTab = 'cards' | 'items' | 'locations'

const TABS: [CollectionTab, string][] = [
  ['cards', t.collection.tabCards],
  ['items', t.collection.tabItems],
  ['locations', t.collection.tabLocations],
]

/** Collection header with tabs; the active tab's view fills the rest of the page. */
export function CollectionPage({
  tab,
  onTab,
  children,
}: {
  tab: CollectionTab
  onTab: (tab: CollectionTab) => void
  children: ReactNode
}) {
  const [printing, setPrinting] = useState(false)
  const queued = usePrintQueue().reduce((n, q) => n + q.qty, 0)
  return (
    <div className="collection-page">
      <header className="collection-page-header">
        <h1>{t.collection.title}</h1>
        <div className="segmented" role="tablist">
          {TABS.map(([id, label]) => (
            <button key={id} role="tab" className={tab === id ? 'on' : ''} onClick={() => onTab(id)}>
              {label}
            </button>
          ))}
        </div>
        <button className="button collection-print" onClick={() => setPrinting(true)}>
          {t.print.collectionButton}
          {queued > 0 && ` (${queued})`}
        </button>
      </header>
      {printing && <ProxyDialog deckId={null} onClose={() => setPrinting(false)} />}
      <div className="collection-page-body">{children}</div>
    </div>
  )
}
