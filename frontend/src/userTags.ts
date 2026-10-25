import { api } from './api/client'
import { t } from './i18n'

/** Edit the user's own tags on a card in a prompt (comma-separated, the tags in use as a hint), like
a deck card's category. Resolves to the tags as stored, or null when cancelled. */
export async function editUserTags(card: { id: string; name: string }): Promise<string[] | null> {
  const [detail, used] = await Promise.all([api.card(card.id), api.userTags()])
  const value = window.prompt(
    t.userTags.prompt(card.name, used.map((u) => u.tag).join(', ')),
    (detail.user_tags ?? []).join(', '),
  )
  if (value === null) return null
  return api.updateUserTags(card.id, value.split(','))
}

/** From a menu: only a failure is shown. */
export function editUserTagsFromMenu(card: { id: string; name: string }, onChange?: (tags: string[]) => void): void {
  editUserTags(card).then(
    (tags) => tags && onChange?.(tags),
    (e: Error) => window.alert(e.message),
  )
}
