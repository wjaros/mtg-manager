import { useEffect, useState } from 'react'
import { t } from '../i18n'
import {
  BUILT_IN,
  chooseSkin,
  CLASSIC,
  deleteSkin,
  MANA_SKIN,
  manaSkin,
  parseSkin,
  previewSkin,
  saveSkin,
  setSkinByDeck,
  SKIN_GROUPS,
  skinJson,
  skinTokens,
  useSkins,
  type Skin,
  type SkinGroup,
  type StoredSkin,
} from '../skins'
import { useTheme } from '../theme'
import { ManaCost } from './ManaCost'

// The classic skin's swatch: index.css's own :root tokens (bg, panel, accent, glow).
const CLASSIC_SWATCH = {
  dark: ['#0f1218', '#171b24', '#d6a842', '#d6a842'],
  light: ['#f3f4f6', '#ffffff', '#8f6206', '#8f6206'],
}

const GROUP_LABEL: Record<SkinGroup | 'own', string> = {
  basic: t.skins.groupBasic,
  mono: t.skins.groupMono,
  guild: t.skins.groupGuild,
  shard: t.skins.groupShard,
  wedge: t.skins.groupWedge,
  own: t.skins.groupOwn,
}

interface Editing {
  id: string | null // null: a new skin
  skin: Skin
  json: string
  error: string | null
}

function swatch(skin: Skin | null, mode: 'dark' | 'light'): string[] {
  if (!skin) return CLASSIC_SWATCH[mode]
  const tokens = skinTokens(skin, mode)
  return [tokens['--bg'], tokens['--bg-elevated'], tokens['--accent'], tokens['--glow']]
}

