import type { ValidationIssue, ValidationResult } from '../api/client'
import { t } from '../i18n'

const ICON = { error: '✗', warning: '⚠', info: 'ℹ' } as const

/** Format rule problems (errors) and advice (warnings, info) for the deck. */
export function ValidationPanel({ result }: { result: ValidationResult | null }) {
  if (!result) return null
  const errors = result.issues.filter((i) => i.severity === 'error')
  if (result.issues.length === 0) {
    return <p className="validation-ok">{t.panels.validOk}</p>
  }
  return (
    <div className="validation">
      <p className={errors.length ? 'validation-summary error' : 'validation-ok'}>
        {errors.length ? t.panels.formatErrors(errors.length) : t.panels.validOk}
      </p>
      <ul className="validation-issues">
        {result.issues.map((issue: ValidationIssue) => (
          <li key={issue.code + issue.message} className={`issue ${issue.severity}`}>
            <span className="issue-icon" aria-label={issue.severity}>
              {ICON[issue.severity]}
            </span>
            <span>{issue.message}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
