import type { ReactNode } from 'react'
import { CardImage } from './CardImage'

const PREVIEW_WIDTH = 300
const PREVIEW_HEIGHT = Math.round((PREVIEW_WIDTH * 680) / 488)
const INFO_HEIGHT = 160

export interface Hovered {
  id: string
  name: string
  x: number
  y: number
  hasImage: boolean
}

/** The large card image next to the hovered card, with optional info under it. */
export function HoverPreview({ hovered, info }: { hovered: Hovered; info?: ReactNode }) {
  // Prefer the right side of the hovered card; flip left when there is no room.
  const margin = 12
  let left = hovered.x + margin
  if (left + PREVIEW_WIDTH > window.innerWidth - margin) {
    left = Math.max(margin, hovered.x - PREVIEW_WIDTH * 2 - margin)
  }
  // Room for the info panel under the image.
  const height = PREVIEW_HEIGHT + (info ? INFO_HEIGHT : 0)
  const top = Math.min(Math.max(margin, hovered.y), window.innerHeight - height - margin)
  return (
    <div className="hover-preview" style={{ left, top, width: PREVIEW_WIDTH }}>
      <CardImage key={hovered.id} cardId={hovered.id} name={hovered.name} size="normal" hasImage={hovered.hasImage} />
      {info}
    </div>
  )
}
