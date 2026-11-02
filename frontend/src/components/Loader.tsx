import { t } from '../i18n'

/** A turning d20 (the favicon's, in the skin's colors) while a view loads. */
export function Loader({ label = t.common.loading }: { label?: string }) {
  return (
    <div className="loader" role="status">
      <svg viewBox="0 0 100 100" width={48} height={48} aria-hidden="true">
        <polygon
          points="50,6 90,28 90,72 50,94 10,72 10,28"
          strokeWidth="4"
          strokeLinejoin="round"
          style={{ fill: 'var(--bg-elevated)', stroke: 'var(--accent)' }}
        />
        <polygon
          points="50,20 76,66 24,66"
          fillOpacity="0.6"
          strokeWidth="3"
          strokeLinejoin="round"
          style={{ fill: 'var(--glow)', stroke: 'var(--text)' }}
        />
        <path d="M50 6V20M10 28L24 66M90 28L76 66M50 94L24 66M50 94L76 66" strokeWidth="2.5" style={{ stroke: 'var(--text)' }} />
      </svg>
      <span>{label}</span>
    </div>
  )
}
