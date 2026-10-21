import { useState } from 'react'
import { imageUrl, type ImageSize } from '../api/client'

interface Props {
  cardId: string
  name: string
  size?: ImageSize
  face?: number
  hasImage?: boolean
  className?: string
}

/** Card image from the backend cache, with a text placeholder while loading or when missing. */
export function CardImage({ cardId, name, size = 'normal', face = 0, hasImage = true, className = '' }: Props) {
  const [state, setState] = useState<'loading' | 'loaded' | 'error'>('loading')
  const showImage = hasImage && state !== 'error'

  return (
    <div className={`card-image ${state} ${className}`}>
      {showImage && (
        <img
          src={imageUrl(cardId, size, face)}
          alt={name}
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={() => setState('loaded')}
          onError={() => setState('error')}
        />
      )}
      {state !== 'loaded' && <span className="card-image-name">{name}</span>}
    </div>
  )
}
