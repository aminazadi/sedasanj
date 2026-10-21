export function isFreshRunSequence(previous, incoming) {
  return Number(incoming) > Number(previous || 0);
}

export function withConversationRunState(current, conversationId, runId) {
  if (runId === undefined) return current;
  const next = { ...current };
  if (runId === null) delete next[conversationId];
  else next[conversationId] = runId;
  return next;
}

export function orderUniqueRunEvents(replayed, buffered) {
  const bySequence = new Map();
  for (const event of [...(replayed || []), ...(buffered || [])]) {
    const sequence = Number(event.sequence);
    if (Number.isFinite(sequence) && sequence > 0 && !bySequence.has(sequence)) {
      bySequence.set(sequence, event);
    }
  }
  return [...bySequence.entries()]
    .sort(([first], [second]) => first - second)
    .map(([, event]) => event);
}

export function mergeSnapshotMessages(current, restored, completedDraftIds) {
  const restoredIds = new Set(restored.map((message) => message.id));
  return [
    ...restored,
    ...current.filter(
      (message) => message.id.startsWith("draft-")
        && !completedDraftIds.has(message.id)
        && !restoredIds.has(message.id),
    ),
  ];
}

export function reconcileAcceptedMessage(current, requestId, messageId) {
  const draftId = `draft-user-${requestId}`;
  if (current.some((message) => message.id === messageId)) {
    return current.filter((message) => message.id !== draftId);
  }
  return current.map((message) => message.id === draftId ? { ...message, id: messageId } : message);
}
