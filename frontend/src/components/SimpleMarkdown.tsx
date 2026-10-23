import type { ReactNode } from 'react'

const REPO_URL = 'https://github.com/wjaros/mtg-manager'
// **bold**, `code`, [text](url), bare https:// links and #123 (a pull request).
const INLINE = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s)]+)|#(\d+)\b/g

/** github.com/…/pull/12 -> "#12", …/compare/v1...v2 -> "v1...v2"; other links as they are. */
function shortUrl(url: string): string {
  const pull = url.match(/\/pull\/(\d+)$/)
  if (pull) return `#${pull[1]}`
  const compare = url.match(/\/compare\/(.+)$/)
  return compare ? compare[1] : url
}

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const key = m.index
    if (m[1]) out.push(<strong key={key}>{m[1]}</strong>)
    else if (m[2]) out.push(<code key={key}>{m[2]}</code>)
    else if (m[3]) out.push(<a key={key} href={m[4]} target="_blank" rel="noreferrer">{m[3]}</a>)
    else if (m[5]) out.push(<a key={key} href={m[5]} target="_blank" rel="noreferrer">{shortUrl(m[5])}</a>)
    else out.push(<a key={key} href={`${REPO_URL}/pull/${m[6]}`} target="_blank" rel="noreferrer">#{m[6]}</a>)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/** The bit of Markdown release notes use: headings, paragraphs, lists, bold, code, links.
Rendered as elements (never as HTML), so notes from the network can't inject markup. */
export function SimpleMarkdown({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let list: string[] = []
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length) blocks.push(<p key={blocks.length}>{inline(paragraph.join(' '))}</p>)
    if (list.length)
      blocks.push(
        <ul key={blocks.length}>
          {list.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      )
    paragraph = []
    list = []
  }
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    const heading = line.match(/^#{1,6}\s+(.*)$/)
    const item = line.match(/^[-*+]\s+(.*)$/)
    if (!line) flush()
    else if (heading) {
      flush()
      blocks.push(<h4 key={blocks.length}>{inline(heading[1])}</h4>)
    } else if (item) {
      if (paragraph.length) flush()
      list.push(item[1])
    } else if (list.length) list[list.length - 1] += ` ${line}`
    else paragraph.push(line)
  }
  flush()
  return <div className="markdown">{blocks}</div>
}
