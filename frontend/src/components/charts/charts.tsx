import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { ManaCost } from '../ManaCost'
import { t } from '../../i18n'

/*
 * Small hand-built SVG charts for deck statistics. Mark specs follow the dataviz guidance:
 * bars <= 24px with a 4px rounded data end and square baseline, 2px gaps between grouped
 * bars, hairline recessive grid, text in text tokens (never the series color),
 * per-mark hover tooltips, a legend for >= 2 series and a table view for every chart.
 */

export interface Series {
  key: string
  label: string
  color: string // CSS value, e.g. var(--series-u)
}

const BAR_MAX = 24
const GAP = 2
const RADIUS = 4

/** Rect with only the data end (top, or right for horizontal bars) rounded. */
function barPath(x: number, y: number, w: number, h: number, horizontal: boolean, rounded: boolean): string {
  const r = rounded ? Math.min(RADIUS, horizontal ? w : h, horizontal ? h / 2 : w / 2) : 0
  if (horizontal) {
    return `M${x},${y} h${w - r} a${r},${r} 0 0 1 ${r},${r} v${h - 2 * r} a${r},${r} 0 0 1 ${-r},${r} h${-(w - r)} z`
  }
  return `M${x},${y + h} v${-(h - r)} a${r},${r} 0 0 1 ${r},${-r} h${w - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${h - r} z`
}

function niceMax(value: number): number {
  if (value <= 4) return Math.max(value, 1)
  const step = value <= 10 ? 2 : value <= 25 ? 5 : value <= 50 ? 10 : 20
  return Math.ceil(value / step) * step
}

function ticks(max: number): number[] {
  const step = max <= 4 ? 1 : max <= 10 ? 2 : max <= 25 ? 5 : max <= 50 ? 10 : 20
  const result = []
  for (let v = 0; v <= max; v += step) result.push(v)
  return result
}

/** Width of the chart container, so SVG units equal CSS pixels (marks keep their specified size). */
function useWidth(fallback = 360) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.floor(entry.contentRect.width))))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

interface TooltipState {
  x: number
  y: number
  content: ReactNode
}

function Tooltip({ state }: { state: TooltipState | null }) {
  if (!state) return null
  return (
    <div className="chart-tooltip" style={{ left: state.x, top: state.y }} role="status">
      {state.content}
    </div>
  )
}

