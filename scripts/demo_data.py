"""Create a demo Forge data folder (learner "Priya") for screenshots and trying the UI. No AI calls.

    python scripts/demo_data.py <folder>        then: FORGE_DATA=<folder> python server.py
"""
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-data")
out.mkdir(parents=True, exist_ok=True)
today = date.today()
start = today - timedelta(days=11)
now = int(time.time() * 1000)
MIN = 60_000


def ts(days_ago, minutes):
    d = today - timedelta(days=days_ago)
    return int(time.mktime(d.timetuple()) * 1000) + minutes * MIN


(out / "profile.json").write_text(json.dumps({
    "name": "Priya", "goal": "Crack a FAANG frontend role", "deadlineLabel": "until offer day",
    "start": start.isoformat(), "deadline": (start + timedelta(days=125)).isoformat(),
    "language": "Python", "knows": "JavaScript, React, Node.js", "hours": "1–2 h",
    "level": "Some practice: I can do easy problems", "model": "sonnet",
    "weakSpots": ["Big-O of nested loops", "off-by-one in slices"],
}, indent=2), encoding="utf-8")

TASK = """Longest Substring Without Repeating Characters
Given a string `s`, return the length of the longest substring with no repeated characters.
`s = "abcabcbb"` → `3`
`s = "pwwkew"` → `3`
Send back: your function, run on both examples."""

msgs = [
    ("learner", "code", 1, 0, "hi! ready for today"),
    ("coach", "code", 1, 1, "⚠️ Watch today: off-by-one in slices.\n\nNew pattern: **sliding window**. One worked example first.\n\n```python\ns = \"abca\"\nleft, seen = 0, set()\nfor right, ch in enumerate(s):\n    while ch in seen:\n        seen.remove(s[left])\n        left += 1\n    seen.add(ch)\n    print(right, s[left:right + 1])\n```\n\n```text\n0 a\n1 ab\n2 abc\n3 bca\n```\n\nThe window grows on the right and shrinks on the left whenever a letter repeats.\n\n**At `right = 3`, which letter left the window, and why?**"),
    ("learner", "code", 1, 4, "a left because the new a was already in seen"),
    ("coach", "code", 1, 5, "Q: which letter left the window at `right = 3`?\n\n✅ **`a`, and your reason is exactly right.** The new `a` was already in `seen`, so the `while` loop removed from the left until it wasn't.\n\nNow you do one alone.\n\n```task\n" + TASK + "\n```\n\n**Write `length_of_longest_substring(s)` in the code editor and send it with the output.**"),
    ("learner", "code", 0, 0, "```python\ndef length_of_longest_substring(s):\n    left, seen, best = 0, set(), 0\n    for right, ch in enumerate(s):\n        while ch in seen:\n            seen.remove(s[left])\n            left += 1\n        seen.add(ch)\n        best = max(best, right - left + 1)\n    return best\n\nprint(length_of_longest_substring(\"abcabcbb\"), length_of_longest_substring(\"pwwkew\"))\n```\n\nOutput:\n```text\n3 3\n```"),
    ("coach", "code", 0, 1, "Q: does your function return 3 for both examples?\n\n✅ **Yes, and you wrote it yourself.** `best` updates on every step, so the window size is never missed.\n\n| check | yours |\n|---|---|\n| window shrinks with `while` | ✅ |\n| `best` inside the loop | ✅ |\n| off-by-one (`right - left + 1`) | ✅ |\n\n```status\nproblem: Longest Substring Without Repeating Characters\nresult: solved\n```\n\n**Explain-back: in 3 sentences, give the approach, the time and space complexity, and one edge case.**"),
    ("learner", "code", 0, 4, "Sliding window with a set. O(n) time since each letter enters and leaves once, O(k) space. Edge case: empty string returns 0."),
    ("coach", "code", 0, 5, "Q: explain-back for Longest Substring.\n\n✅ **Approach** ✅ **Complexity** ✅ **Edge case**: all three, interview-ready.\n\n🥊 Challenge: a friend says the inner `while` makes this O(n²). Predict first:\n\n```python\nprint(sum(1 for _ in range(5)))\n```\n\n```text\n5\n```\n\nAcross the whole run, how many times can `left` move forward at most?\n\n- A) n times in total\n- B) n times per letter\n- C) once per loop iteration, always\n- D) it depends on the alphabet size\n\n**Pick a letter, then one line on why.**"),
]
messages = []
for i, (role, track, days_ago, minute, text) in enumerate(msgs):
    m = {"id": f"demo{i:03d}", "role": role, "track": track, "text": text,
         "day": (today - timedelta(days=days_ago) - start).days + 1, "createdAt": ts(days_ago, 18 * 60 + 30 + minute)}
    if role == "learner":
        m["status"] = "answered"
    else:
        m["replyTo"] = f"demo{i - 1:03d}"
    messages.append(m)

days = {}
for k in range(12):
    d = start + timedelta(days=k)
    if k in (4, 8):
        continue  # two missed days, for a realistic streak
    days[d.isoformat()] = {"day": k + 1, "code": True, "sd": k % 3 != 1, "type": "normal"}

due = today.isoformat()
problems = {
    "Contains Duplicate": {"status": "mastered", "due": (today + timedelta(days=18)).isoformat()},
    "Valid Anagram": {"status": "mastered", "due": (today + timedelta(days=15)).isoformat()},
    "Two Sum": {"status": "solved", "due": due},
    "Group Anagrams": {"status": "solved", "due": (today + timedelta(days=2)).isoformat()},
    "Valid Palindrome": {"status": "solved", "due": due},
    "Longest Substring Without Repeating Characters": {"status": "solved", "due": (today + timedelta(days=1)).isoformat()},
    "Top K Frequent Elements": {"status": "seen"},
    "Product of Array Except Self": {"status": "seen"},
}
for p in problems.values():
    p.update(reviews=[], updatedAt=now, solvedAt=now - 5 * 86400_000)

state = {"messages": messages, "days": days, "problems": problems,
         "task": {"text": TASK, "fromId": "demo003", "updatedAt": ts(1, 18 * 60 + 35)}}
(out / "data.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
(out / "progress.md").write_text("# Priya's progress (Forge)\n\nDemo data.\n", encoding="utf-8")
print(f"Demo data written to {out.resolve()}")
