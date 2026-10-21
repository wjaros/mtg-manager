import { useEffect, useState, type FormEvent } from 'react'
import { api, type Location, type LocationKind } from '../api/client'
import { t } from '../i18n'

const KIND_LABEL: Record<LocationKind, string> = {
  deck: t.locations.kindDeck,
  binder: t.locations.kindBinder,
  box: t.locations.kindBox,
  other: t.locations.kindOther,
}

interface Props {
  onOpen: (locationId: number) => void
}

export function LocationsView({ onOpen }: Props) {
  const [locations, setLocations] = useState<Location[] | null>(null)
  const [name, setName] = useState('')
  const [kind, setKind] = useState<LocationKind>('box')
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    api.locations().then(setLocations, (e: Error) => setError(e.message))
  }, [version])

  const run = async (action: () => Promise<unknown>) => {
    setError(null)
    try {
      await action()
      setVersion((v) => v + 1)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const create = (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    run(() => api.createLocation(name.trim(), kind)).then(() => setName(''))
  }

  return (
    <div className="view locations-view">
      <form className="panel" onSubmit={create}>
        <h2>{t.locations.newLocation}</h2>
        <div className="form-row">
          <label>
            {t.locations.name}
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={t.locations.namePlaceholder} />
          </label>
          <label>
            {t.locations.kind}
            <select className="select" value={kind} onChange={(e) => setKind(e.target.value as LocationKind)}>
              {(Object.keys(KIND_LABEL) as LocationKind[]).map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="actions">
          <button className="button primary" type="submit" disabled={!name.trim()}>
            {t.common.add}
          </button>
        </div>
      </form>
      {error && <p className="status error">{error}</p>}

      {locations === null ? (
        <p className="muted">{t.common.loading}</p>
      ) : locations.length === 0 ? (
        <p className="muted">{t.locations.empty}</p>
      ) : (
        <table className="items-table locations-table">
          <thead>
            <tr>
              <th>{t.locations.name}</th>
              <th>{t.locations.kind}</th>
              <th className="num">{t.locations.cardsColumn}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {locations.map((loc) => (
              <tr key={loc.id}>
                <td>
                  <button className="link-button plain" onClick={() => onOpen(loc.id)}>
                    {loc.name}
                  </button>
                </td>
                <td className="muted">{KIND_LABEL[loc.kind]}</td>
                <td className="num">{loc.card_count}</td>
                <td className="nowrap">
                  <button
                    className="link-button"
                    onClick={() => {
                      const next = window.prompt(t.locations.renamePrompt, loc.name)?.trim()
                      if (next && next !== loc.name) run(() => api.updateLocation(loc.id, { name: next }))
                    }}
                  >
                    {t.locations.rename}
                  </button>
                  <button
                    className="link-button danger"
                    onClick={() => {
                      if (
                        window.confirm(t.locations.confirmDelete(loc.name, loc.card_count))
                      ) {
                        run(() => api.deleteLocation(loc.id))
                      }
                    }}
                  >
                    {t.common.delete}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