export function Legend({ series }: { series: Series[] }) {
  if (series.length < 2) return null
  return (
    <div className="chart-legend">
      {series.map((s) => (
        <span key={s.key} className="chart-legend-item">
          <span className="chart-swatch" style={{ background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  )
}

export function ChartTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <details className="chart-table">
      <summary>{t.stats.table}</summary>
      <table>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

// --- columns ---------------------------------------------------------------------

export interface Column {
  label: string
  value: number
  /** Breakdown shown in the tooltip, e.g. per mana color (keyed by mana symbol, not by hue). */
  detail?: { key: string; label: string; value: number }[]
}

/** Single-series columns with the value on the cap. */
export function Columns({
  columns,
  unit,
  axisLabel,
  height = 170,
}: {
  columns: Column[]
  unit: string
  axisLabel: string
  height?: number
}) {
  const [tip, setTip] = useState<TooltipState | null>(null)
  const [ref, width] = useWidth()
  const pad = { top: 18, right: 4, bottom: 22, left: 26 }
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom
  const max = niceMax(Math.max(...columns.map((c) => c.value), 1))
  const slot = plotW / columns.length
  const barW = Math.min(BAR_MAX, slot * 0.6)
  const y = (v: number) => pad.top + plotH - (v / max) * plotH

  return (
    <div className="chart" ref={ref} onMouseLeave={() => setTip(null)}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        className="chart-svg"
        role="img"
        aria-label={t.stats.chartBy(unit, axisLabel)}
      >
        {ticks(max).map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={pad.left - 6} y={y(t)} className="chart-axis" textAnchor="end" dominantBaseline="middle">
              {t}
            </text>
          </g>
        ))}
        {columns.map((col, i) => {
          const cx = pad.left + slot * i + slot / 2
          return (
            <g
              key={col.label}
              className="chart-hit"
              tabIndex={0}
              onMouseMove={(e) => {
                const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect()
                setTip({
                  x: e.clientX - box.left + 12,
                  y: e.clientY - box.top - 12,
                  content: (
                    <>
                      <strong>
                        {col.value} {unit}
                      </strong>{' '}
                      <span className="muted">
                        {axisLabel} {col.label}
                      </span>
                      {col.detail?.map((d) => (
                        <div key={d.key} className="chart-tooltip-row">
                          <ManaCost cost={`{${d.key}}`} />
                          <strong>{d.value}</strong> <span className="muted">{d.label}</span>
                        </div>
                      ))}
                    </>
                  ),
                })
              }}
            >
              <rect x={pad.left + slot * i} y={pad.top} width={slot} height={plotH} fill="transparent" />
              {col.value > 0 && (
                <>
                  <path
                    d={barPath(cx - barW / 2, y(col.value), barW, y(0) - y(col.value), false, true)}
                    fill="var(--series-1)"
                  />
                  <text x={cx} y={y(col.value) - 5} className="chart-value" textAnchor="middle">
                    {col.value}
                  </text>
                </>
              )}
              <text x={cx} y={height - 6} className="chart-axis" textAnchor="middle">
                {col.label}
              </text>
            </g>
          )
        })}
        <line x1={pad.left} x2={width - pad.right} y1={y(0)} y2={y(0)} className="chart-baseline" />
      </svg>
      <Tooltip state={tip} />
    </div>
  )
}

// --- horizontal bars --------------------------------------------------------------

export interface BarRow {
  label: string
  values: Record<string, number>
}

/** Horizontal bars, one row per category; several series are grouped within a row. */
export function HorizontalBars({ rows, series, unit }: { rows: BarRow[]; series: Series[]; unit: string }) {
  const [tip, setTip] = useState<TooltipState | null>(null)
  const [ref, width] = useWidth()
  const labelW = 96
  const valueW = 28
  const barH = series.length > 1 ? 10 : 14
  const rowH = series.length * barH + (series.length - 1) * GAP + 12
  const height = rows.length * rowH
  const max = Math.max(1, ...rows.flatMap((r) => series.map((s) => r.values[s.key] ?? 0)))
  const plotW = width - labelW - valueW

  return (
    <div className="chart" ref={ref} onMouseLeave={() => setTip(null)}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        className="chart-svg"
        role="img"
        aria-label={t.stats.chart(unit)}
      >
        <line x1={labelW} x2={labelW} y1={0} y2={height} className="chart-baseline" />
        {rows.map((row, i) => {
          const top = i * rowH + 6
          return (
            <g
              key={row.label}
              className="chart-hit"
              tabIndex={0}
              onMouseMove={(e) => {
                const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect()
                setTip({
                  x: e.clientX - box.left + 12,
                  y: e.clientY - box.top - 12,
                  content: (
                    <>
                      <span className="muted">{row.label}</span>
                      {series.map((s) => (
                        <div key={s.key} className="chart-tooltip-row">
                          {series.length > 1 && <span className="chart-line-key" style={{ background: s.color }} />}
                          <strong>{row.values[s.key] ?? 0}</strong>{' '}
                          <span className="muted">{series.length > 1 ? s.label : unit}</span>
                        </div>
                      ))}
                    </>
                  ),
                })
              }}
            >
              <rect x={0} y={i * rowH} width={width} height={rowH} fill="transparent" />
              <text x={labelW - 8} y={top + (rowH - 12) / 2} className="chart-axis" textAnchor="end" dominantBaseline="middle">
                {row.label}
              </text>
              {series.map((s, j) => {
                const v = row.values[s.key] ?? 0
                const w = (v / max) * plotW
                const by = top + j * (barH + GAP)
                return (
                  <g key={s.key}>
                    {v > 0 && <path d={barPath(labelW, by, Math.max(w, 2), barH, true, true)} fill={s.color} />}
                    <text x={labelW + w + 6} y={by + barH / 2} className="chart-value" dominantBaseline="middle">
                      {v}
                    </text>
                  </g>
                )
              })}
            </g>
          )
        })}
      </svg>
      <Tooltip state={tip} />
    </div>
  )
}

export function StatTile({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="stat-tile">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {note && <span className="stat-note">{note}</span>}
    </div>
  )
}
