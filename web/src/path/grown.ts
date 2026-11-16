import { useEffect, useRef } from "react";

/** What already grew in this session: a path's vine grows on the first view only, not on every visit. */
const grown = new Set<string>();

/** True on the first view of `key` in this session (once `ready`), and it stays true for that mounted view. */
export function useGrowsOnce(key: string, ready: boolean): boolean {
  const fresh = useRef(!grown.has(key)).current;
  useEffect(() => {
    if (ready) grown.add(key);
  }, [key, ready]);
  return fresh;
}
