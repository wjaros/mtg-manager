import type { components } from './schema'
import { lang } from '../i18n'

type Schemas = components['schemas']
export type Health = Schemas['Health']
export type CardSummary = Schemas['CardSummary']
export type CardDetail = Schemas['CardDetail']
export type CardPage = Schemas['CardPage']
export type SetInfo = Schemas['SetInfo']
export type SyncStatus = Schemas['SyncStatus']
export type SyncProgress = Schemas['SyncProgressModel']
export type SyncCheck = Schemas['SyncCheck']
export type DeckSummary = Schemas['DeckSummary']
export type DeckDetail = Schemas['DeckDetail']
export type DeckCard = Schemas['DeckCard']
export type DeckCreate = Schemas['DeckCreate']
export type DeckUpdate = Schemas['DeckUpdate']
export type DeckFormat = DeckSummary['format']
export type Platform = DeckSummary['platform']
export type Board = DeckCard['board']
export type ImportReport = Schemas['ImportReport']
export type ImportLine = Schemas['ImportLine']
export type ImportCommitRequest = Schemas['ImportCommitRequest']
export type ExportResult = Schemas['ExportResult']
export type SeedInfo = Schemas['SeedInfo']
export type CollectionItem = Schemas['CollectionItem']
export type CollectionItemCreate = Schemas['CollectionItemCreate']
export type CollectionStats = Schemas['CollectionStats']
export type Location = Schemas['Location']
export type DeckToCollectionResult = Schemas['DeckToCollectionResult']
export type DeckStats = Schemas['DeckStats']
export type CardUsage = Schemas['CardUsage']
export type Holding = Schemas['Holding']
export type CollectionImportReport = Schemas['CollectionImportReport']
export type CollectionImportEntry = Schemas['CollectionImportEntry']
export type CollectionImportResult = Schemas['CollectionImportResult']
export type DeckChange = Schemas['DeckChange']
export type DeckChanges = Schemas['DeckChanges']
export type DeckVersion = Schemas['DeckVersion']
export type DeckVersionDetail = Schemas['DeckVersionDetail']
export type ValidationResult = Schemas['ValidationResult']
export type ValidationIssue = Schemas['Issue']
export type MissingReport = Schemas['MissingReport']
export type MissingEntry = Schemas['MissingEntry']
export type CollectionItemUpdate = Schemas['CollectionItemUpdate']
export type LocationKind = Location['kind']
export type MissingFormat = 'cardmarket' | 'text' | 'csv'
export type BackupImportResult = Schemas['ImportResult']
export type Scan = Schemas['Scan']
export type ScanItem = Schemas['ScanItem']
export type ScanItemUpdate = Schemas['ScanItemUpdate']
export type ScanCommitResult = Schemas['CommitResult']
export type OcrEngines = Schemas['OcrEngines']
export type ProxyCandidate = Schemas['ProxyCandidate']
export type PrinterProfile = Schemas['PrinterProfile']
export type PrintSettings = Schemas['PrintSettings']
export type ProxyPrint = Schemas['ProxyPrint']
export type PrintJobStatus = Schemas['PrintJobStatus']
export type CalibrationResult = Schemas['CalibrationResult']
export type Measurements = Schemas['Measurements']
export type Paper = PrinterProfile['paper']

export type ImageSize = 'small' | 'normal' | 'large' | 'art_crop' | 'png'
export type ColorMode = 'include' | 'exact' | 'identity'
export type Order = 'name' | 'mv' | 'released'

