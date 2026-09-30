"""Empirical Big-O for Forge 27.

Runs the user's code once to find the function it calls and the example arguments, then calls
that function on bigger and bigger generated inputs, measuring:
  time  = Python lines executed inside the user's code (deterministic; no timer noise)
  space = peak memory allocated during the call (tracemalloc), excluding the input itself
and fits each series against O(1), O(log n), O(n), O(n log n), O(n^2), O(n^3), O(2^n).

Inputs are generated worst-case-ish: distinct numbers (no early duplicate hit), strings of equal
length, and example ints (like target or k) kept as given.
Usage: python complexity.py <file.py>  ->  prints one JSON object.
"""
import contextlib
import copy
import io
import json
import math
import random
import string
import sys
import time
import tracemalloc
import types

SIZES = [8, 16, 32, 64, 128, 256, 512, 1024, 2048]
STEP_CAP = 3_000_000
TIME_BUDGET = 3.5  # seconds for the whole measurement

CLASSES = [
    ("O(1)", lambda n: 1.0),
    ("O(log n)", lambda n: math.log2(n)),
    ("O(n)", lambda n: float(n)),
    ("O(n log n)", lambda n: n * math.log2(n)),
    ("O(n²)", lambda n: float(n * n)),
    ("O(n³)", lambda n: float(n ** 3)),
    ("O(2ⁿ)", lambda n: 2.0 ** min(n, 60)),
]


def fit(ns, ys, allowed=None):
    """Pick the class whose y/f(n) ratio stays most constant (lowest spread in log space)."""
    pts = [(n, y) for n, y in zip(ns, ys) if y and y > 0]
    if len(pts) < 3:
        return None, []
    scores = []
    for name, f in CLASSES:
        if allowed and name not in allowed:
            continue
        logs = [math.log(y / f(n)) for n, y in pts if f(n) > 0]
        mean = sum(logs) / len(logs)
        spread = math.sqrt(sum((v - mean) ** 2 for v in logs) / len(logs))
        scores.append((spread, name))
    scores.sort()
    return scores[0][1], [{"cls": n, "spread": round(s, 3)} for s, n in scores[:3]]


def make_like(sample, n, rng, twin=None, floor=0):
    """Generate an input of size n shaped like the example argument.
    `floor` pushes generated ints above any example int (like a target), so no pair can sum to it
    and searches never succeed early: the worst case."""
    if isinstance(sample, bool):
        return sample
    if isinstance(sample, str):
        if twin is not None:  # second string of a pair: same letters, shuffled -> full comparison work
            s = list(twin)
            rng.shuffle(s)
            return "".join(s)
        alphabet = "".join(sorted(set(sample))) if sample and sample.isupper() else string.ascii_lowercase
        return "".join(rng.choice(alphabet) for _ in range(n))
    if isinstance(sample, list):
        if all(isinstance(x, int) and not isinstance(x, bool) for x in sample):
            return rng.sample(range(floor, floor + 10 * n + 10), n)  # distinct and above any target
        if all(isinstance(x, str) for x in sample):
            return ["".join(rng.choice("abcdefgh") for _ in range(rng.randint(3, 6))) for _ in range(n)]
        if all(isinstance(x, float) for x in sample):
            return [rng.random() * 100 for _ in range(n)]
        raise ValueError("lists of that kind aren't supported yet (try a list of ints or strings)")
    if isinstance(sample, (int, float)):
        return sample
    raise ValueError(f"can't generate inputs of type {type(sample).__name__}")


