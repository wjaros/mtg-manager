import { useEffect, useState } from 'react'
import { api, type PurchaseSettings as Settings, type PurchaseSource, type PurchaseSourcePatch } from '../api/client'
import { t } from '../i18n'

const RATE_CURRENCIES = ['EUR', 'USD']

function num(value: string): number | null {
  const n = Number(value.replace(',', '.'))
  return value.trim() === '' || Number.isNaN(n) ? null : n
}

/** Settings › Where to buy: the shops' search links and the basket planner's thresholds and rates. */
export function PurchaseSettings() {
  const [sources, setSources] = useState<PurchaseSource[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = () => api.purchaseSources().then(setSources, (e: Error) => setError(e.message))
  useEffect(() => {
    void reload()
  }, [])

  const run = async (action: () => Promise<unknown>) => {
    setError(null)
    try {
      await action()
    } catch (e) {
      setError((e as Error).message)
    }
    await reload()
  }

  const move = (index: number, step: -1 | 1) => {
    if (!sources) return
    const order = [...sources]
    const [item] = order.splice(index, 1)
    order.splice(index + step, 0, item)
    void run(() => Promise.all(order.map((s, i) => api.updatePurchaseSource(s.id, { sort_order: i }))))
  }

  return (
    <section className="panel purchase-settings">
      <h2>{t.buy.settingsTitle}</h2>
      <p className="muted small">{t.buy.settingsIntro}</p>
      {error && <p className="status error">{error}</p>}
      {sources?.map((source, i) => (
        <SourceEditor
          key={source.id}
          source={source}
          first={i === 0}
          last={i === sources.length - 1}
          onSave={(patch) => run(() => api.updatePurchaseSource(source.id, patch))}
          onMove={(step) => move(i, step)}
          onDelete={() =>
            window.confirm(t.buy.confirmDelete(source.name)) && run(() => api.deletePurchaseSource(source.id))
          }
        />
      ))}
      <div className="actions">
        <button
          className="button"
          onClick={() =>
            run(() =>
              api.createPurchaseSource({ name: t.buy.newSource, url_template: 'https://allegro.pl/uzytkownik/NAZWA?string={query}', enabled: false }),
            )
          }
        >
          {t.buy.addSource}
        </button>
      </div>
      <BasketSettings />
    </section>
  )
}

function SourceEditor({
  source,
  first,
  last,
  onSave,
  onMove,
  onDelete,
}: {
  source: PurchaseSource
  first: boolean
  last: boolean
  onSave: (patch: PurchaseSourcePatch) => Promise<void>
  onMove: (step: -1 | 1) => void
  onDelete: () => void
}) {
  const [name, setName] = useState(source.name)
  const [url, setUrl] = useState(source.url_template)
  const [suffix, setSuffix] = useState(source.query_suffix)
  const [note, setNote] = useState(source.note ?? '')
  const [threshold, setThreshold] = useState(source.free_delivery_threshold?.toString() ?? '')
  const [shipping, setShipping] = useState(source.shipping_cost?.toString() ?? '')
  const [testUrl, setTestUrl] = useState<string | null>(null)

  useEffect(() => {
    api.testPurchaseSource(source.id).then((r) => setTestUrl(r.url), () => setTestUrl(null))
  }, [source.id, source.url_template, source.query_suffix, source.query_mode])

  const dirty =
    name !== source.name ||
    url !== source.url_template ||
    suffix !== source.query_suffix ||
    note !== (source.note ?? '') ||
    threshold !== (source.free_delivery_threshold?.toString() ?? '') ||
    shipping !== (source.shipping_cost?.toString() ?? '')

  const save = () =>
    onSave({
      name,
      url_template: url,
      query_suffix: suffix,
      note: note.trim() || null,
      free_delivery_threshold: num(threshold),
      shipping_cost: num(shipping),
    })

  return (
    <div className={`source-editor ${source.enabled ? '' : 'disabled'}`}>
      <div className="source-row">
        <label className="checkbox">
          <input type="checkbox" checked={source.enabled} onChange={(e) => onSave({ enabled: e.target.checked })} />
          {t.buy.enabled}
        </label>
        <input className="input source-name" value={name} onChange={(e) => setName(e.target.value)} aria-label={t.buy.name} />
        <input
          className="input source-url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          aria-label={t.buy.url}
          placeholder={t.buy.url}
        />
      </div>
      <div className="source-row small">
        <label>
          {t.buy.mode}{' '}
          <select
            className="select small"
            value={source.query_mode}
            onChange={(e) => onSave({ query_mode: e.target.value as PurchaseSource['query_mode'] })}
          >
            <option value="name">{t.buy.modeName}</option>
            <option value="name_set">{t.buy.modeNameSet}</option>
          </select>
        </label>
        <label title={t.buy.suffixHint}>
          {t.buy.suffix}{' '}
          <input className="input narrow" value={suffix} onChange={(e) => setSuffix(e.target.value)} />
        </label>
        <label title={t.buy.overridesHint}>
          {t.buy.threshold}{' '}
          <input className="input narrow" inputMode="decimal" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
        </label>
        <label title={t.buy.overridesHint}>
          {t.buy.shipping}{' '}
          <input className="input narrow" inputMode="decimal" value={shipping} onChange={(e) => setShipping(e.target.value)} />
        </label>
        <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t.buy.note} aria-label={t.buy.note} />
      </div>
      <div className="source-row small">
        {dirty && (
          <button className="button primary small" onClick={save}>
            {t.common.save}
          </button>
        )}
        {testUrl && (
          <a className="button small" href={testUrl} target="_blank" rel="noreferrer" title={t.buy.testTitle}>
            {t.buy.test} ↗
          </a>
        )}
        <button className="link-button small" disabled={first} onClick={() => onMove(-1)}>
          ↑ {t.buy.moveUp}
        </button>
        <button className="link-button small" disabled={last} onClick={() => onMove(1)}>
          ↓ {t.buy.moveDown}
        </button>
        <button className="link-button danger small" onClick={onDelete}>
          {t.common.delete}
        </button>
      </div>
    </div>
  )
}

