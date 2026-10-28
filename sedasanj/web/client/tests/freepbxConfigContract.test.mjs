import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const sourcePath = new URL('../src/agentConfig.ts', import.meta.url);
const fixturePath = new URL('../../../../freepbx-module/tests/fixtures/freepbx-config.v1.json', import.meta.url);
const source = fs.readFileSync(sourcePath, 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
const module = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('FreePBX configuration matches the shared PHP contract fixture', () => {
  const actual = module.freePbxModuleConfig('https://api.sedasanj.ir', '123e4567-e89b-12d3-a456-426614174000', 'sk_live_test', 'sk_live_test_secret', 'gzip', '', '2026-10-28T00:00:00.000Z');
  assert.deepEqual(JSON.parse(actual), JSON.parse(fs.readFileSync(fixturePath, 'utf8')));
});

test('missed calls remain opt-in in generated FreePBX configuration', () => {
  const config = JSON.parse(module.freePbxModuleConfig('https://api.sedasanj.ir', '123e4567-e89b-12d3-a456-426614174000', 'sk_live_test', 'sk_live_test_secret', 'gzip', '', '2026-10-28T00:00:00.000Z'));
  assert.deepEqual(config.settings.missed_calls, { enabled: false, poll_interval_seconds: 30 });
});
