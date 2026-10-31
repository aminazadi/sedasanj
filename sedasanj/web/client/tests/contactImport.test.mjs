import test from 'node:test';
import assert from 'node:assert/strict';
import { csvRecords, csvCells, importContacts } from '../src/lib/contactImport.mjs';

test('CSV records preserve quoted newlines, escaped quotes and chunk boundaries', async () => {
  const text = 'name,phone,notes\r\n"A","09121234567","' + 'x'.repeat(65536) + '\n""quoted"""\r\nB,123,ok';
  const records = [];
  for await (const record of csvRecords(new Blob([text]))) records.push(record);
  assert.equal(records.length, 3);
  assert.match(csvCells(records[1].text, ',')[2], /\n"quoted"/);
});

test('large imports use sequential batches and preserve duplicate semantics', async () => {
  const file = new Blob(['name,phone\n', ...Array.from({length: 501}, (_, i) => `A,${1000+i}\n`), 'Again,1000\n']);
  let calls = 0, active = 0;
  const progress = [];
  const report = await importContacts(file, 'update', false, async body => {
    assert.equal(active++, 0);
    const lines = (await body.get('file').text()).trim().split('\n').slice(1);
    assert.ok(lines.length <= 250);
    calls++; active--;
    return {total_rows: lines.length, created: lines.length, updated: 0, skipped: 0, error_count: 0, errors: [], accepted_numbers: lines.map(l => l.split(',')[1])};
  }, p => progress.push(p));
  assert.equal(calls, 3);
  assert.equal(report.created, 501);
  assert.equal(report.total_rows, 502);
  assert.equal(report.error_count, 1);
  assert.equal(report.errors[0].row, 503);
  assert.equal(progress.at(-1), 100);
});

test('failed batch stops processing without claiming completion', async () => {
  const progress = [];
  await assert.rejects(importContacts(new Blob(['name,phone\nA,123\n']), 'skip', true, async () => { throw new Error('offline'); }, p => progress.push(p)), /offline/);
  assert.ok(!progress.includes(100));
});

test('rate-limit errors propagate immediately without a countdown or automatic retry', async () => {
  const error = Object.assign(new Error('rate limited'), { status: 429 });
  const progress = [];
  let calls = 0;
  await assert.rejects(importContacts(new Blob(['name,phone\nA,123\n']), 'skip', true, async () => {
    calls++;
    throw error;
  }, (percent, message) => progress.push({ percent, message })), candidate => candidate === error);
  assert.equal(calls, 1);
  assert.equal(progress.length, 1);
  assert.equal(progress[0].percent, 0);
});
