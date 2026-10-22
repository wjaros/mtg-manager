import { ZOOM_LEVELS } from '../hooks/useZoom'
import { t } from '../i18n'

/** − 100% + : smaller / default / larger cards. */
export function ZoomControl({ zoom, onChange }: { zoom: number; onChange: (zoom: number) => void }) {
  const index = ZOOM_LEVELS.indexOf(zoom)
  return (
    <span className="zoom-control" role="group" aria-label={t.common.zoom}>
      <button onClick={() => onChange(ZOOM_LEVELS[index - 1])} disabled={index <= 0} title={t.common.zoomOut}>
        −
      </button>
      <button className="zoom-value" onClick={() => onChange(1)} title={t.common.zoomReset}>
        {Math.round(zoom * 100)}%
      </button>
      <button
        onClick={() => onChange(ZOOM_LEVELS[index + 1])}
        disabled={index >= ZOOM_LEVELS.length - 1}
        title={t.common.zoomIn}
      >
        +
      </button>
    </span>
  )
}
