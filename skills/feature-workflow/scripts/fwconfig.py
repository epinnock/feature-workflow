#!/usr/bin/env python3
"""Read feature-workflow.json, the one config file every script in this directory uses.

Where it is found (first hit wins):
  1. $FEATURE_WORKFLOW_CONFIG (a path to the file)
  2. feature-workflow.json in the current directory or any parent directory

The directory holding the file is the "ops root": relative paths in the config and in
links.json are resolved against it. Schema: scripts/README.md.

Library use (from the other scripts):
    import fwconfig
    cfg = fwconfig.load()                 # exits with a clear message if the file is missing
    cfg.features_root                     # absolute path
    cfg.need("diff_service.base_url")     # exits naming the key if it is missing
    cfg.get("hub_artifact_url")           # None if missing
    cfg.repo("my-dashboard")              # the repos[] entry, or exits naming it

CLI use (from the bash scripts):
    fwconfig.py root                      # ops root
    fwconfig.py features-root             # absolute features_root
    fwconfig.py get <dotted.key>          # value (JSON for objects/lists); exit 3 if missing
    fwconfig.py path <dotted.key>         # value resolved as a path against the ops root
    fwconfig.py repo <name> <field>       # one field of a repos[] entry ("path" is resolved)
Stdlib only.
"""
import json
import os
import sys

FILENAME = "feature-workflow.json"


class ConfigError(SystemExit):
    pass


def fail(msg):
    print(f"feature-workflow: {msg}", file=sys.stderr)
    raise ConfigError(3)


def find_config(start=None):
    env = os.environ.get("FEATURE_WORKFLOW_CONFIG")
    if env:
        p = os.path.abspath(os.path.expanduser(env))
        if not os.path.isfile(p):
            fail(f"FEATURE_WORKFLOW_CONFIG points at {p}, which does not exist")
        return p
    d = os.path.abspath(start or os.getcwd())
    while True:
        p = os.path.join(d, FILENAME)
        if os.path.isfile(p):
            return p
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


class Config:
    def __init__(self, path):
        self.path = path
        self.root = os.path.dirname(path)
        try:
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except json.JSONDecodeError as err:
            fail(f"{path} is not valid JSON: {err}")
        if not isinstance(self.data, dict):
            fail(f"{path} must hold a JSON object")

    def get(self, key, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur or cur[part] in (None, ""):
                return default
            cur = cur[part]
        return cur

    def need(self, key, why=""):
        v = self.get(key)
        if v is None:
            fail(f"{self.path}: missing key '{key}'" + (f" ({why})" if why else "") + "; see scripts/README.md for the schema")
        return v

    def resolve(self, p):
        p = os.path.expanduser(str(p))
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.root, p))

    def path_of(self, key, why=""):
        return self.resolve(self.need(key, why))

    @property
    def features_root(self):
        return self.resolve(self.get("features_root", "features"))

    def repos(self):
        r = self.get("repos", [])
        if not isinstance(r, list):
            fail(f"{self.path}: 'repos' must be a list")
        return r

    def repo(self, name):
        for r in self.repos():
            if r.get("name") == name:
                return r
        known = ", ".join(r.get("name", "?") for r in self.repos()) or "none configured"
        fail(f"{self.path}: no entry named '{name}' in 'repos' (known: {known})")

    def rel(self, p):
        """Path relative to the ops root when it is inside it (for links.json and reports)."""
        a = os.path.abspath(p)
        return os.path.relpath(a, self.root) if a.startswith(self.root + os.sep) else a


def load(required=True):
    p = find_config()
    if not p:
        if required:
            fail(f"no {FILENAME} found in this directory or any parent, and FEATURE_WORKFLOW_CONFIG is not set. "
                 f"Create one at the root of your ops repo (schema: scripts/README.md).")
        return None
    return Config(p)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cfg = load()
    cmd = argv[0]
    if cmd == "root":
        print(cfg.root)
    elif cmd == "features-root":
        print(cfg.features_root)
    elif cmd in ("get", "path") and len(argv) == 2:
        v = cfg.get(argv[1])
        if v is None:
            print(f"feature-workflow: {cfg.path}: missing key '{argv[1]}'", file=sys.stderr)
            return 3
        if cmd == "path":
            print(cfg.resolve(v))
        else:
            print(json.dumps(v) if isinstance(v, (dict, list)) else v)
    elif cmd == "repo" and len(argv) == 3:
        r = cfg.repo(argv[1])
        v = r.get(argv[2])
        if v in (None, ""):
            print(f"feature-workflow: {cfg.path}: repos entry '{argv[1]}' has no '{argv[2]}'", file=sys.stderr)
            return 3
        if argv[2] == "path":
            v = cfg.resolve(v)
        print(json.dumps(v) if isinstance(v, (dict, list)) else v)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ConfigError as e:
        sys.exit(e.code)