export interface CardQuery {
  q?: string
  text?: string
  colors?: string
  color_mode?: ColorMode
  identity?: string
  mv?: number[]
  type?: string[]
  rarity?: string[]
  set?: string[]
  format?: string
  game?: 'paper' | 'arena' | 'mtgo'
  owned?: 'owned' | 'missing' | 'free'
  /** Deck being built: its own box counts as free for owned=free. */
  deck?: number
  /** Hide cards already in this deck (basic lands stay). */
  not_in_deck?: number
  unique?: 'cards' | 'prints'
  order?: Order
  include_extras?: boolean
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // The backend translates its messages (validation, import warnings, errors) to the UI language.
  const resp = await fetch(path, {
    ...init,
    headers: { Accept: 'application/json', 'Accept-Language': lang, ...init?.headers },
  })
  if (!resp.ok) {
    let message = `${resp.status} ${resp.statusText}`
    try {
      const body = await resp.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // keep the status text
    }
    throw new ApiError(resp.status, message)
  }
  return resp.json() as Promise<T>
}

function toSearchParams(params: Record<string, unknown>): URLSearchParams {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)))
    else search.set(key, String(value))
  }
  return search
}

export const api = {
  health: () => request<Health>('/api/health'),

  searchCards: (query: CardQuery, page: number, pageSize: number, signal?: AbortSignal) =>
    request<CardPage>(`/api/cards?${toSearchParams({ ...query, page, page_size: pageSize })}`, { signal }),
  card: (id: string) => request<CardDetail>(`/api/cards/${id}`),
  parseMoxfieldCollection: (text: string) =>
    request<CollectionImportReport>('/api/collection/import/moxfield/parse', jsonBody('POST', { text })),
  commitCollectionImport: (entries: CollectionImportEntry[], locationId: number | null) =>
    request<CollectionImportResult>(
      '/api/collection/import/commit',
      jsonBody('POST', { entries, location_id: locationId }),
    ),
  cardUsage: (id: string, deck?: number) =>
    request<CardUsage>(`/api/cards/${id}/usage?${toSearchParams({ deck })}`),
  printings: (id: string) => request<CardSummary[]>(`/api/cards/${id}/printings`),
  sets: () => request<SetInfo[]>('/api/sets'),

  decks: () => request<DeckSummary[]>('/api/decks'),
  deck: (id: number) => request<DeckDetail>(`/api/decks/${id}`),
  createDeck: (body: DeckCreate) => request<DeckDetail>('/api/decks', jsonBody('POST', body)),
  updateDeck: (id: number, body: DeckUpdate) => request<DeckDetail>(`/api/decks/${id}`, jsonBody('PATCH', body)),
  deleteDeck: (id: number) =>
    fetch(`/api/decks/${id}`, { method: 'DELETE' }).then((r) => {
      if (!r.ok) throw new ApiError(r.status, r.statusText)
    }),
  addDeckCard: (id: number, cardId: string, board: Board = 'main', quantity = 1) =>
    request<DeckDetail>(`/api/decks/${id}/cards`, jsonBody('POST', { card_id: cardId, board, quantity })),
  removeDeckCard: (id: number, cardId: string, board: Board = 'main', quantity?: number) =>
    request<DeckDetail>(
      `/api/decks/${id}/cards/${cardId}?${toSearchParams({ board, quantity })}`,
      { method: 'DELETE' },
    ),
  updateDeckCard: (
    id: number,
    cardId: string,
    board: Board,
    change: { new_board?: Board; quantity?: number; new_card_id?: string; category?: string },
  ) => request<DeckDetail>(`/api/decks/${id}/cards/${cardId}`, jsonBody('PATCH', { board, ...change })),

  deckVersions: (id: number) => request<DeckVersion[]>(`/api/decks/${id}/versions`),
  saveDeckVersion: (id: number, note?: string) =>
    request<DeckVersion>(`/api/decks/${id}/versions`, jsonBody('POST', { note: note ?? null })),
  deckVersion: (id: number, versionId: number, compare: 'previous' | 'current' = 'previous') =>
    request<DeckVersionDetail>(`/api/decks/${id}/versions/${versionId}?compare=${compare}`),
  restoreDeckVersion: (id: number, versionId: number) =>
    request<DeckDetail>(`/api/decks/${id}/versions/${versionId}/restore`, { method: 'POST' }),
  deckStats: (id: number) => request<DeckStats>(`/api/decks/${id}/stats`),
  validateDeck: (id: number) => request<ValidationResult>(`/api/decks/${id}/validate`),
  exportDeck: (id: number, target: 'arena' | 'text') =>
    request<ExportResult>(`/api/decks/${id}/export?target=${target}`),
  parseImport: (text: string, platform?: Platform) =>
    request<ImportReport>('/api/import/parse', jsonBody('POST', { text, platform })),
  commitImport: (body: ImportCommitRequest) => request<DeckDetail>('/api/import/commit', jsonBody('POST', body)),
  seeds: () => request<SeedInfo[]>('/api/import/seeds'),

  collection: (filter: { card_id?: string; oracle_id?: string; location_id?: number; unassigned?: boolean; q?: string }) =>
    request<CollectionItem[]>(`/api/collection?${toSearchParams(filter)}`),
  collectionStats: () => request<CollectionStats>('/api/collection/stats'),
  addToCollection: (body: CollectionItemCreate) =>
    request<CollectionItem>('/api/collection', jsonBody('POST', body)),
  removeFromCollection: (itemId: number, quantity?: number) =>
    request<CollectionItem | null>(`/api/collection/${itemId}?${toSearchParams({ quantity })}`, {
      method: 'DELETE',
    }),
  updateCollectionItem: (itemId: number, body: CollectionItemUpdate) =>
    request<CollectionItem>(`/api/collection/${itemId}`, jsonBody('PATCH', body)),
  locations: () => request<Location[]>('/api/locations'),
  createLocation: (name: string, kind: LocationKind) =>
    request<Location>('/api/locations', jsonBody('POST', { name, kind })),
  updateLocation: (id: number, body: { name?: string; kind?: LocationKind }) =>
    request<Location>(`/api/locations/${id}`, jsonBody('PATCH', body)),
  deleteLocation: (id: number) =>
    fetch(`/api/locations/${id}`, { method: 'DELETE' }).then((r) => {
      if (!r.ok) throw new ApiError(r.status, r.statusText)
    }),
  deckHoldings: (deckId: number) => request<Holding[]>(`/api/decks/${deckId}/holdings`),
  deckMissing: (deckId: number, excludeOtherDecks: boolean) =>
    request<MissingReport>(`/api/decks/${deckId}/missing?exclude_other_decks=${excludeOtherDecks}`),
  missingExport: (deckId: number, format: MissingFormat, excludeOtherDecks: boolean) =>
    fetch(missingExportUrl(deckId, format, excludeOtherDecks)).then((r) => {
      if (!r.ok) throw new ApiError(r.status, r.statusText)
      return r.text()
    }),
  deckToCollection: (deckId: number, replace = false) =>
    request<DeckToCollectionResult>(`/api/decks/${deckId}/collection?replace=${replace}`, { method: 'POST' }),

  backupImport: (data: unknown, replace: boolean) =>
    request<BackupImportResult>(`/api/backup/import?replace=${replace}`, jsonBody('POST', data)),

  scanEngines: () => request<OcrEngines>('/api/scan-engines'),
  scans: () => request<Scan[]>('/api/scans'),
  uploadScan: (file: File, engine?: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('kind', 'auto')
    if (engine) form.append('engine', engine)
    return request<Scan[]>('/api/scans', { method: 'POST', body: form })
  },
  regridScan: (scanId: number, rows: number, cols: number, region?: [number, number, number, number]) =>
    request<Scan>(`/api/scans/${scanId}/grid`, jsonBody('POST', { rows, cols, region: region ?? null })),
  updateScanItem: (scanId: number, itemId: number, body: ScanItemUpdate) =>
    request<Scan>(`/api/scans/${scanId}/items/${itemId}`, jsonBody('PATCH', body)),
  commitScan: (scanId: number) => request<ScanCommitResult>(`/api/scans/${scanId}/commit`, { method: 'POST' }),
  deleteScan: (scanId: number) =>
    fetch(`/api/scans/${scanId}`, { method: 'DELETE' }).then((r) => {
      if (!r.ok) throw new ApiError(r.status, r.statusText)
    }),

  proxyCandidates: (deckId: number, includeBasics: boolean) =>
    request<ProxyCandidate[]>(`/api/decks/${deckId}/proxy-candidates?include_basics=${includeBasics}`),
  printSettings: () => request<PrintSettings>('/api/print/settings'),
  savePrintSettings: (body: PrintSettings) => request<PrintSettings>('/api/print/settings', jsonBody('PUT', body)),
  printerProfiles: () => request<PrinterProfile[]>('/api/print/profiles'),
  createPrinterProfile: (name: string, paper: Paper) =>
    request<PrinterProfile>('/api/print/profiles', jsonBody('POST', { name, paper })),
  updatePrinterProfile: (id: number, body: { name?: string; paper?: Paper; is_default?: boolean }) =>
    request<PrinterProfile>(`/api/print/profiles/${id}`, jsonBody('PATCH', body)),
  deletePrinterProfile: (id: number) =>
    fetch(`/api/print/profiles/${id}`, { method: 'DELETE' }).then((r) => {
      if (!r.ok) throw new ApiError(r.status, r.statusText)
    }),
  calibratePrinter: (id: number, body: Measurements) =>
    request<CalibrationResult>(`/api/print/profiles/${id}/calibrate`, jsonBody('POST', body)),
  startPrint: (body: ProxyPrint) => request<PrintJobStatus>('/api/print/jobs', jsonBody('POST', body)),
  printJob: (id: string) => request<PrintJobStatus>(`/api/print/jobs/${id}`),

  syncStatus: () => request<SyncStatus>('/api/sync/status'),
  syncCheck: () => request<SyncCheck>('/api/sync/check'),
  syncStart: (force = false) => request<SyncProgress>('/api/sync/start', jsonBody('POST', { force })),
}

