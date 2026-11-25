/* Pure helpers for the opening-hours editor: one text box per day, written like "09:00-14:00, 17:00-22:00". */

const TIME = /^([01]?\d|2[0-3]):([0-5]\d)$/;

const pad = (t) => {
  const m = TIME.exec(t.trim());
  return m ? `${m[1].padStart(2, "0")}:${m[2]}` : null;
};

/** [{opens, closes}] -> "09:00-14:00, 17:00-22:00" ("" for a closed day). */
export function formatDay(periods) {
  return (periods ?? []).map((p) => `${p.opens}-${p.closes}`).join(", ");
}

/** "9:00-14:00, 17:00-22:00" -> { periods } or { error }. An empty box means closed that day. */
export function parseDay(text) {
  const value = (text ?? "").trim();
  if (!value) return { periods: [] };
  const periods = [];
  for (const part of value.split(",")) {
    const bits = part.split(/[-\u2013\u2014]/);
    const opens = bits.length === 2 ? pad(bits[0]) : null;
    const closes = bits.length === 2 ? pad(bits[1]) : null;
    if (!opens || !closes) return { error: "Write times like 09:00-14:00, separated by commas." };
    if (closes <= opens) return { error: `${opens}-${closes}: closing must be after opening. For a late night, end at 23:59 and start the next day at 00:00.` };
    periods.push({ opens, closes });
  }
  periods.sort((a, b) => a.opens.localeCompare(b.opens));
  for (let i = 1; i < periods.length; i += 1) {
    if (periods[i].opens < periods[i - 1].closes) return { error: "These times overlap." };
  }
  return { periods };
}

/** Seven day boxes -> the list the API wants, or the first error as { day, error }. */
export function buildPeriods(texts) {
  const out = [];
  for (let weekday = 0; weekday < 7; weekday += 1) {
    const parsed = parseDay(texts[weekday]);
    if (parsed.error) return { day: weekday, error: parsed.error };
    for (const p of parsed.periods) out.push({ weekday, ...p });
  }
  return { periods: out };
}

/** "" -> null, otherwise a plain decimal string with at most 6 places (what the API stores). */
export function coordinateText(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number.toFixed(6) : text;
}
