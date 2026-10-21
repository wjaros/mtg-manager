import { useRef, useState, type PointerEvent } from 'react'
import { api, scanImageUrl, type Scan } from '../api/client'
import { t } from '../i18n'

type Region = [number, number, number, number]

interface Props {
  scan: Scan
  onChange: (scan: Scan) => void
  onError: (message: string) => void
}

/** A page scan: preview with the found cards numbered, and the manual grid fallback. */
export function PageScanHeader({ scan, onChange, onError }: Props) {
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [gridOpen, setGridOpen] = useState(false)
  const [rows, setRows] = useState(3)
  const [cols, setCols] = useState(3)
  const [region, setRegion] = useState<Region | null>(null)
  const [busy, setBusy] = useState(false)
  const drag = useRef<{ x: number; y: number } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const committed = scan.status === 'committed'

  const relative = (e: PointerEvent) => {
    const rect = box.current!.getBoundingClientRect()
    return {
      x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height)),
    }
  }

  const applyGrid = async () => {
    setBusy(true)
    try {
      onChange(await api.regridScan(scan.id, rows, cols, region ?? undefined))
      setGridOpen(false)
    } catch (e) {
      onError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-scan">
      <div
        className={`page-preview ${gridOpen ? 'selecting' : ''}`}
        ref={box}
        onPointerDown={(e) => {
          if (!gridOpen) return
          const p = relative(e)
          drag.current = p
          setRegion([p.x, p.y, p.x, p.y])
          e.currentTarget.setPointerCapture(e.pointerId)
        }}
        onPointerMove={(e) => {
          if (!drag.current) return
          const p = relative(e)
          const s = drag.current
          setRegion([Math.min(s.x, p.x), Math.min(s.y, p.y), Math.max(s.x, p.x), Math.max(s.y, p.y)])
        }}
        onPointerUp={() => {
          drag.current = null
          if (region && (region[2] - region[0] < 0.05 || region[3] - region[1] < 0.05)) setRegion(null)
        }}
      >
        <img
          src={scanImageUrl(scan.id)}
          alt={scan.original_name ?? t.scan.scan}
          draggable={false}
          onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
        />
        {size && (
          <svg viewBox={`0 0 ${size.w} ${size.h}`} className="page-overlay" preserveAspectRatio="none">
            {!gridOpen &&
              scan.items.map((item, i) => {
                const pts = item.corners.map(([x, y]) => `${x},${y}`).join(' ')
                const cx = item.corners.reduce((s, [x]) => s + x, 0) / 4
                const cy = item.corners.reduce((s, [, y]) => s + y, 0) / 4
                return (
                  <g key={item.id} className={`page-card ${item.status}`}>
                    <polygon points={pts} />
                    <circle cx={cx} cy={cy} r={size.w * 0.035} />
                    <text x={cx} y={cy} fontSize={size.w * 0.04} textAnchor="middle" dominantBaseline="central">
                      {i + 1}
                    </text>
                  </g>
                )
              })}
            {gridOpen && (
              <GridPreview
                region={region ?? [0, 0, 1, 1]}
                rows={rows}
                cols={cols}
                width={size.w}
                height={size.h}
              />
            )}
          </svg>
        )}
      </div>

      <div className="page-info">
        <strong>{scan.original_name ?? t.scan.scan}</strong>
        <span className="muted small">
          {t.scan.page(t.common.cards(scan.items.length))}
        </span>
        {!committed &&
          (gridOpen ? (
            <div className="grid-form">
              <p className="muted small">
                {t.scan.gridHelp}
              </p>
              <div className="form-row">
                <label>
                  {t.scan.rows}
                  <input className="input small qty-input" type="number" min={1} max={6} value={rows}
                    onChange={(e) => setRows(Math.min(6, Math.max(1, Number(e.target.value) || 1)))} />
                </label>
                <label>
                  {t.scan.columns}
                  <input className="input small qty-input" type="number" min={1} max={6} value={cols}
                    onChange={(e) => setCols(Math.min(6, Math.max(1, Number(e.target.value) || 1)))} />
                </label>
              </div>
              <div className="actions compact">
                <button className="button primary" onClick={applyGrid} disabled={busy}>
                  {busy ? t.importer.analyzing : t.scan.applyGrid}
                </button>
                {region && (
                  <button className="link-button" onClick={() => setRegion(null)}>
                    {t.scan.wholePage}
                  </button>
                )}
                <button className="link-button" onClick={() => { setGridOpen(false); setRegion(null) }}>
                  {t.common.cancel}
                </button>
              </div>
            </div>
          ) : (
            <button className="button" onClick={() => setGridOpen(true)}>
              {t.scan.gridButton}
            </button>
          ))}
      </div>
    </div>
  )
}

function GridPreview({ region, rows, cols, width, height }: {
  region: Region; rows: number; cols: number; width: number; height: number
}) {
  const [x0, y0, x1, y1] = region
  const lines = []
  for (let r = 1; r < rows; r++) {
    const y = (y0 + ((y1 - y0) * r) / rows) * height
    lines.push(<line key={`r${r}`} x1={x0 * width} x2={x1 * width} y1={y} y2={y} />)
  }
  for (let c = 1; c < cols; c++) {
    const x = (x0 + ((x1 - x0) * c) / cols) * width
    lines.push(<line key={`c${c}`} x1={x} x2={x} y1={y0 * height} y2={y1 * height} />)
  }
  return (
    <g className="grid-preview">
      <rect x={x0 * width} y={y0 * height} width={(x1 - x0) * width} height={(y1 - y0) * height} />
      {lines}
    </g>
  )
}