def main():
    src = open(sys.argv[1], encoding="utf-8").read()
    out = {"ok": False}
    try:
        code = compile(src, "<your code>", "exec")
    except SyntaxError as e:
        out["error"] = f"SyntaxError on line {e.lineno}: {e.msg}"
        print(json.dumps(out))
        return

    # 1) run once, capturing the first call from top-level code to a function defined in the code
    env = {"__name__": "__main__"}
    first = {}

    def spy(frame, event, arg):
        if event == "call" and frame.f_code.co_filename == "<your code>" and frame.f_code.co_name != "<module>" \
                and frame.f_back is not None and frame.f_back.f_code.co_name == "<module>" and not first:
            fn = frame.f_code.co_name
            argnames = frame.f_code.co_varnames[: frame.f_code.co_argcount]
            first.update(name=fn, args=[copy.deepcopy(frame.f_locals[a]) for a in argnames], argnames=list(argnames))
        return None

    sys.settrace(spy)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(code, env)
    except Exception as e:
        sys.settrace(None)
        out["error"] = f"Your code raised {type(e).__name__}: {e}"
        print(json.dumps(out))
        return
    sys.settrace(None)
    if not first:
        out["error"] = "Call your function once with an example, e.g. print(two_sum([2, 7, 11, 15], 9))."
        print(json.dumps(out))
        return
    fn = env.get(first["name"])
    if not isinstance(fn, types.FunctionType):
        out["error"] = f"Couldn't find the function {first['name']}()."
        print(json.dumps(out))
        return

    out.update(function=first["name"], argnames=first["argnames"])
    rng = random.Random(27)
    ns, steps, peaks, started = [], [], [], time.time()
    scaled = [a for a, v in zip(first["argnames"], first["args"]) if isinstance(v, (str, list))]
    if not scaled:
        out["error"] = "None of the inputs is a list or string, so there's no 'n' to grow."
        print(json.dumps(out))
        return
    out["scaled"] = scaled
    ints = [abs(v) for v in first["args"] if isinstance(v, int) and not isinstance(v, bool)]
    floor = max(ints) + 1 if ints else 0

    def build(n):
        args, prev_str = [], None
        for v in first["args"]:
            twin = prev_str if isinstance(v, str) and prev_str is not None else None
            g = make_like(v, n, rng, twin, floor)
            if isinstance(v, str) and prev_str is None:
                prev_str = g
            args.append(g)
        return args

    for n in SIZES:
        if time.time() - started > TIME_BUDGET:
            break
        try:
            args = build(n)
        except ValueError as e:
            out["error"] = str(e)
            break

        count = [0]

        class Cap(Exception):
            pass

        def counter(frame, event, arg):
            if frame.f_code.co_filename != "<your code>":
                return None
            if event == "line":
                count[0] += 1
                if count[0] > STEP_CAP:
                    raise Cap
            return counter

        a1 = copy.deepcopy(args)
        sys.settrace(counter)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fn(*a1)
        except Cap:
            sys.settrace(None)
            out["note"] = f"Stopped growing at n={n}: over {STEP_CAP:,} steps."
            break
        except Exception as e:
            sys.settrace(None)
            out["error"] = f"At n={n} your function raised {type(e).__name__}: {e}"
            break
        sys.settrace(None)

        a2 = copy.deepcopy(args)
        tracemalloc.start()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fn(*a2)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        ns.append(n)
        steps.append(count[0])
        peaks.append(peak)

    out.update(n=ns, steps=steps, peak_bytes=peaks)

    # wall-clock time on bigger inputs: this sees the work done inside built-ins like set() or sorted()
    tns, tsec = [], []
    if "error" not in out:
        for n in [256, 512, 1024, 2048, 4096, 8192, 16384, 32768]:
            if time.time() - started > TIME_BUDGET + 2.5:
                break
            args = build(n)
            best = None
            for _ in range(3):
                reps, t0 = 0, time.perf_counter()
                while True:
                    a = copy.deepcopy(args)
                    s = time.perf_counter()
                    with contextlib.redirect_stdout(io.StringIO()):
                        fn(*a)
                    reps += 1
                    elapsed = time.perf_counter() - s
                    best = elapsed if best is None or elapsed < best else best
                    if time.perf_counter() - t0 > 0.03 or elapsed > 0.2:
                        break
            tns.append(n)
            tsec.append(best)
            if best > 0.25:
                break
    out.update(time_n=tns, seconds=[round(s, 7) for s in tsec])

    if len(ns) >= 3:
        order = [c for c, _ in CLASSES]
        steps_cls, _ = fit(ns, steps)
        out["steps_class"] = steps_cls
        # The line count is exact for the user's own loops but blind to work inside built-ins
        # (set(), sorted(), Counter(), "x in list"). A stopwatch sees that work, but can't separate
        # O(n) from O(n log n) (both about double per doubling), so it's only used to detect hidden work.
        hidden = None
        if len(tsec) >= 3:
            rs = sorted(tsec[i] / tsec[i - 1] for i in range(1, len(tsec)) if tsec[i - 1])
            wall_ratio = rs[len(rs) // 2]
            out["wall_ratio"] = round(wall_ratio, 2)
            if wall_ratio >= 3.0:
                hidden = "O(n²)"
            elif wall_ratio >= 1.6:
                hidden = "O(n log n)" if ("sorted(" in src or ".sort(" in src) else "O(n)"
        if hidden and order.index(hidden) > order.index(steps_cls):
            out["time"], out["time_source"], out["hidden_work"] = hidden, "run time (work inside built-ins)", True
        else:
            out["time"], out["time_source"] = steps_cls, "lines executed"
        # memory: flat within ~2 KB across the whole range means constant extra space
        if max(peaks) - min(peaks) < 2048:
            out["space"], out["space_fits"] = "O(1)", [{"cls": "O(1)", "spread": 0}]
        else:
            # fit the growth above the fixed overhead, on the larger sizes where the overhead doesn't dominate
            base = min(peaks)
            big = [(n, p - base + 1) for n, p in zip(ns, peaks) if n >= 64]
            out["space"], out["space_fits"] = fit([n for n, _ in big], [p for _, p in big], {"O(1)", "O(log n)", "O(n)", "O(n²)"})
        def median_ratio(ys):
            rs = sorted(ys[i] / ys[i - 1] for i in range(1, len(ys)) if ys[i - 1])
            return round(rs[len(rs) // 2], 2) if rs else None
        tseries = tsec if out.get("time_source") == "run time" else steps
        out["doubling"] = {"time": median_ratio(tseries), "space": median_ratio(peaks)}
        out["ok"] = True
    elif "error" not in out:
        out["error"] = "Not enough sizes finished to fit a curve."
    print(json.dumps(out))


if __name__ == "__main__":
    main()
