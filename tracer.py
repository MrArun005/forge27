"""Step tracer for Forge 27: runs user code and records every line with the variables at that moment.

Usage: python tracer.py <file.py>  ->  prints one JSON object {steps, error, truncated}.
Each step: {line, func, event, vars, out}. "vars" is the frame's locals *before* the line runs,
so stepping forward shows what each line changed.
"""
import io
import json
import sys
import types

MAX_STEPS = 500
MAX_REPR = 120


def show(v):
    try:
        r = repr(v)
    except Exception:
        r = "<unprintable>"
    return r if len(r) <= MAX_REPR else r[: MAX_REPR - 3] + "..."


def visible(name, value):
    if name.startswith("__"):
        return False
    return not isinstance(value, (types.ModuleType, types.FunctionType, type, types.BuiltinFunctionType))


def main():
    src = open(sys.argv[1], encoding="utf-8").read()
    steps, out, real_out = [], io.StringIO(), sys.stdout
    result = {"steps": steps, "error": None, "truncated": False}

    class Stop(Exception):
        pass

    def tracer(frame, event, arg):
        if frame.f_code.co_filename != "<your code>":
            return None
        if event == "return" and frame.f_code.co_name == "<module>":
            return tracer
        if event in ("line", "return", "exception"):
            if len(steps) >= MAX_STEPS:
                result["truncated"] = True
                raise Stop
            step = {
                "line": frame.f_lineno,
                "func": frame.f_code.co_name if frame.f_code.co_name != "<module>" else "",
                "event": event,
                "vars": {k: show(v) for k, v in frame.f_locals.items() if visible(k, v)},
                "out": out.getvalue(),
            }
            if event == "return":
                step["ret"] = show(arg)
            steps.append(step)
        return tracer

    try:
        code = compile(src, "<your code>", "exec")
    except SyntaxError as e:
        result["error"] = f"SyntaxError on line {e.lineno}: {e.msg}"
        real_out.write(json.dumps(result))
        return
    sys.stdout = out
    sys.settrace(tracer)
    try:
        exec(code, {"__name__": "__main__"})
    except Stop:
        pass
    except Exception as e:  # show the error at the step where it happened
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        sys.settrace(None)
        sys.stdout = real_out
    if steps:
        steps.append({"line": steps[-1]["line"], "func": "", "event": "end", "vars": steps[-1]["vars"], "out": out.getvalue()})
    real_out.write(json.dumps(result))


if __name__ == "__main__":
    main()
