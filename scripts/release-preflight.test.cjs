const test = require('node:test')
const assert = require('node:assert/strict')
const { checkAvailability } = require('./release-preflight.cjs')

test('unused version requires successful tag query and exact Release 404', () => {
  const calls = []
  const result = checkAvailability('0.1.2', 'TheNorthS/Merak', (command, args) => {
    calls.push([command, args])
    return command === 'git' ? { status: 0, stdout: '' } : { status: 1, stderr: 'gh: Not Found (HTTP 404)' }
  })
  assert.equal(result, 'v0.1.2')
  assert.equal(calls.length, 2)
  assert(calls[0][1].includes('refs/tags/v0.1.2'))
})

test('existing tag rejects before any release operation', () => {
  let calls = 0
  assert.throws(() => checkAvailability('0.1.1', 'TheNorthS/Merak', () => {
    calls += 1
    return { status: 0, stdout: 'old-commit\trefs/tags/v0.1.1\n' }
  }), /already exists/)
  assert.equal(calls, 1)
})

for (const reply of [{ status: 0, stdout: '{}' }, { status: 1, stderr: 'HTTP 403' },
  { status: 1, stderr: 'connection timed out' }, { error: new Error('missing gh') }]) {
  test(`release query fails closed: ${JSON.stringify(reply)}`, () => {
    assert.throws(() => checkAvailability('0.1.2', 'TheNorthS/Merak', command =>
      command === 'git' ? { status: 0, stdout: '' } : reply))
  })
}

test('tag query failure cannot mean unused version', () => {
  assert.throws(() => checkAvailability('0.1.2', 'TheNorthS/Merak', () => ({ status: 128, stdout: '' })), /Cannot query/)
})
