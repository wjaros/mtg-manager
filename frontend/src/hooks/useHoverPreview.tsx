import { useCallback, useState, type MouseEvent, type ReactNode } from 'react'
import { HoverPreview, type Hovered } from '../components/HoverPreview'

/** Large card image following the hovered card (Arena-style preview). */
export function useHoverPreview(info?: (cardId: string) => ReactNode) {
  const [hovered, setHovered] = useState<Hovered | null>(null)

  const show = useCallback(
    (card: { id: string; name: string; image_faces: number } | null, event?: MouseEvent) => {
      if (!card || !event) {
        setHovered(null)
        return
      }
      const rect = event.currentTarget.getBoundingClientRect()
      setHovered({ id: card.id, name: card.name, x: rect.right, y: rect.top, hasImage: card.image_faces > 0 })
    },
    [],
  )

  const element = hovered ? <HoverPreview hovered={hovered} info={info?.(hovered.id)} /> : null
  return { show, element }
}
