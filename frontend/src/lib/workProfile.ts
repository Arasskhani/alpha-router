/**
 * The directory fields this account carries into non-private chats.
 *
 * Its own module and its own endpoint on purpose. The Work profile screen
 * used to read these out of the memories bundle, which meant it could not
 * open unless the memory feature answered — two unrelated features sharing
 * one request, each able to break the other's screen.
 */
import { api } from "../api";

export type WorkProfile = {
  company: string | null;
  department: string | null;
  job_title: string | null;
  reporting_to: string | null;
};

export const EMPTY_WORK_PROFILE: WorkProfile = {
  company: null,
  department: null,
  job_title: null,
  reporting_to: null,
};

function trimOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export async function fetchWorkProfile(): Promise<WorkProfile> {
  const data = await api<Partial<WorkProfile>>("/api/user/work-profile");
  return {
    company: trimOrNull(data?.company),
    department: trimOrNull(data?.department),
    job_title: trimOrNull(data?.job_title),
    reporting_to: trimOrNull(data?.reporting_to),
  };
}
