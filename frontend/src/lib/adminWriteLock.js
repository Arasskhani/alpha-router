import { useReadOnly } from "../context/ReadOnlyContext";
export const ADMIN_WRITE_LOCK_TITLE = "Read-only administrator — you cannot create, edit, or delete.";
/** True when the current admin session is read-only (RBAC). */
export function useAdminWriteLock() {
    const readOnly = useReadOnly();
    return {
        readOnly,
        writeLockProps: {
            disabled: readOnly,
            title: readOnly ? ADMIN_WRITE_LOCK_TITLE : undefined,
        },
    };
}
