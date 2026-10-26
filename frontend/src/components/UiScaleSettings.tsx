import { t } from '../i18n'
import { setUiScale, UI_SCALES, useUiScale } from '../prefs'

/** Size of the whole interface: the window app zooms its web view; a browser has its own zoom. */
export function UiScaleSettings() {
  const { scale, native } = useUiScale()
  if (!native) return <p className="muted small">{t.settings.uiScaleBrowser}</p>
  return (
    <>
      <div className="segmented" role="group" aria-label={t.settings.uiScaleTitle}>
        {UI_SCALES.map((s) => (
          <button key={s} className={Math.abs(s - scale) < 0.001 ? 'on' : ''} onClick={() => void setUiScale(s)}>
            {Math.round(s * 100)}%
          </button>
        ))}
      </div>
      <p className="muted small">{t.settings.uiScaleHint}</p>
    </>
  )
}
