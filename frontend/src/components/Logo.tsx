import { useId } from 'react'
import { t } from '../i18n'

/** The app's icon in the skin's colors (the design: Gemini's per-skin logos, which all map the same tokens to
 * the same parts), inline so its cards and die move on hover. */
export function LogoIcon({ size }: { size: number }) {
  const id = useId().replace(/:/g, '') // gradient ids unique per logo on the page
  const stop = (offset: string, token: string) => <stop offset={offset} style={{ stopColor: `var(${token})` }} />
  const accent = `url(#${id}-accent)`
  return (
    <svg className="logo-icon" viewBox="0 0 512 512" width={size} height={size} aria-hidden="true">
      <defs>
        <radialGradient id={`${id}-bg`} cx="50%" cy="50%" r="70%">
          {stop('0%', '--bg-hover')}
          {stop('100%', '--bg')}
        </radialGradient>
        <linearGradient id={`${id}-accent`} x1="0%" y1="0%" x2="100%" y2="100%">
          {stop('0%', '--text')}
          {stop('35%', '--accent')}
          {stop('100%', '--accent')}
        </linearGradient>
        <linearGradient id={`${id}-face`} x1="0%" y1="0%" x2="0%" y2="100%">
          {stop('0%', '--glow')}
          {stop('100%', '--bg-hover')}
        </linearGradient>
        <linearGradient id={`${id}-card-left`} x1="0%" y1="0%" x2="100%" y2="100%">
          {stop('0%', '--glow')}
          {stop('100%', '--bg-elevated')}
        </linearGradient>
        <linearGradient id={`${id}-card-right`} x1="0%" y1="0%" x2="100%" y2="100%">
          {stop('0%', '--accent')}
          {stop('100%', '--bg-elevated')}
        </linearGradient>
        <filter id={`${id}-glow`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="8" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>
      <rect width="512" height="512" rx="105" fill={`url(#${id}-bg)`} strokeWidth="8" style={{ stroke: 'var(--border)' }} />
      <path
        d="M256 36L446 146V366L256 476L66 366V146ZM256 36V160M66 146H446M66 146L160 366M446 146L352 366M66 366L256 410L446 366M256 410V476"
        fill="none"
        strokeWidth="6"
        strokeLinejoin="round"
        style={{ stroke: 'var(--border)' }}
      />
      <g stroke={accent} strokeWidth="12" strokeLinecap="round" strokeLinejoin="round">
        <path
          d="M 96,190 L 96,360 L 226,360 C 240,360 250,372 256,372 C 262,372 272,360 286,360 L 416,360 L 416,190"
          style={{ fill: 'var(--bg-elevated)' }}
        />
        <path
          d="M 118,172 C 172,172 226,188 256,215 C 286,188 340,172 394,172 L 394,340 C 340,340 286,350 256,368 C 226,350 172,340 118,340 Z"
          style={{ fill: 'var(--bg-hover)' }}
        />
      </g>
      <g stroke={accent} strokeWidth="7" strokeLinejoin="round">
        <g className="logo-card-left">
          <rect x="150" y="155" width="80" height="112" rx="10" transform="rotate(-16 190 211)" fill={`url(#${id}-card-left)`} />
        </g>
        <g className="logo-card-right">
          <rect x="282" y="155" width="80" height="112" rx="10" transform="rotate(16 322 211)" fill={`url(#${id}-card-right)`} />
        </g>
      </g>
      <g className="logo-die" filter={`url(#${id}-glow)`}>
        <polygon
          points="256,188 322,226 322,302 256,340 190,302 190,226"
          strokeWidth="10"
          strokeLinejoin="round"
          style={{ fill: 'var(--bg-elevated)', stroke: 'var(--glow)' }}
        />
        <polygon points="256,214 298,286 214,286" fill={`url(#${id}-face)`} strokeWidth="5" strokeLinejoin="round" style={{ stroke: 'var(--text)' }} />
        <path
          d="M256 188V214M190 226L256 214L322 226M190 226L214 286M322 226L298 286M190 302L214 286M322 302L298 286M256 340L214 286M256 340L298 286"
          fill="none"
          strokeWidth="5"
          strokeLinejoin="round"
          style={{ stroke: 'var(--text)' }}
        />
      </g>
      <path
        className="logo-sparkle"
        d="M256,118 Q256,148 286,148 Q256,148 256,178 Q256,148 226,148 Q256,148 256,118 Z"
        fill={accent}
      />
    </svg>
  )
}

/** The icon with the app's name: in a row (the sidebar) or stacked (the start screen). */
export function Logo({ size = 32, stacked = false }: { size?: number; stacked?: boolean }) {
  return (
    <div className={`logo ${stacked ? 'stacked' : ''}`}>
      <LogoIcon size={size} />
      <div className="logo-text">
        <div className="logo-name">
          <span className="logo-gold">MTG</span> Deck Manager
        </div>
        <div className="logo-tagline">{t.app.tagline}</div>
      </div>
    </div>
  )
}
