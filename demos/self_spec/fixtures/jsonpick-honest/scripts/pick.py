import json
import sys

data = json.load(sys.stdin)
key = sys.argv[1].lstrip(".")
val = data[key]
print(val if isinstance(val, str) else json.dumps(val))
