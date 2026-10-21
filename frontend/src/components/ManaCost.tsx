const COLORS = new Set(['W', 'U', 'B', 'R', 'G', 'C'])

/** Renders "{2}{W}{W} // {1}{U}" as small colored symbols. */
export function ManaCost({ cost }: { cost: string | null | undefined }) {
  if (!cost) return null
  const parts = cost.split(/(\{[^}]+\}|\s\/\/\s)/).filter((p) => p.trim())
  return (
    <span className="mana-cost" aria-label={cost}>
      {parts.map((part, i) => {
        if (part.trim() === '//') {
          return (
            <span key={i} className="mana-sep">
              //
            </span>
          )
        }
        const symbol = part.replace(/[{}]/g, '')
        // Hybrid / Phyrexian symbols (W/U, G/P) are colored by their first color.
        const color = COLORS.has(symbol[0]) ? symbol[0].toLowerCase() : 'generic'
        return (
          <span key={i} className={`mana mana-${color}`} title={part}>
            {symbol.replace('/', '')}
          </span>
        )
      })}
    </span>
  )
}
