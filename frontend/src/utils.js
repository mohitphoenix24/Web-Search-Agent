export function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function faviconOf(url) {
  return `https://www.google.com/s2/favicons?domain=${hostOf(url)}&sz=64`;
}

export function hideBrokenImage(e) {
  e.currentTarget.style.display = "none";
}

// The LLM writes citations like [1] or [2, 5]. Turn each number into a
// markdown link to "#source-N" so we can render it as a clickable pill.
export function linkCitations(text) {
  return text
    .replace(/【(\d+)[^】]*】/g, "[$1]") // some models use 【1†...】 style
    .replace(/\[(\d+(?:\s*,\s*\d+)*)\](?!\()/g, (_, nums) =>
      nums
        .split(/\s*,\s*/)
        .map((n) => `[${n}](#source-${n})`)
        .join("")
    );
}

export function citedIds(text) {
  return new Set([...linkCitations(text).matchAll(/#source-(\d+)/g)].map((m) => Number(m[1])));
}
