// Pure helpers for Web Speech API result lists, kept free of DOM types so they can be unit tested.

export function joinText(...parts) {
  return parts.map((part) => part.trim()).filter(Boolean).join(" ");
}

// Chrome on Android re-emits the whole utterance so far as a new final result
// ("a", "a b", "a b c"). Replace the previous phrase when the next one extends it.
export function mergeFinalPhrases(phrases) {
  const merged = [];
  for (const raw of phrases) {
    const phrase = raw.trim();
    if (!phrase) continue;
    const last = merged[merged.length - 1];
    if (last !== undefined && (phrase === last || phrase.startsWith(`${last} `))) merged[merged.length - 1] = phrase;
    else if (last !== undefined && last.startsWith(phrase)) continue;
    else merged.push(phrase);
  }
  return merged.join(" ");
}

export function isMobileSpeechClient(userAgent, maxTouchPoints = 0) {
  return /android|iphone|ipad|ipod|mobile/i.test(userAgent) || maxTouchPoints > 1 && /macintosh/i.test(userAgent);
}
