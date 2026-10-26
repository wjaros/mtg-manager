import { useEffect, useState } from 'react'
import { api, type DeckStats } from '../api/client'
import { ChartTable, Columns, HorizontalBars, Legend, StatTile, type Series } from './charts/charts'
import { RARITY_LABEL } from '../decks'
import { locale, t } from '../i18n'

// The curve is one series (magnitude per mana value). Seven mana-color series cannot all be
// told apart pairwise (palette validator: no assignment passes), so the color breakdown lives
// in the tooltip and the table, keyed by mana symbols rather than by hue.
const CURVE_GROUPS = [
  { key: 'W', label: t.filters.white },
  { key: 'U', label: t.filters.blue },
  { key: 'B', label: t.filters.black },
  { key: 'R', label: t.filters.red },
  { key: 'G', label: t.filters.green },
  { key: 'M', label: t.stats.multicolor },
  { key: 'C', label: t.stats.colorlessCards },
]
const COLOR_NAME: Record<string, string> = {
  W: t.filters.white,
  U: t.filters.blue,
  B: t.filters.black,
  R: t.filters.red,
  G: t.filters.green,
}
const SOURCE_SERIES: Series[] = [
  { key: 'pips', label: t.stats.pips, color: 'var(--series-1)' },
  { key: 'sources', label: t.stats.sources, color: 'var(--series-2)' },
]
const MANA_SERIES: Series[] = [
  { key: 'sources', label: t.stats.manaSources, color: 'var(--series-1)' },
  { key: 'needed', label: t.stats.manaNeeded, color: 'var(--series-2)' },
]
const SINGLE: Series[] = [{ key: 'value', label: t.stats.cards, color: 'var(--series-1)' }]
const TYPE_LABEL: Record<string, string> = {
  Creature: t.deck.typeCreature,
  Instant: t.deck.typeInstant,
  Sorcery: t.deck.typeSorcery,
  Enchantment: t.deck.typeEnchantment,
  Artifact: t.deck.typeArtifact,
  Planeswalker: t.deck.typePlaneswalker,
  Battle: t.deck.typeBattle,
  Land: t.deck.typeLand,
}
interface Props {
  deckId: number
  platform: 'paper' | 'arena'
  /** Changes whenever the deck's contents change, to refetch. */
  revision: string
}

