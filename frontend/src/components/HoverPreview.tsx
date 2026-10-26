import type { ReactNode } from 'react'
import { CardImage } from './CardImage'

// Fixed size, about a pool card at 220% zoom.
export const PREVIEW_WIDTH = 300
const PREVIEW_HEIGHT = Math.round((PREVIEW_WIDTH * 680) / 488)
const INFO_HEIGHT = 160

export interface Hovered {
  id: string
  name: string
  x: number
  y: number
  hasImage: boolean
  width: number // of the hovered card on screen
}

/** The large card image next to the hovered card, with optional info under it. */
export function HoverPreview({ hovered, info, image = true }: { hovered: Hovered; info?: ReactNode; image?: boolean }) {
  // Prefer the right side of the hovered card; flip left when there is no room.
  const margin = 12
  let left = hovered.x + margin
  if (left + PREVIEW_WIDTH > window.innerWidth - margin) {
    left = Math.max(margin, hovered.x - hovered.width - PREVIEW_WIDTH - margin)
  }
  // Room for the info panel under the image.
  const height = (image ? PREVIEW_HEIGHT : 0) + (info ? INFO_HEIGHT : 0)
  const top = Math.min(Math.max(margin, hovered.y), window.innerHeight - height - margin)
  return (
    <div className="hover-preview" style={{ left, top, width: PREVIEW_WIDTH }}>
      {image && (
        <CardImage key={hovered.id} cardId={hovered.id} name={hovered.name} size="normal" hasImage={hovered.hasImage} />
      )}
      {info}
    </div>
  )
}
