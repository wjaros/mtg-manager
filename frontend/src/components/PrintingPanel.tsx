import { useEffect, useState } from 'react'
import {
  api,
  calibrationPdfUrl,
  duplexTestPdfUrl,
  type CalibrationResult,
  type Paper,
  type PrinterProfile,
  type PrintSettings,
} from '../api/client'
import { formatNumber, t } from '../i18n'

/** Settings › Printing: card size, printer profiles and the calibration wizard. */
export function PrintingPanel() {
  const [settings, setSettings] = useState<PrintSettings | null>(null)
  const [savedSize, setSavedSize] = useState(false)
  const [profiles, setProfiles] = useState<PrinterProfile[]>([])
  const [name, setName] = useState('')
  const [paper, setPaper] = useState<Paper>('a4')
  const [calibrating, setCalibrating] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = () => api.printerProfiles().then(setProfiles, (e: Error) => setError(e.message))
  useEffect(() => {
    api.printSettings().then(setSettings, (e: Error) => setError(e.message))
    reload()
  }, [])

  const run = async (action: () => Promise<unknown>) => {
    setError(null)
    try {
      await action()
      await reload()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const saveSize = async () => {
    if (!settings) return
    setError(null)
    try {
      setSettings(await api.savePrintSettings(settings))
      setSavedSize(true)
      setTimeout(() => setSavedSize(false), 2000)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const add = () =>
    run(async () => {
      const created = await api.createPrinterProfile(name.trim(), paper)
      setName('')
      setCalibrating(created.id)
    })

  return (
    <section className="panel printing-panel">
      <h2>{t.printing.title}</h2>
      <p className="muted small">{t.printing.intro}</p>

      {settings && (
        <div className="printing-size">
          <span>{t.printing.cardSize}</span>
          <label>
            {t.printing.width}{' '}
            <input
              className="input small"
              type="number"
              step={0.1}
              min={50}
              max={80}
              value={settings.card_w_mm}
              onChange={(e) => setSettings({ ...settings, card_w_mm: Number(e.target.value) })}
            />
          </label>
          <label>
            {t.printing.height}{' '}
            <input
              className="input small"
              type="number"
              step={0.1}
              min={70}
              max={110}
              value={settings.card_h_mm}
              onChange={(e) => setSettings({ ...settings, card_h_mm: Number(e.target.value) })}
            />
          </label>
          <button className="button" onClick={saveSize}>
            {savedSize ? t.printing.saved : t.printing.save}
          </button>
        </div>
      )}
      <p className="muted small">{t.printing.cardSizeNote}</p>

      <h3>{t.printing.profiles}</h3>
      {profiles.length === 0 && <p className="muted small">{t.printing.noProfiles}</p>}
      {profiles.map((p) => (
        <div key={p.id} className="printer-profile">
          <div className="printer-profile-row">
            <strong>{p.name}</strong>
            <span className="muted small">{p.paper === 'a4' ? 'A4' : 'Letter'}</span>
            <span className="muted small">
              {p.calibrated_at
                ? t.printing.scales(percent(1 / p.scale_x), percent(1 / p.scale_y))
                : t.printing.uncalibrated}
            </span>
            {p.is_default ? (
              <span className="badge">{t.printing.default}</span>
            ) : (
              <button className="link-button small" onClick={() => run(() => api.updatePrinterProfile(p.id, { is_default: true }))}>
                {t.printing.makeDefault}
              </button>
            )}
            <span className="spacer" />
            <button className="button" onClick={() => setCalibrating(calibrating === p.id ? null : p.id)}>
              {calibrating === p.id ? t.printing.close : t.printing.calibrate}
            </button>
            <button
              className="link-button danger"
              onClick={() => window.confirm(t.printing.confirmDelete(p.name)) && run(() => api.deletePrinterProfile(p.id))}
              aria-label={t.common.delete}
            >
              ×
            </button>
          </div>
          {calibrating === p.id && settings && (
            <>
              <CalibrationWizard profile={p} settings={settings} onCalibrated={reload} />
              <DuplexWizard profile={p} onSaved={reload} />
            </>
          )}
        </div>
      ))}

      <div className="printing-add">
        <input className="input" placeholder={t.printing.newName} value={name} onChange={(e) => setName(e.target.value)} />
        <select className="select small" value={paper} onChange={(e) => setPaper(e.target.value as Paper)}>
          <option value="a4">A4</option>
          <option value="letter">Letter</option>
        </select>
        <button className="button" onClick={add} disabled={!name.trim()}>
          {t.printing.add}
        </button>
      </div>
      {error && <p className="status error">{error}</p>}
    </section>
  )
}

/** "+1.2%" for a printer that prints 1.2% too large. */
function percent(printed: number): string {
  const diff = (printed - 1) * 100
  return `${diff >= 0 ? '+' : ''}${formatNumber(Number(diff.toFixed(2)))}%`
}

function CalibrationWizard({
  profile,
  settings,
  onCalibrated,
}: {
  profile: PrinterProfile
  settings: PrintSettings
  onCalibrated: () => void
}) {
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [left, setLeft] = useState('')
  const [top, setTop] = useState('')
  const [result, setResult] = useState<CalibrationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const nominalA = (settings.card_w_mm * 3).toFixed(1)
  const nominalB = (settings.card_h_mm * 3).toFixed(1)
  const num = (value: string) => (value.trim() ? Number(value.replace(',', '.')) : null)

  const save = async () => {
    setError(null)
    try {
      const r = await api.calibratePrinter(profile.id, {
        measured_a_mm: num(a) ?? 0,
        measured_b_mm: num(b) ?? 0,
        measured_left_mm: num(left),
        measured_top_mm: num(top),
      })
      setResult(r)
      onCalibrated()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="calibration">
      <p className="small">{t.printing.step1}</p>
      <a className="button" href={calibrationPdfUrl(profile.paper)} download>
        {t.printing.step1Link}
      </a>
      <p className="small">{t.printing.step2(nominalA, nominalB)}</p>
      <div className="calibration-inputs">
        {(
          [
            [t.printing.measuredA, a, setA],
            [t.printing.measuredB, b, setB],
            [t.printing.measuredLeft, left, setLeft],
            [t.printing.measuredTop, top, setTop],
          ] as const
        ).map(([label, value, set]) => (
          <label key={label}>
            {label}
            <input className="input small" inputMode="decimal" value={value} onChange={(e) => set(e.target.value)} />
          </label>
        ))}
        <button className="button primary" onClick={save} disabled={!num(a) || !num(b)}>
          {t.printing.compute}
        </button>
      </div>
      {result && (
        <p className={`status ${result.out_of_range ? 'warn' : 'ok'}`}>
          {result.out_of_range
            ? t.printing.outOfRange
            : t.printing.result(signed(result.difference_x_pct), signed(result.difference_y_pct))}
        </p>
      )}
      {error && <p className="status error">{error}</p>}
      {(result || profile.calibrated_at) && (
        <>
          <p className="small">{t.printing.step3}</p>
          <a className="button" href={calibrationPdfUrl(profile.paper, profile.id)} download>
            {t.printing.step3Link}
          </a>
        </>
      )}
    </div>
  )
}

function signed(pct: number): string {
  return `${pct >= 0 ? '+' : ''}${formatNumber(Number(pct.toFixed(2)))}%`
}

/** Two-sided printing: read how far the back lands off the front on the test page. Each test page
already includes the saved offset, so a reading is what is left and adds to it. */
function DuplexWizard({ profile, onSaved }: { profile: PrinterProfile; onSaved: () => void }) {
  const [duplex, setDuplex] = useState<'long' | 'short'>(profile.back_offset_duplex ?? 'long')
  const [x, setX] = useState('')
  const [y, setY] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const num = (value: string) => (value.trim() ? Number(value.replace(',', '.').replace('−', '-')) : 0)
  const current = profile.back_offset_duplex === duplex

  const save = async () => {
    setError(null)
    try {
      await api.saveBackOffset(profile.id, num(x), num(y), duplex)
      setX('')
      setY('')
      setSaved(true)
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="calibration">
      <strong className="small">{t.printing.duplexTitle}</strong>
      <label className="small">
        {t.printing.duplexMode}{' '}
        <select className="select small" value={duplex} onChange={(e) => setDuplex(e.target.value as 'long' | 'short')}>
          <option value="long">{t.print.duplexLong}</option>
          <option value="short">{t.print.duplexShort}</option>
        </select>
      </label>
      <p className="small">{t.printing.duplexStep1}</p>
      <a className="button" href={duplexTestPdfUrl(profile.paper, duplex, profile.id)} download>
        {t.printing.duplexLink}
      </a>
      <p className="small">{t.printing.duplexStep2}</p>
      <div className="calibration-inputs">
        <label>
          X (mm)
          <input className="input small" inputMode="decimal" placeholder="0" value={x} onChange={(e) => setX(e.target.value)} />
        </label>
        <label>
          Y (mm)
          <input className="input small" inputMode="decimal" placeholder="0" value={y} onChange={(e) => setY(e.target.value)} />
        </label>
        <button className="button primary" onClick={save} disabled={Number.isNaN(num(x)) || Number.isNaN(num(y))}>
          {t.printing.compute}
        </button>
      </div>
      <p className="muted small">
        {current
          ? t.printing.duplexCurrent(signedMm(profile.back_offset_x_mm), signedMm(profile.back_offset_y_mm))
          : t.printing.duplexNone}
      </p>
      {saved && <p className="status ok">{t.printing.duplexSaved}</p>}
      {error && <p className="status error">{error}</p>}
    </div>
  )
}

function signedMm(mm: number): string {
  return `${mm > 0 ? '+' : ''}${formatNumber(Number(mm.toFixed(2)))} mm`
}
