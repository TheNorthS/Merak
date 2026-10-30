/** Pure backend startup decisions; process launching and I/O remain in backend.ts. */

import { existsSync, realpathSync } from 'fs'
import * as path from 'path'
import { PROBE_CODE } from '../../scripts/backend-probe.cjs'

export interface PythonCandidate {
  executable: string
  prefix: string[]
}

export type HealthClassification =
  | 'owned'
  | 'external-merak'
  | 'stale-owned'
  | 'foreign-merak'
  | 'none'

/** Check the interpreter and key dependencies without importing the application. */
export function buildProbeArgs(): string[] {
  return ['-B', '-c', PROBE_CODE]
}

/** Deduplicate PATH commands and absolute interpreters that resolve to one file. */
export function dedupePythonCandidates(
  candidates: PythonCandidate[],
  platform: string,
  pathEnv: string,
): PythonCandidate[] {
  const paths = platform === 'win32' ? path.win32 : path.posix
  const directories = pathEnv.split(platform === 'win32' ? ';' : ':').filter(Boolean)
  const seen = new Set<string>()
  const unique: PythonCandidate[] = []

  for (const candidate of candidates) {
    const executable = resolveExecutable(candidate.executable, directories, platform)
    const normalized = executable
      ? paths.normalize(executable)
      : candidate.executable
    const key = `${platform === 'win32' ? normalized.toLowerCase() : normalized}\0${candidate.prefix.join('\0')}`
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(candidate)
  }
  return unique
}

function resolveExecutable(
  executable: string,
  directories: string[],
  platform: string,
): string | null {
  const paths = platform === 'win32' ? path.win32 : path.posix
  const names = platform === 'win32' && !paths.extname(executable)
    ? [`${executable}.exe`, executable]
    : [executable]
  const hasPath = paths.isAbsolute(executable) || /[/\\]/.test(executable)
  const bases = hasPath ? [''] : directories
  for (const base of bases) {
    for (const name of names) {
      const full = base ? paths.join(base, name) : name
      if (!existsSync(full)) continue
      try {
        return realpathSync.native(full)
      } catch {
        return full
      }
    }
  }
  return null
}

/** Classify a health response without claiming ownership of another desktop. */
export function classifyHealth(
  data: unknown,
  ownerTokenSha256: string,
  installationSha256: string,
  ownerAlive: boolean,
): HealthClassification {
  if (typeof data !== 'object' || data === null) return 'none'
  const value = data as Record<string, unknown>
  if (value.service !== 'merak-ide-server' || value.status !== 'healthy') return 'none'
  if (
    typeof value.installation_sha256 !== 'string'
    || value.installation_sha256 !== installationSha256
  ) return 'foreign-merak'

  const token = value.desktop_owner_token_sha256
  if (token === ownerTokenSha256) return 'owned'
  if (!token) return 'external-merak'
  const pid = value.desktop_owner_pid
  if (Number.isSafeInteger(pid) && Number(pid) > 0 && !ownerAlive) return 'stale-owned'
  return 'foreign-merak'
}