function BasketSettings() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  const fill = (s: Settings) => {
    setSettings(s)
    setForm({
      threshold: s.free_delivery_threshold?.toString() ?? '',
      currency: s.currency ?? 'PLN',
      shipping: s.default_shipping_cost?.toString() ?? '',
      ctShipping: s.cardtrader_shipping?.toString() ?? '',
      ctCurrency: s.cardtrader_shipping_currency ?? 'USD',
      ...Object.fromEntries(RATE_CURRENCIES.map((c) => [`rate${c}`, s.rates?.[c]?.toString() ?? ''])),
    })
  }
  useEffect(() => {
    api.purchaseSettings().then(fill, () => setSettings(null))
  }, [])

  if (!settings) return null
  const field = (key: string) => ({
    value: form[key] ?? '',
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value }),
  })
  const save = async () => {
    setMessage(null)
    const rates: Record<string, number> = { ...settings.rates }
    for (const c of RATE_CURRENCIES) {
      const value = num(form[`rate${c}`] ?? '')
      if (value) rates[c] = value
      else delete rates[c]
    }
    try {
      fill(
        await api.savePurchaseSettings({
          free_delivery_threshold: num(form.threshold) ?? 0,
          currency: form.currency || 'PLN',
          default_shipping_cost: num(form.shipping),
          cardtrader_shipping: num(form.ctShipping) ?? 0,
          cardtrader_shipping_currency: form.ctCurrency || 'USD',
          rates,
        }),
      )
      setMessage({ ok: true, text: t.buy.saved })
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    }
  }
  const currency = form.currency || 'PLN'

  return (
    <div className="basket-settings">
      <h3>{t.buy.basketSettings}</h3>
      <div className="form-grid">
        <label>
          {t.buy.globalThreshold}
          <span>
            <input className="input narrow" inputMode="decimal" {...field('threshold')} /> {currency}
          </span>
        </label>
        <p className="muted small">{t.buy.thresholdHint}</p>
        <label>
          {t.buy.currency}
          <input className="input narrow" {...field('currency')} />
        </label>
        <label>
          {t.buy.defaultShipping}
          <span>
            <input className="input narrow" inputMode="decimal" {...field('shipping')} /> {currency}
          </span>
        </label>
        <label>
          {t.buy.ctShipping}
          <span>
            <input className="input narrow" inputMode="decimal" {...field('ctShipping')} />{' '}
            <input className="input narrow" {...field('ctCurrency')} aria-label={t.buy.currency} />
          </span>
        </label>
        <span className="form-label">{t.buy.rates}</span>
        <span className="rates">
          {RATE_CURRENCIES.map((c) => (
            <label key={c}>
              {t.buy.rate(c, currency)}{' '}
              <input className="input narrow" inputMode="decimal" {...field(`rate${c}`)} />
            </label>
          ))}
        </span>
        <p className="muted small">{t.buy.ratesHint}</p>
      </div>
      <div className="actions">
        <button className="button primary" onClick={save}>
          {t.common.save}
        </button>
        {message && <span className={`status ${message.ok ? 'ok' : 'error'} small`}>{message.text}</span>}
      </div>
    </div>
  )
}
