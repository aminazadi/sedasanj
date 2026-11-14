/** Structural session equality, so a periodic refresh that changed nothing does not re-render consumers. */
export interface SessionLike {
  userId: string;
  tenantId: string;
  role: string;
  panelPermissions: string[] | null;
}

export function sameSession(a: SessionLike | null, b: SessionLike | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.userId !== b.userId || a.tenantId !== b.tenantId || a.role !== b.role) return false;
  if (a.panelPermissions === b.panelPermissions) return true;
  if (!a.panelPermissions || !b.panelPermissions) return false;
  return a.panelPermissions.length === b.panelPermissions.length
    && a.panelPermissions.every((item, index) => item === b.panelPermissions![index]);
}

/** Stable string key for a permission list, for hook dependency arrays. */
export function permissionsKey(permissions: string[] | null | undefined): string {
  return permissions ? permissions.join(",") : "*";
}
