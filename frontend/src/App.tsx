import { useCallback, useEffect, useState } from 'react'
import { api, type SyncStatus } from './api/client'
import { AppUpdateBanner } from './components/AppUpdate'
import { CloudBackupBanner } from './components/CloudBackupBanner'
import { UpdateBanner } from './components/UpdateBanner'
import { t } from './i18n'
import { CollectionItemsView, type LocationFilter } from './views/CollectionItemsView'
import { CollectionPage } from './views/CollectionPage'
import { CollectionView } from './views/CollectionView'
import { LocationsView } from './views/LocationsView'
import { DeckBuilderView, type DeckTab } from './views/DeckBuilderView'
import { DecksView } from './views/DecksView'
import { ImportView } from './views/ImportView'
import { ProxiesView } from './views/ProxiesView'
import { ScanView } from './views/ScanView'
import { SettingsView } from './views/SettingsView'

type Route =
  | { view: 'collection' }
  | { view: 'items'; location: LocationFilter }
  | { view: 'locations' }
  | { view: 'proxies' }
  | { view: 'settings' }
  | { view: 'decks' }
  | { view: 'import' }
  | { view: 'scan' }
  | { view: 'deck'; deckId: number; tab: DeckTab }

const NAV: { id: keyof typeof t.nav; label: string }[] = [
  { id: 'collection', label: t.nav.collection },
  { id: 'decks', label: t.nav.decks },
  { id: 'import', label: t.nav.import },
  { id: 'scan', label: t.nav.scan },
  { id: 'settings', label: t.nav.settings },
]

function routeFromHash(): Route {
  const hash = window.location.hash
  const deck = hash.match(/^#\/decks\/(\d+)(?:\/(stats|missing|history))?$/)
  if (deck) return { view: 'deck', deckId: Number(deck[1]), tab: (deck[2] as DeckTab | undefined) ?? 'pool' }
  if (hash === '#/decks') return { view: 'decks' }
  const items = hash.match(/^#\/collection\/items(?:\/(none|\d+))?$/)
  if (items) return { view: 'items', location: items[1] ? (items[1] === 'none' ? 'none' : Number(items[1])) : 'all' }
  if (hash === '#/collection/locations') return { view: 'locations' }
  if (hash === '#/collection/proxies') return { view: 'proxies' }
  if (hash === '#/settings') return { view: 'settings' }
  if (hash === '#/import') return { view: 'import' }
  if (hash === '#/scan') return { view: 'scan' }
  return { view: 'collection' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash)
  const [status, setStatus] = useState<SyncStatus | null>(null)
  const [backendError, setBackendError] = useState<string | null>(null)

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const refreshStatus = useCallback(() => {
    api.syncStatus().then(
      (s) => {
        setStatus(s)
        setBackendError(null)
      },
      (e: Error) => setBackendError(e.message),
    )
  }, [])

  useEffect(refreshStatus, [refreshStatus])

  const go = (path: string) => {
    window.location.assign(`#/${path}`)
  }
  const activeNav =
    route.view === 'deck' ? 'decks' : route.view === 'items' || route.view === 'locations' || route.view === 'proxies'
        ? 'collection'
        : route.view

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <span>MTG Deck Manager</span>
        </div>
        <nav>
          {NAV.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${activeNav === item.id ? 'active' : ''}`}
              onClick={() => go(item.id)}
            >
              {item.label}
              {item.id === 'settings' && status?.progress.running && <span className="dot" title={t.nav.syncing} />}
            </button>
          ))}
        </nav>
      </aside>

      <main className="content">
        {status && (
          <UpdateBanner
            status={status}
            onRefresh={() => {
              go('settings')
              setTimeout(refreshStatus, 500)
            }}
          />
        )}
        {status && <CloudBackupBanner />}
        <AppUpdateBanner />
        {backendError ? (
          <div className="view">
            <section className="panel">
              <p className="status error">{t.app.backendDown(backendError)}</p>
              <button className="button" onClick={refreshStatus}>
                {t.common.retry}
              </button>
            </section>
          </div>
        ) : !status ? (
          <div className="view">
            <p className="muted">{t.app.connecting}</p>
          </div>
        ) : route.view === 'settings' ? (
          <SettingsView status={status} onStatusChange={refreshStatus} />
        ) : route.view === 'decks' ? (
          <DecksView onOpen={(id) => go(`decks/${id}`)} />
        ) : route.view === 'scan' ? (
          <ScanView />
        ) : route.view === 'import' ? (
          <ImportView
            onImported={(id) => go(`decks/${id}`)}
            onCollectionImported={(loc) => go(loc === null ? 'collection/items/none' : `collection/items/${loc}`)}
          />
        ) : route.view === 'deck' ? (
          <DeckBuilderView
            key={route.deckId}
            deckId={route.deckId}
            tab={route.tab}
            onTabChange={(tab) => go(`decks/${route.deckId}${tab === 'pool' ? '' : `/${tab}`}`)}
            onBack={() => go('decks')}
          />
        ) : (
          <CollectionPage
            tab={route.view === 'items' || route.view === 'locations' || route.view === 'proxies' ? route.view : 'cards'}
            onTab={(tab) => go(tab === 'cards' ? 'collection' : `collection/${tab}`)}
          >
            {route.view === 'items' ? (
              <CollectionItemsView
                location={route.location}
                onLocationChange={(loc) => go(loc === 'all' ? 'collection/items' : `collection/items/${loc}`)}
              />
            ) : route.view === 'locations' ? (
              <LocationsView onOpen={(id) => go(`collection/items/${id}`)} />
            ) : route.view === 'proxies' ? (
              <ProxiesView />
            ) : (
              <CollectionView hasData={status.card_count > 0} onOpenSettings={() => go('settings')} />
            )}
          </CollectionPage>
        )}
      </main>
    </div>
  )
}
