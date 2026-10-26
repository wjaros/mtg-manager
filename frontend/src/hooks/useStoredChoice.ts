import { useState } from 'react'
import { getPref, setPref } from '../prefs'

/** One of `choices`, remembered under `key` (`fallback` when nothing valid is stored). */
export function useStoredChoice<T extends string>(key: string, choices: readonly T[], fallback: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => choices.find((c) => c === getPref(key)) ?? fallback)
  const update = (next: T) => {
    setValue(next)
    void setPref(key, next)
  }
  return [value, update]
}
