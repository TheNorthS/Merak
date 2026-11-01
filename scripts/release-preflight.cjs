/** Fail before verification/build when a release version is already occupied. */
const assert = require('node:assert/strict')
const { spawnSync } = require('node:child_process')

function checkAvailability(version, repository, execute = spawnSync) {
  assert.match(version, /^\d+\.\d+\.\d+$/)
  assert.match(repository, /^[\w.-]+\/[\w.-]+$/)
  const tag = `v${version}`
  const options = { encoding: 'utf8', timeout: 30000, windowsHide: true }
  const refs = execute('git', ['ls-remote', '--tags', 'origin', `refs/tags/${tag}`, `refs/tags/${tag}^{}`], options)
  assert(!refs.error && refs.status === 0, 'Cannot query remote tags; check repository access and retry')
  assert(!refs.stdout.trim(), `${tag} already exists. Preserve the published tag and choose a new version.`)
  const release = execute('gh', ['api', `repos/${repository}/releases/tags/${tag}`], options)
  assert(!release.error, 'Cannot query GitHub Release availability')
  if (release.status === 0) throw new Error(`${tag} already has a Release. Choose a new version.`)
  assert(/\(HTTP 404\)/.test(release.stderr || ''),
    'Cannot verify Release availability; authentication, network or API failure is not an unused version')
  return tag
}

if (require.main === module) {
  try {
    const tag = checkAvailability(require('../package.json').version, process.env.GH_REPO || '')
    console.log(`${tag} is available for a new release`)
  } catch (error) { console.error(error.message); process.exitCode = 1 }
}

module.exports = { checkAvailability }
