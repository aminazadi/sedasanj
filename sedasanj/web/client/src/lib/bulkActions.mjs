/** Execute sequentially to avoid flooding the processing queue; preserve failed IDs for retry. */
export async function runBulkAction(ids, execute, onProgress = () => {}) {
  const succeeded = [];
  const failed = [];
  for (const id of ids) {
    try {
      await execute(id);
      succeeded.push(id);
    } catch (error) {
      failed.push({ id, message: error instanceof Error ? error.message : "عملیات انجام نشد؛ دوباره تلاش کنید." });
    }
    onProgress(succeeded.length + failed.length);
  }
  return { succeeded, failed };
}
