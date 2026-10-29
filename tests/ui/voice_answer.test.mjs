// Tests the spoken-answer rules used by the ORION window (copied from orion.js voiceAnswer; keep in sync).
// Run: node tests/ui/voice_answer.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../../src/orion/ui/web/orion.js", import.meta.url), "utf8");
const no = new RegExp(src.match(/if \(\/(\\b\(no\|nope[^/]*)\/\.test\(t\)\) return answer\(false\)/)[1]);
const yes = new RegExp(src.match(/if \(\/(\\b\(yes\|yeah[^/]*)\/\.test\(t\)\) return answer\(true\)/)[1]);
const decide = t => (no.test(t) ? false : yes.test(t) ? true : null);

for (const [said, want] of [
  ["yes", true], ["yes please", true], ["go ahead", true], ["approve it", true], ["okay send it", true],
  ["no", false], ["don't do it", false], ["do not send", false], ["cancel", false], ["wait", false],
  ["hmm what was that", null], ["the weather is nice", null],
]) {
  assert.equal(decide(said.toLowerCase()), want, `"${said}"`);
}
console.log("voice answer rules: all cases pass");
