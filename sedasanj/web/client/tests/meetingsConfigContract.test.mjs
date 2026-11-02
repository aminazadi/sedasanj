import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/agentConfig.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
const module = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('Jalase Negar pairing file has exactly the contract keys', () => {
  const config = JSON.parse(module.jalaseNegarConfig('https://api.sedasanj.ir/', 'ABCD2345', '2026-11-01T10:15:00Z'));
  assert.deepEqual(config, {
    schema: 'sedasanj.jalase-negar.config',
    version: 1,
    server_url: 'https://api.sedasanj.ir',
    pairing_code: 'ABCD2345',
    expires_at: '2026-11-01T10:15:00Z',
  });
  assert.deepEqual(Object.keys(config), ['schema', 'version', 'server_url', 'pairing_code', 'expires_at']);
});

test('pairing file never carries a long-lived token', () => {
  const text = module.jalaseNegarConfig('https://api.sedasanj.ir', 'ABCD2345', '2026-11-01T10:15:00Z');
  assert.doesNotMatch(text, /sk_live_|token|secret|password/i);
});
