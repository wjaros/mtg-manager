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
import { WantsView } from './views/WantsView'
import { useWants } from './wants'
import { SettingsView } from './views/SettingsView'
import { getPref, setPref, setUiScale, stepUiScale, useUiScale } from './prefs'

type Route =
  | { view: 'collection' }
  | { view: 'items'; location: LocationFilter }
  | { view: 'locations' }
  | { view: 'proxies' }
  | { view: 'wants' }
  | { view: 'settings' }
  | { view: 'decks' }
  | { view: 'import' }
  | { view: 'scan' }
  | { view: 'deck'; deckId: number; tab: DeckTab }

const NAV: { id: keyof typeof t.nav; label: string; icon: string }[] = [
  // 24×24 stroke paths, shown alone when the sidebar is collapsed
  { id: 'collection', label: t.nav.collection, icon: 'M4 6h16M4 12h16M4 18h16' },
  { id: 'decks', label: t.nav.decks, icon: 'M7 3h10v14H7zM4 7v14h10' },
  { id: 'import', label: t.nav.import, icon: 'M12 3v12M7 10l5 5 5-5M4 21h16' },
  { id: 'scan', label: t.nav.scan, icon: 'M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4M8 12h8' },
  {
    id: 'settings',
    label: t.nav.settings,
    icon: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1',
  },
]

const COLLAPSED_KEY = 'mtgdm.sidebarCollapsed'

function NavIcon({ path }: { path: string }) {
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={path} />
    </svg>
  )
}

function routeFromHash(): Route {
  const hash = window.location.hash
  const deck = hash.match(/^#\/decks\/(\d+)(?:\/(stats|combos|missing|history|compare))?$/)
  if (deck) return { view: 'deck', deckId: Number(deck[1]), tab: (deck[2] as DeckTab | undefined) ?? 'pool' }
  if (hash === '#/decks') return { view: 'decks' }
  const items = hash.match(/^#\/collection\/items(?:\/(none|\d+))?$/)
  if (items) return { view: 'items', location: items[1] ? (items[1] === 'none' ? 'none' : Number(items[1])) : 'all' }
  if (hash === '#/collection/locations') return { view: 'locations' }
  if (hash === '#/collection/proxies') return { view: 'proxies' }
  if (hash === '#/collection/wants') return { view: 'wants' }
  if (hash === '#/settings') return { view: 'settings' }
  if (hash === '#/import') return { view: 'import' }
  if (hash === '#/scan') return { view: 'scan' }
  return { view: 'collection' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash)
  const [status, setStatus] = useState<SyncStatus | null>(null)
  const [backendError, setBackendError] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(() => getPref(COLLAPSED_KEY) === 'true')
  const toggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    void setPref(COLLAPSED_KEY, next ? 'true' : null)
  }

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

  // The window app: Cmd/Ctrl +, − and 0 size the whole interface (a browser zooms by itself).
  const { native: nativeZoom } = useUiScale()
  useEffect(() => {
    if (!nativeZoom) return
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return
      if (e.key === '=' || e.key === '+') stepUiScale(1)
      else if (e.key === '-') stepUiScale(-1)
      else if (e.key === '0') void setUiScale(1)
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [nativeZoom])

  const go = (path: string) => {
    window.location.assign(`#/${path}`)
  }
  const activeNav =
    route.view === 'deck'
      ? 'decks'
      : route.view === 'items' || route.view === 'locations' || route.view === 'proxies' || route.view === 'wants'
        ? 'collection'
        : route.view
  const { notice: wantsNotice } = useWants()

  return (
    <div className={`shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
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
              title={collapsed ? item.label : undefined}
              aria-label={item.label}
            >
              <NavIcon path={item.icon} />
              <span className="nav-label">{item.label}</span>
              {item.id === 'settings' && status?.progress.running && <span className="dot" title={t.nav.syncing} />}
            </button>
          ))}
        </nav>
        <button
          className="nav-item sidebar-toggle"
          onClick={toggleSidebar}
          title={collapsed ? t.nav.expand : t.nav.collapse}
          aria-label={collapsed ? t.nav.expand : t.nav.collapse}
          aria-expanded={!collapsed}
        >
          <NavIcon path={collapsed ? 'M9 6l6 6-6 6' : 'M15 6l-6 6 6 6'} />
          <span className="nav-label">{t.nav.collapse}</span>
        </button>
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
            onOpenDeck={(id) => go(`decks/${id}${route.tab === 'pool' ? '' : `/${route.tab}`}`)}
          />
        ) : (
          <CollectionPage
            tab={
              route.view === 'items' || route.view === 'locations' || route.view === 'proxies' || route.view === 'wants'
                ? route.view
                : 'cards'
            }
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
            ) : route.view === 'wants' ? (
              <WantsView />
            ) : (
              <CollectionView hasData={status.card_count > 0} onOpenSettings={() => go('settings')} />
            )}
          </CollectionPage>
        )}
        {wantsNotice && (
          <div className="notice" role="status">
            {wantsNotice}{' '}
            <button className="link-button" onClick={() => go('collection/wants')}>
              {t.wants.show}
            </button>
          </div>
        )}
      </main>
    </div>
  )
}
