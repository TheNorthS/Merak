/** Pure checks for backend source snapshots required by the frozen runtime. */

const assert = require('node:assert/strict')
const { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')
const {
  backendPythonSources, backendTemplates, backendSourceSnapshot, skillSources, sourceDigest, stageSources,
  verifyBundledSources,
} = require('./build-backend.js')

function put(root, relative, contents) {
  const target = path.join(root, relative)
  mkdirSync(path.dirname(target), { recursive: true })
  writeFileSync(target, contents)
  return target
}

test('staged source bytes preserve figure and simulation provenance', () => {
  const fixture = mkdtempSync(path.join(os.tmpdir(), 'merak-backend-source-test-'))
  try {
    put(fixture, 'pyproject.toml', '[project]\nname = "test"\n')
    put(fixture, 'requirements.lock', '# dependencies\n')
    put(fixture, 'scripts/merak_backend_entry.py', '# entry\n')
    put(fixture, 'scripts/build-backend.js', '// build\n')
    const figure = put(fixture, 'server/services/figure_delegate_budget.py', '# figure\n')
    const generator = put(fixture, 'server/services/simulation_benchmark.py', '# generator\n')
    put(fixture, 'server/tests/test_unused.py', '# must not bundle\n')
    const template = put(fixture, 'server/services/simulation_plot_templates/verify_bundle.py.tmpl', '# template\n')
    const skill = put(fixture, 'merak-skills/model-svg-figure/SKILL.md', '# skill\n')
    put(fixture, 'merak-skills/paper-write/templates/article.tex', '% template\n')

    const pythonFiles = backendPythonSources(fixture)
    assert.deepEqual(pythonFiles, [figure, generator])
    const stage = path.join(fixture, 'staging', '_internal')
    stageSources(pythonFiles, path.join(fixture, 'server'), path.join(stage, 'merak-source/server'))
    stageSources(skillSources(fixture), path.join(fixture, 'merak-skills'), path.join(stage, 'merak-skills'))
    stageSources(backendTemplates(fixture), path.join(fixture, 'server'), path.join(stage, 'server'))
    assert.throws(() => verifyBundledSources(stage, fixture), /verify_bundle\.py\.tmpl/)
    stageSources(backendSourceSnapshot(fixture), path.join(fixture, 'server'), path.join(stage, 'merak-source/server'))
    verifyBundledSources(stage, fixture)
    const mirror = path.join(stage, 'merak-source/server/services/simulation_plot_templates/verify_bundle.py.tmpl')
    assert.deepEqual(readFileSync(mirror), readFileSync(template))
    writeFileSync(mirror, '# changed template\n')
    assert.throws(() => verifyBundledSources(stage, fixture), /verify_bundle\.py\.tmpl/)
    writeFileSync(mirror, readFileSync(template))
    const runtimeTemplate = path.join(stage, 'server/services/simulation_plot_templates/verify_bundle.py.tmpl')
    rmSync(runtimeTemplate)
    assert.throws(() => verifyBundledSources(stage, fixture), /verify_bundle\.py\.tmpl/)
    writeFileSync(runtimeTemplate, readFileSync(template))
    assert.deepEqual(
      readFileSync(path.join(stage, 'merak-source/server/services/simulation_benchmark.py')),
      readFileSync(generator),
    )
    assert.deepEqual(
      readFileSync(path.join(stage, 'merak-skills/model-svg-figure/SKILL.md')),
      readFileSync(skill),
    )

    const before = sourceDigest(fixture)
    writeFileSync(path.join(fixture, 'requirements.lock'), '# changed dependencies\n')
    assert.notEqual(sourceDigest(fixture), before)
    const afterDependencies = sourceDigest(fixture)
    writeFileSync(figure, '# figure changed\n')
    assert.notEqual(sourceDigest(fixture), afterDependencies)
    const afterFigure = sourceDigest(fixture)
    writeFileSync(skill, '# skill changed\n')
    assert.notEqual(sourceDigest(fixture), afterFigure)
    assert.throws(
      () => verifyBundledSources(stage, fixture),
      /source snapshot is missing or changed/,
    )
  } finally {
    rmSync(fixture, { recursive: true, force: true })
  }
})
