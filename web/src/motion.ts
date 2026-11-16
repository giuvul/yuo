// Whether the learner asked for reduced motion; follows the setting while the page is open. Motion in Yuo is CSS
// (which reads the same media query); this is for the few places where script moves things (the path graph).
import { useEffect, useState } from "react";

export function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => typeof matchMedia === "function" && matchMedia(query).matches);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const media = matchMedia(query);
    const on = () => setReduced(media.matches);
    media.addEventListener("change", on);
    return () => media.removeEventListener("change", on);
  }, []);
  return reduced;
}
