import { useCallback, useState, type MouseEvent, type ReactNode } from 'react'
import { HoverPreview, PREVIEW_WIDTH, type Hovered } from '../components/HoverPreview'

/** Large card image following the hovered card (Arena-style preview). Without `image` (cards already
shown large), only the info is shown, and nothing when there is no info. */
export function useHoverPreview(info?: (cardId: string) => ReactNode, image = true) {
  const [hovered, setHovered] = useState<Hovered | null>(null)

  const show = useCallback(
    (card: { id: string; name: string; image_faces: number } | null, event?: MouseEvent) => {
      if (!card || !event) {
        setHovered(null)
        return
      }
      const rect = event.currentTarget.getBoundingClientRect()
      setHovered({
        id: card.id,
        name: card.name,
        x: rect.right,
        y: rect.top,
        hasImage: card.image_faces > 0,
        width: rect.width,
      })
    },
    [],
  )

  // A card shown about as large as the preview (big screen, high zoom) needs no enlarged copy.
  const withImage = image && !!hovered && hovered.width < PREVIEW_WIDTH * 0.85
  const element =
    hovered && (withImage || info) ? (
      <HoverPreview hovered={hovered} info={info?.(hovered.id)} image={withImage} />
    ) : null
  return { show, element }
}
