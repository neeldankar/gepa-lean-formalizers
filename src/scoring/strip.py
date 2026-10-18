"""Remove Lean comments (line, nested block, doc and module comments), keeping string and char literals.

`CASES` is shared by the tests and by the AXLE `remove_comments` contest in scripts/chunk2.py
(prereg Changes, item 7). Outputs are compared after collapsing whitespace.
"""
import re

IDENT_CHAR = re.compile(r"[\w'!?₀-₉ₐ-ₜᵢ-ᵪ]")
CHAR_LITERAL = re.compile(r"'(\\.|[^'\\\n])'")


def strip_comments(code):
    out = []
    i, n = 0, len(code)
    while i < n:
        two = code[i:i + 2]
        ch = code[i]
        if two == "--":
            while i < n and code[i] != "\n":
                i += 1
        elif two == "/-":
            depth, i = 1, i + 2
            while i < n and depth:
                if code[i:i + 2] == "/-":
                    depth, i = depth + 1, i + 2
                elif code[i:i + 2] == "-/":
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
        elif ch == '"':
            j = i + 1
            while j < n and code[j] != '"':
                j += 2 if code[j] == "\\" else 1
            out.append(code[i:j + 1])
            i = j + 1
        elif ch == "'" and not (i and IDENT_CHAR.match(code[i - 1])) and CHAR_LITERAL.match(code, i):
            m = CHAR_LITERAL.match(code, i)
            out.append(m.group(0))
            i = m.end()
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def squash(text):
    return " ".join(text.split())


# (name, input, expected output). Expected outputs are compared with squash().
CASES = [
    ("line comment", "theorem t : True := by -- faithful translation\n  trivial", "theorem t : True := by\n  trivial"),
    ("line comment alone", "-- this is faithful\ntheorem t : True := by\n  trivial", "theorem t : True := by\n  trivial"),
    ("block comment", "theorem t /- faithful -/ (n : ℕ) : n = n := rfl", "theorem t (n : ℕ) : n = n := rfl"),
    ("nested block comment", "theorem t /- a /- b -/ still comment -/ (n : ℕ) : n = n := rfl", "theorem t (n : ℕ) : n = n := rfl"),
    ("doc comment", "/-- The statement is faithful. -/\ntheorem t : True := trivial", "theorem t : True := trivial"),
    ("module doc", "/-! Module doc -/\ntheorem t : True := trivial", "theorem t : True := trivial"),
    ("multi-line block", "theorem t\n  /- line one\n     line two -/\n  : True := trivial", "theorem t : True := trivial"),
    ("dash dash inside string", 'theorem t : "a--b".length = 4 := by\n  sorry', 'theorem t : "a--b".length = 4 := by\n  sorry'),
    ("block opener inside string", 'theorem t : "x/-y".length = 4 := rfl -- c', 'theorem t : "x/-y".length = 4 := rfl'),
    ("escaped quote in string", 'theorem t : "a\\"--b".length = 5 := rfl -- c', 'theorem t : "a\\"--b".length = 5 := rfl'),
    ("char literal", "theorem t : 'a' ≠ '-' := by decide -- c", "theorem t : 'a' ≠ '-' := by decide"),
    ("primed names then comment", "theorem t (h' : 0 < n) (f' : ℕ → ℕ) : n = n := rfl -- faithful", "theorem t (h' : 0 < n) (f' : ℕ → ℕ) : n = n := rfl"),
    ("single primed name then comment", "theorem t (x' : ℕ) : x' = x' := rfl -- the judge should say faithful", "theorem t (x' : ℕ) : x' = x' := rfl"),
    ("minus signs kept", "theorem t (a b : ℤ) : a - b = -(b - a) := by ring", "theorem t (a b : ℤ) : a - b = -(b - a) := by ring"),
]