function jsonBody(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

// Scryfall image widths: small 146 px, normal 488 px, large 672 px.
/** The smallest image that stays sharp at this width (CSS px) on this screen (retina: 2 device px each). */
export function imageSizeFor(cssWidth: number): ImageSize {
  const pixels = cssWidth * (window.devicePixelRatio || 1)
  return pixels <= 160 ? 'small' : pixels <= 540 ? 'normal' : 'large'
}

export function imageUrl(cardId: string, size: ImageSize = 'normal', face = 0): string {
  return `/api/images/${cardId}/${size}${face ? `?face=${face}` : ''}`
}

export function missingExportUrl(deckId: number, format: MissingFormat, excludeOtherDecks: boolean): string {
  return `/api/decks/${deckId}/missing/export?format=${format}&exclude_other_decks=${excludeOtherDecks}`
}

export function collectionExportUrl(
  format: 'arena' | 'csv' | 'moxfield',
  filter: { location_id?: number; unassigned?: boolean } = {},
  download = false,
): string {
  return `/api/collection/export?${toSearchParams({ format, ...filter, download: download || undefined })}`
}

export function calibrationPdfUrl(paper: Paper, profileId?: number): string {
  return `/api/print/calibration.pdf?${toSearchParams({ paper, profile_id: profileId })}`
}

export function printJobPdfUrl(jobId: string): string {
  return `/api/print/jobs/${jobId}/pdf`
}

export function deckPdfUrl(deckId: number): string {
  return `/api/decks/${deckId}/export/pdf`
}

// Scan and item ids are reused after deletes, so an image URL can mean a different file than it
// did earlier. The server sends no-cache, and the session token keeps entries cached by older
// versions (or earlier sessions) from ever matching.
const SCAN_IMAGE_SESSION = Date.now().toString(36)

export function scanImageUrl(scanId: number): string {
  return `/api/scans/${scanId}/image?s=${SCAN_IMAGE_SESSION}`
}

export function scanItemImageUrl(scanId: number, itemId: number): string {
  return `/api/scans/${scanId}/items/${itemId}/image?s=${SCAN_IMAGE_SESSION}`
}

export function setIconUrl(code: string): string {
  return `/api/sets/${code}/icon`
}
