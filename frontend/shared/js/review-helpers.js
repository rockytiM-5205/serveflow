/* Pure helpers for showing and writing reviews. */

export const RATING_WORDS = Object.freeze({ 1: "Poor", 2: "Fair", 3: "Good", 4: "Very good", 5: "Excellent" });

/** "★★★★☆" for 4. Anything that isn't a whole 1-5 rating shows as no stars rather than a guess. */
export function starText(rating) {
  const n = Number.isInteger(rating) && rating >= 1 && rating <= 5 ? rating : 0;
  return "\u2605".repeat(n) + "\u2606".repeat(5 - n);
}

/** A rating the form may send, or null. Radio buttons give strings. */
export function readRating(value) {
  const n = Number(value);
  return Number.isInteger(n) && n >= 1 && n <= 5 ? n : null;
}

/** "12 Nov 2026" in the visitor's language, or "" for a missing or broken date. */
export function reviewDate(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** What the page says once it knows how many reviews a restaurant has. */
export function reviewSummary(average, count) {
  if (!count || typeof average !== "number") return "No reviews yet";
  return `${average.toFixed(1)} out of 5 from ${count} ${count === 1 ? "review" : "reviews"}`;
}
