import { t } from '../i18n'
import { setTheme, THEME_CHOICES, useTheme, type ThemeChoice } from '../theme'

const LABEL: Record<ThemeChoice, string> = {
  system: t.settings.themeSystem,
  light: t.settings.themeLight,
  dark: t.settings.themeDark,
}

/** System (the default), light or dark. */
export function ThemeSettings() {
  const theme = useTheme()
  return (
    <>
      <div className="segmented" role="group" aria-label={t.settings.theme}>
        {THEME_CHOICES.map((c) => (
          <button key={c} className={c === theme ? 'on' : ''} aria-pressed={c === theme} onClick={() => setTheme(c)}>
            {LABEL[c]}
          </button>
        ))}
      </div>
      <span className="muted small">{t.settings.themeHint}</span>
    </>
  )
}