/** Choose a skin, or make one: from a deck's mana colors, sliders and color pickers, or pasted JSON. */
export function SkinSettings() {
  const { id, custom, byDeck } = useSkins()
  useTheme() // swatches follow light / dark chosen in Settings
  const mode = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
  const [editing, setEditing] = useState<Editing | null>(null)
  const [open, setOpen] = useState(false) // all skins shown; folded it is the chosen one only

  useEffect(() => {
    previewSkin(editing && !editing.error ? editing.skin : null)
  }, [editing])
  useEffect(() => () => previewSkin(null), [])

  const edit = (skin: Skin, skinId: string | null) =>
    setEditing({ id: skinId, skin, json: skinJson(skin), error: null })
  const change = (patch: Partial<Skin>) =>
    setEditing((prev) => prev && { ...prev, skin: { ...prev.skin, ...patch }, json: skinJson({ ...prev.skin, ...patch }), error: null })
  const mana = (colors: string[]) => {
    if (colors.length) change(manaSkin(colors))
  }
  const ownSkin = custom.find((s) => s.id === id) ?? null
  const chosen = ownSkin ?? BUILT_IN.find((s) => s.id === id) ?? null
  const base = chosen ?? BUILT_IN[0]

  const tile = (skin: StoredSkin | null) => {
    const skinKey = skin?.id ?? CLASSIC
    const [bg, panel, accent, glow] = swatch(skin, mode)
    return (
      <button
        key={skinKey}
        className={`skin-tile ${skinKey === id ? 'on' : ''}`}
        role="radio"
        aria-checked={skinKey === id}
        onClick={() => {
          if (!open) return setOpen(true)
          setEditing(null)
          chooseSkin(skinKey)
        }}
      >
        <span className="skin-swatch" style={{ background: bg }}>
          <span style={{ background: panel }} />
          <span style={{ background: accent }} />
          <span style={{ background: glow }} />
        </span>
        <span className="skin-name">
          {skin?.name ?? t.skins.classic}
          {skin?.mana && <ManaCost cost={[...skin.mana].map((c) => `{${c}}`).join('')} />}
        </span>
      </button>
    )
  }

  return (
    <div className="skin-settings">
      {open ? (
        <>
          {[...SKIN_GROUPS, 'own' as const].map((group) => {
            const skins: (StoredSkin | null)[] =
              group === 'own' ? custom : [...(group === 'basic' ? [null] : []), ...BUILT_IN.filter((b) => b.group === group)]
            if (!skins.length) return null
            return (
              <div key={group} className="skin-group">
                <h3 className="skin-group-title">{GROUP_LABEL[group]}</h3>
                <div className="skin-list" role="radiogroup" aria-label={GROUP_LABEL[group]}>
                  {skins.map((skin) => tile(skin))}
                </div>
              </div>
            )
          })}
          <button className="link-button small skin-fold" onClick={() => setOpen(false)}>
            {t.skins.fold}
          </button>
        </>
      ) : (
        <div className="skin-list skin-folded">
          {tile(chosen)}
          <button className="button" onClick={() => setOpen(true)}>
            {t.skins.change(BUILT_IN.length + custom.length + 1)}
          </button>
        </div>
      )}
      <label className="checkbox skin-by-deck">
        <input type="checkbox" checked={byDeck} onChange={(e) => setSkinByDeck(e.target.checked)} />
        {t.skins.byDeck}
        <span className="muted small">{t.skins.byDeckHint}</span>
      </label>
      <div className="actions compact">
        <button
          className="button"
          onClick={() => edit({ ...parseSkin(skinJson(base)), name: t.skins.defaultName }, null)}
        >
          {t.skins.create}
        </button>
        {ownSkin && (
          <>
            <button className="button" onClick={() => edit(parseSkin(skinJson(ownSkin)), ownSkin.id)}>
              {t.skins.edit}
            </button>
            <button
              className="button"
              onClick={() => {
                if (window.confirm(t.skins.confirmDelete(ownSkin.name))) deleteSkin(ownSkin.id)
              }}
            >
              {t.common.delete}
            </button>
          </>
        )}
      </div>

      {editing && (
        <div className="skin-editor">
          <label>
            {t.skins.name}
            <input className="input" value={editing.skin.name} maxLength={40} onChange={(e) => change({ name: e.target.value })} />
          </label>
          <div className="skin-field">
            <span>{t.skins.fromColors}</span>
            <ManaPicker onPick={mana} />
            <span className="muted small">{t.skins.fromColorsHint}</span>
          </div>
          <label className="skin-field">
            <span>{t.skins.hue}</span>
            <input
              type="range"
              className="skin-hue"
              min={0}
              max={360}
              value={Math.round(editing.skin.hue)}
              onChange={(e) => change({ hue: Number(e.target.value) })}
            />
          </label>
          <label className="skin-field">
            <span>{t.skins.tint}</span>
            <input
              type="range"
              min={0}
              max={100}
              value={Math.round(editing.skin.tint * 100)}
              onChange={(e) => change({ tint: Number(e.target.value) / 100 })}
            />
          </label>
          <label className="skin-field">
            <span>{t.skins.accent}</span>
            <input type="color" value={editing.skin.accent} onChange={(e) => change({ accent: e.target.value })} />
          </label>
          <label className="skin-field">
            <span>{t.skins.glow}</span>
            <input type="color" value={editing.skin.glow} onChange={(e) => change({ glow: e.target.value })} />
          </label>
          <label>
            {t.skins.json}
            <textarea
              className="input skin-json"
              value={editing.json}
              spellCheck={false}
              onChange={(e) => {
                const json = e.target.value
                try {
                  setEditing({ ...editing, skin: parseSkin(json), json, error: null })
                } catch (err) {
                  setEditing({ ...editing, json, error: (err as Error).message })
                }
              }}
            />
          </label>
          <p className="muted small">{t.skins.jsonHint}</p>
          {editing.error && <p className="status error">{editing.error}</p>}
          <div className="actions">
            <button
              className="button primary"
              disabled={!!editing.error || !editing.skin.name.trim()}
              onClick={() => {
                saveSkin(editing.skin, editing.id ?? undefined)
                setEditing(null)
              }}
            >
              {t.skins.save}
            </button>
            <button className="button" onClick={() => setEditing(null)}>
              {t.common.cancel}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Up to three mana colors, in the order clicked. */
function ManaPicker({ onPick }: { onPick: (colors: string[]) => void }) {
  const [colors, setColors] = useState<string[]>([])
  return (
    <div className="color-toggles" role="group" aria-label={t.skins.fromColors}>
      {Object.keys(MANA_SKIN).map((c) => (
        <button
          key={c}
          className={`color-toggle ${colors.includes(c) ? 'on' : ''}`}
          onClick={() => {
            const next = colors.includes(c) ? colors.filter((x) => x !== c) : [...colors, c].slice(-3)
            setColors(next)
            onPick(next)
          }}
        >
          <ManaCost cost={`{${c}}`} />
        </button>
      ))}
    </div>
  )
}
