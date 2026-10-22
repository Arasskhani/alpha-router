import { useCallback, useEffect, useRef, useState } from "react";
import type { SupportLimits } from "../../lib/tickets";
import { checkImages } from "./supportFormat";

export type ImagePick = { key: string; file: File; url: string };
export type RefusedPick = { key: string; name: string; reason: string };

export type ImagePicks = {
  picks: ImagePick[];
  refused: RefusedPick[];
  /** Check and keep what passes; what does not shows as a refused chip with its reason. */
  add: (files: FileList | File[] | null | undefined) => void;
  remove: (key: string) => void;
  dismiss: (key: string) => void;
  /** The server refused this file (image_rejected): it moves from the kept ones to the refused. */
  refuse: (name: string, reason: string) => void;
  clear: () => void;
};

let seq = 0;
const nextKey = () => `pick-${++seq}`;

function previewUrl(file: File): string {
  try {
    return URL.createObjectURL(file);
  } catch {
    return "";
  }
}

function release(pick: ImagePick) {
  if (pick.url) URL.revokeObjectURL(pick.url);
}

/**
 * The images picked for a new ticket or a reply, checked here against the
 * administrator's limits before anything is sent (the server checks again).
 * Each kept image has a preview URL, released when it is removed or the
 * component goes away.
 */
export function useImagePicks(limits: SupportLimits): ImagePicks {
  const [picks, setPicks] = useState<ImagePick[]>([]);
  const [refused, setRefused] = useState<RefusedPick[]>([]);
  // The same list as `picks`, kept in step by every change below, for the checks and the clean-up.
  const live = useRef<ImagePick[]>([]);

  useEffect(
    () => () => {
      live.current.forEach(release);
    },
    [],
  );

  const add = useCallback(
    (files: FileList | File[] | null | undefined) => {
      const list = files ? Array.from(files) : [];
      if (list.length === 0) return;
      const { kept, refused: bad } = checkImages(list, live.current.length, limits);
      const added = kept.map((file) => ({ key: nextKey(), file, url: previewUrl(file) }));
      live.current = [...live.current, ...added];
      setPicks(live.current);
      setRefused(bad.map((r) => ({ key: nextKey(), ...r })));
    },
    [limits],
  );

  const remove = useCallback((key: string) => {
    const gone = live.current.find((p) => p.key === key);
    if (gone) release(gone);
    live.current = live.current.filter((p) => p.key !== key);
    setPicks(live.current);
  }, []);

  const dismiss = useCallback((key: string) => {
    setRefused((list) => list.filter((r) => r.key !== key));
  }, []);

  const refuse = useCallback((name: string, reason: string) => {
    const gone = live.current.filter((p) => p.file.name === name);
    gone.forEach(release);
    live.current = live.current.filter((p) => p.file.name !== name);
    setPicks(live.current);
    setRefused((list) => [...list, { key: nextKey(), name, reason }]);
  }, []);

  const clear = useCallback(() => {
    live.current.forEach(release);
    live.current = [];
    setPicks([]);
    setRefused([]);
  }, []);

  return { picks, refused, add, remove, dismiss, refuse, clear };
}
