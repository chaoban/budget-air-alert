import { useEffect } from "react";

function setMeta(attr: "name" | "property", key: string, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

/** Client-side replacement for per-route <head> meta (title, description, og:*). */
export function usePageMeta({
  title,
  description,
  ogDescription,
}: {
  title: string;
  description: string;
  ogDescription?: string;
}) {
  useEffect(() => {
    document.title = title;
    setMeta("name", "description", description);
    setMeta("property", "og:title", title);
    setMeta("property", "og:description", ogDescription ?? description);
  }, [title, description, ogDescription]);
}
