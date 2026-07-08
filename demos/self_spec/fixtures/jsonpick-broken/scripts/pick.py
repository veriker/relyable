import json
import sys

data = json.load(sys.stdin)
key = sys.argv[1].lstrip(".")
val = data[key]
# Regression: always repr()s, so `.version` prints "'1.2'" not "1.2" —
# contradicts the skill's OWN documented example.
print(repr(val))
