export interface SequencedRunEvent {
  sequence: number;
  [key: string]: unknown;
}

export function isFreshRunSequence(previous: number | undefined, incoming: number): boolean;
export function withConversationRunState(
  current: Record<string, string | null>,
  conversationId: string,
  runId: string | null | undefined,
): Record<string, string | null>;
export function orderUniqueRunEvents<T extends SequencedRunEvent>(
  replayed: T[],
  buffered: T[],
): T[];
export function mergeSnapshotMessages<T extends { id: string }>(
  current: T[],
  restored: T[],
  completedDraftIds: Set<string>,
): T[];
export function reconcileAcceptedMessage<T extends { id: string }>(
  current: T[],
  requestId: string,
  messageId: string,
): T[];
