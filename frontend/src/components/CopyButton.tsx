import { useEffect, useState } from 'react'
import { copyText } from '../clipboard'
import { t } from '../i18n'

/** Small button copying a text (e.g. a card's name); shows ✓ for a moment after copying. */
export function CopyButton({ text, title }: { text: string; title: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')

  useEffect(() => {
    if (state === 'idle') return
    const timer = setTimeout(() => setState('idle'), 1500)
    return () => clearTimeout(timer)
  }, [state])

  return (
    <button
      className="copy-button"
      title={state === 'failed' ? t.common.clipboardUnavailable : title}
      aria-label={title}
      onClick={() => copyText(text).then(() => setState('copied'), () => setState('failed'))}
    >
      {state === 'copied' ? '✓' : '⧉'}
    </button>
  )
}
