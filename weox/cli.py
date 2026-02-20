# weox/cli.py

import sys
import re

variables = {}


# ===============================
# Error System
# ===============================

def error(err_type, msg, lineno):
    print(f"{err_type} (line {lineno}): {msg}")


# ===============================
# Utilities
# ===============================

def should_skip_line(line):
    line = line.strip()
    return not line or line.startswith("//")


def translate_condition(expr):
    """
    Convert Weox comparisons to Python.
    Important: '=' becomes '==' but not for >= <= !=
    """
    # protect >= <= != first
    expr = expr.replace(">=", "__GE__")
    expr = expr.replace("<=", "__LE__")
    expr = expr.replace("!=", "__NE__")

    # replace single =
    expr = re.sub(r'(?<![<>!])=(?!=)', '==', expr)

    # restore
    expr = expr.replace("__GE__", ">=")
    expr = expr.replace("__LE__", "<=")
    expr = expr.replace("__NE__", "!=")

    return expr


# ===============================
# Expression Engine
# ===============================

def evaluate_expression(expr, lineno):
    expr = expr.strip()

    # replace @vars
    for name, value in variables.items():
        expr = expr.replace(f"@{name}", repr(value))

    try:
        return eval(expr, {"__builtins__": {}}, {})
    except Exception:
        error("RuntimeError", "invalid expression", lineno)
        return None


def evaluate_condition(expr, lineno):
    expr = translate_condition(expr)
    return evaluate_expression(expr, lineno)


# ===============================
# Block Parser
# ===============================

def collect_block(lines, start_index):
    block = []
    depth = 0
    i = start_index

    while i < len(lines):
        line = lines[i]

        if "{" in line:
            depth += line.count("{")
            if depth == 1:
                i += 1
                continue

        if "}" in line:
            depth -= line.count("}")
            if depth == 0:
                return block, i

        if depth >= 1:
            block.append(lines[i])

        i += 1

    return None, i


# ===============================
# Core Commands
# ===============================

def handle_say(line, lineno):
    content = line[4:].strip()

    if content.startswith("@") and " " not in content:
        varname = content[1:]
        if varname in variables:
            print(variables[varname])
        else:
            error("NameError", f"undefined variable '{varname}'", lineno)
        return

    value = evaluate_expression(content, lineno)
    if value is not None:
        print(value)


def handle_assignment(line, lineno):
    name, expr = line.split(":", 1)
    name = name.strip()
    expr = expr.strip()

    if not name.isidentifier():
        error("SyntaxError", "invalid variable name", lineno)
        return

    value = evaluate_expression(expr, lineno)
    if value is not None:
        variables[name] = value


# ===============================
# IF / ELIF / ELSE
# ===============================

def handle_if_chain(lines, index):
    executed = False
    i = index

    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.strip()
        lineno = i + 1

        # IF
        if line.startswith("if "):
            cond_part = line[3:line.index("{")].strip()
            result = evaluate_condition(cond_part, lineno)

            block, end_index = collect_block(lines, i)
            if block is None:
                error("BlockError", "missing closing '}'", lineno)
                return i

            if result and not executed:
                run_lines(block)
                executed = True

            i = end_index

        # ELIF
        elif line.startswith("elif "):
            cond_part = line[5:line.index("{")].strip()
            result = evaluate_condition(cond_part, lineno)

            block, end_index = collect_block(lines, i)
            if block is None:
                error("BlockError", "missing closing '}'", lineno)
                return i

            if result and not executed:
                run_lines(block)
                executed = True

            i = end_index

        # ELSE
        elif line.startswith("else"):
            block, end_index = collect_block(lines, i)
            if block is None:
                error("BlockError", "missing closing '}'", lineno)
                return i

            if not executed:
                run_lines(block)

            i = end_index
            break

        else:
            break

        i += 1

    return i


# ===============================
# LOOP HANDLERS
# ===============================

def handle_loop(line, lines, index, lineno):
    # loop until CONDITION
    if line.startswith("loop until "):
        cond_part = line[11:line.index("{")].strip()
        block, end_index = collect_block(lines, index)

        if block is None:
            error("BlockError", "missing closing '}'", lineno)
            return index

        while True:
            result = evaluate_condition(cond_part, lineno)
            if result:
                break
            run_lines(block)

        return end_index

    # loop i in N times
    m = re.match(r'loop\s+(\w+)\s+in\s+(\d+)\s+times', line)
    if m:
        var = m.group(1)
        count = int(m.group(2))

        block, end_index = collect_block(lines, index)
        if block is None:
            error("BlockError", "missing closing '}'", lineno)
            return index

        for i in range(count):
            variables[var] = i
            run_lines(block)

        return end_index

    # loop i in A-B (inclusive)
    m = re.match(r'loop\s+(\w+)\s+in\s+(\d+)\-(\d+)', line)
    if m:
        var = m.group(1)
        start = int(m.group(2))
        end = int(m.group(3))

        block, end_index = collect_block(lines, index)
        if block is None:
            error("BlockError", "missing closing '}'", lineno)
            return index

        step = 1 if end >= start else -1

        for i in range(start, end + step, step):
            variables[var] = i
            run_lines(block)

        return end_index

    error("SyntaxError", "invalid loop syntax", lineno)
    return index


# ===============================
# Runner
# ===============================

def run(line, lineno, lines=None, index=None):
    line = line.strip()

    if should_skip_line(line):
        return index

    # IF chain
    if line.startswith("if "):
        return handle_if_chain(lines, index)

    # loop
    if line.startswith("loop "):
        return handle_loop(line, lines, index, lineno)

    # say
    if line.startswith("say "):
        handle_say(line, lineno)
        return index

    # assignment
    if ":" in line:
        handle_assignment(line, lineno)
        return index

    error("SyntaxError", "unexpected statement", lineno)
    return index


def run_lines(lines):
    i = 0
    while i < len(lines):
        result = run(lines[i], i + 1, lines, i)
        if result is not None and result != i:
            i = result
        i += 1


def run_file(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            lines = f.readlines()
            run_lines(lines)
    except FileNotFoundError:
        print("Error: File Not Found!")


def main():
    if len(sys.argv) < 2:
        print("Usage: weox <file.we>")
        return

    filename = sys.argv[1]

    if filename.endswith(".we"):
        run_file(filename)
    else:
        print("❌ Weox files must use .we format")


if __name__ == "__main__":
    main()
