import test from 'node:test';
import assert from 'node:assert/strict';
import { runBulkAction } from '../src/lib/bulkActions.mjs';

test('partial failures continue, preserve API error and report progress without replaying successes', async () => {
  const visited = [];
  const progress = [];
  const result = await runBulkAction(['a', 'b', 'c'], async (id) => {
    visited.push(id);
    if (id === 'b') throw new Error('meeting_closed: وضعیت جلسه را بررسی کنید');
  }, (done) => progress.push(done));
  assert.deepEqual(visited, ['a', 'b', 'c']);
  assert.deepEqual(result.succeeded, ['a', 'c']);
  assert.deepEqual(result.failed, [{ id: 'b', message: 'meeting_closed: وضعیت جلسه را بررسی کنید' }]);
  assert.deepEqual(progress, [1, 2, 3]);
  const retried = [];
  await runBulkAction(result.failed.map((item) => item.id), async (id) => retried.push(id));
  assert.deepEqual(retried, ['b']);
});

test('executes at most one request at a time and handles empty selections', async () => {
  let active = 0;
  await runBulkAction(['a', 'b'], async () => {
    active++;
    assert.equal(active, 1);
    await Promise.resolve();
    active--;
  });
  assert.deepEqual(await runBulkAction([], () => assert.fail('must not execute')), { succeeded: [], failed: [] });
});