export function DeckStatsPanel({ deckId, platform, revision }: Props) {
  const [stats, setStats] = useState<DeckStats | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.deckStats(deckId).then(
      (s) => !cancelled && setStats(s),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [deckId, revision])

  if (error) return <p className="status error">{error}</p>
  if (!stats) return <p className="muted">{t.stats.calculating}</p>
  if (stats.total === 0) return <p className="muted">{t.stats.empty}</p>

  const curveGroups = CURVE_GROUPS.filter((g) => stats.curve.some((b) => (b.by_color[g.key] ?? 0) > 0))
  // Colors the deck actually spends; 'any color' lands would otherwise add empty rows.
  const colorRows = stats.colors.filter((c) => c.pips > 0)
  const typeRows = Object.entries(stats.types).filter(([, n]) => n > 0)
  const rarityRows = Object.entries(stats.rarity)
  const categoryRows = Object.entries(stats.categories).sort((a, b) => b[1] - a[1])
  const functionRows = Object.entries(stats.functions ?? {})
  const userTagRows = Object.entries(stats.user_tags ?? {}) // most first
  const mana = stats.mana_base
  const bracket = stats.bracket
  const priceDate = stats.price.as_of ? new Date(stats.price.as_of).toLocaleDateString(locale) : null

  return (
    <div className="deck-stats">
      <div className="stat-tiles">
        <StatTile label={t.stats.cards} value={stats.total} note={t.stats.landsNote(stats.lands, stats.nonlands)} />
        <StatTile label={t.stats.averageMv} value={stats.average_mv?.toFixed(2) ?? '—'} note={t.stats.noLands} />
        <StatTile
          label={t.stats.estimatedPrice}
          value={`€${stats.price.eur.toFixed(2)}`}
          note={`$${stats.price.usd.toFixed(2)}${priceDate ? t.stats.pricesAsOf(priceDate) : ''}`}
        />
        {platform === 'paper' ? (
          <StatTile
            label={t.stats.missingCost}
            value={`€${stats.price.missing_eur.toFixed(2)}`}
            note={stats.price.missing_eur === 0 ? t.stats.haveAll : t.stats.outsideCollection}
          />
        ) : (
          <StatTile
            label={t.stats.wildcards}
            value={Object.values(stats.wildcards).reduce((a, b) => a + b, 0)}
            note={['mythic', 'rare', 'uncommon', 'common']
              .filter((r) => stats.wildcards[r])
              .map((r) => `${stats.wildcards[r]} ${r[0].toUpperCase()}`)
              .join(' · ')}
          />
        )}
      </div>

      <section className="chart-card">
        <h3 className="chart-title">{t.stats.curve}</h3>
        <p className="chart-subtitle">{t.stats.curveSubtitle}</p>
        <Columns
          columns={stats.curve.map((b) => ({
            label: b.mv,
            value: b.total,
            detail: curveGroups
              .filter((g) => (b.by_color[g.key] ?? 0) > 0)
              .map((g) => ({ key: g.key, label: g.label, value: b.by_color[g.key] })),
          }))}
          unit={t.stats.unitCards}
          axisLabel="MV"
        />
        <ChartTable
          head={['MV', t.stats.total, ...curveGroups.map((g) => g.label)]}
          rows={stats.curve.map((b) => [b.mv, b.total, ...curveGroups.map((g) => b.by_color[g.key] ?? 0)])}
        />
      </section>

      {colorRows.length > 0 && (
        <section className="chart-card">
          <h3 className="chart-title">{t.stats.colorsTitle}</h3>
          <p className="chart-subtitle">{t.stats.colorsSubtitle}</p>
          <Legend series={SOURCE_SERIES} />
          <HorizontalBars
            rows={colorRows.map((c) => ({
              label: COLOR_NAME[c.color],
              values: { pips: c.pips, sources: c.land_sources + c.other_sources },
            }))}
            series={SOURCE_SERIES}
            unit={t.stats.unitCards}
          />
          <ChartTable
            head={t.stats.colorHead}
            rows={colorRows.map((c) => [COLOR_NAME[c.color], c.pips, c.land_sources, c.other_sources])}
          />
        </section>
      )}

      {mana.colors.length > 0 && (
        <section className="chart-card">
          <h3 className="chart-title">{t.stats.manaTitle}</h3>
          <p className="chart-subtitle">{t.stats.manaSubtitle(Math.round(mana.target * 100))}</p>
          <Legend series={MANA_SERIES} />
          <HorizontalBars
            rows={mana.colors.map((c) => ({
              label: COLOR_NAME[c.color],
              values: { sources: c.sources, needed: c.needed ?? 0 },
            }))}
            series={MANA_SERIES}
            unit={t.stats.unitCards}
          />
          <ul className="mana-verdicts">
            {mana.colors.map((c) => (
              <li key={c.color} className={c.needed !== null && c.sources >= c.needed ? 'status ok' : 'status warn'}>
                <strong>{COLOR_NAME[c.color]}:</strong>{' '}
                {c.needed === null
                  ? t.stats.manaOutOfReach(c.name, c.pips, c.turn)
                  : c.sources >= c.needed
                    ? t.stats.manaEnough(c.sources, c.needed, c.name, c.pips, c.turn)
                    : t.stats.manaShort(c.sources, c.needed, c.name, c.pips, c.turn)}
              </li>
            ))}
          </ul>
          <div className="stat-tiles">
            {mana.land_drops.map((d) => (
              <StatTile
                key={d.turn}
                label={t.stats.landDrop(d.turn)}
                value={`${Math.round(d.chance * 100)}%`}
                note={t.stats.landDropNote}
              />
            ))}
          </div>
          <ChartTable
            head={t.stats.manaHead}
            rows={mana.colors.map((c) => [COLOR_NAME[c.color], c.sources, c.needed ?? '—', c.name, c.pips, c.turn])}
          />
        </section>
      )}

      {bracket && (
        <section className="chart-card">
          <h3 className="chart-title">{t.stats.bracketTitle}</h3>
          <p className="chart-subtitle">{t.stats.bracketSubtitle}</p>
          <div className="stat-tiles">
            <StatTile
              label={t.stats.bracketMinimum}
              value={bracket.minimum === 2 ? '1–2' : bracket.minimum}
              note={t.stats.bracketReason[bracket.minimum]}
            />
            <StatTile label={t.stats.gameChangers} value={bracket.game_changers.length} note={t.stats.gameChangersNote} />
            <StatTile label={t.stats.tutors} value={bracket.tutors} note={t.stats.tutorsNote} />
          </div>
          <dl className="bracket-cards">
            {(
              [
                [t.stats.gameChangers, bracket.game_changers],
                [t.stats.massLandDenial, bracket.mass_land_denial],
                [t.stats.extraTurns, bracket.extra_turns],
              ] as const
            )
              .filter(([, cards]) => cards.length > 0)
              .map(([label, cards]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{cards.map((c) => c.name).join(', ')}</dd>
                </div>
              ))}
          </dl>
          {bracket.extra_turns.length > 0 && <p className="muted">{t.stats.extraTurnsNote}</p>}
          <p className="muted">{t.stats.bracketCombos}</p>
        </section>
      )}

      {functionRows.length > 0 && (
        <section className="chart-card">
          <h3 className="chart-title">{t.stats.functionsTitle}</h3>
          <p className="chart-subtitle">{t.stats.functionsSubtitle}</p>
          <HorizontalBars
            rows={functionRows.map(([f, n]) => ({ label: t.functions[f] ?? f, values: { value: n } }))}
            series={SINGLE}
            unit={t.stats.unitCards}
          />
          <ChartTable head={[t.stats.function, t.stats.cards]} rows={functionRows.map(([f, n]) => [t.functions[f] ?? f, n])} />
        </section>
      )}

      {userTagRows.length > 0 && (
        <section className="chart-card">
          <h3 className="chart-title">{t.userTags.label}</h3>
          <p className="chart-subtitle">{t.stats.userTagsSubtitle}</p>
          <HorizontalBars
            rows={userTagRows.map(([tag, n]) => ({ label: tag, values: { value: n } }))}
            series={SINGLE}
            unit={t.stats.unitCards}
          />
          <ChartTable head={[t.userTags.label, t.stats.cards]} rows={userTagRows.map(([tag, n]) => [tag, n])} />
        </section>
      )}

      {categoryRows.length > 0 && (
        <section className="chart-card">
          <h3 className="chart-title">{t.stats.categories}</h3>
          <p className="chart-subtitle">{t.stats.categoriesSubtitle}</p>
          <HorizontalBars
            rows={categoryRows.map(([c, n]) => ({ label: c, values: { value: n } }))}
            series={SINGLE}
            unit={t.stats.unitCards}
          />
          <ChartTable head={[t.stats.category, t.stats.cards]} rows={categoryRows.map(([c, n]) => [c, n])} />
        </section>
      )}

      <div className="chart-pair">
        <section className="chart-card">
          <h3 className="chart-title">{t.stats.types}</h3>
          <p className="chart-subtitle">{t.stats.typesSubtitle}</p>
          <HorizontalBars
            rows={typeRows.map(([type, n]) => ({ label: TYPE_LABEL[type] ?? type, values: { value: n } }))}
            series={SINGLE}
            unit={t.stats.unitCards}
          />
          <ChartTable head={[t.stats.type, t.stats.cards]} rows={typeRows.map(([type, n]) => [TYPE_LABEL[type] ?? type, n])} />
        </section>
        <section className="chart-card">
          <h3 className="chart-title">{t.stats.rarity}</h3>
          <p className="chart-subtitle">{t.stats.raritySubtitle}</p>
          <HorizontalBars
            rows={rarityRows.map(([r, n]) => ({ label: RARITY_LABEL[r] ?? r, values: { value: n } }))}
            series={SINGLE}
            unit={t.stats.unitCards}
          />
          <ChartTable head={[t.stats.rarity, t.stats.cards]} rows={rarityRows.map(([r, n]) => [RARITY_LABEL[r] ?? r, n])} />
        </section>
      </div>
    </div>
  )
}
