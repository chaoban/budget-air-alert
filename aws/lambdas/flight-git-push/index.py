import json, urllib.request, urllib.error
import boto3

API = "https://api.github.com"


def gh(tok, method, path, body=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "flight-git-push",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as ex:
        raise RuntimeError("%s %s -> %s %s" % (method, path, ex.code, ex.read().decode()[:300]))


def handler(e, c):
    raw = boto3.client("secretsmanager").get_secret_value(
        SecretId=e.get("secret_id", "flight-price-notifier/github-pat"))["SecretString"]
    try:
        d = json.loads(raw)
        tok = d.get("token") or d.get("pat") if isinstance(d, dict) else str(d)
    except ValueError:
        tok = raw.strip()
    repo, branch = e["repo"], e.get("branch", "main")
    try:
        if e.get("check"):
            r = gh(tok, "GET", "/repos/" + repo)
            head = gh(tok, "GET", "/repos/%s/git/ref/heads/%s" % (repo, branch))["object"]["sha"]
            print("CHECK_OK", repo, "head", head, "permissions", json.dumps(r.get("permissions")))
            return {"ok": True}
        head = gh(tok, "GET", "/repos/%s/git/ref/heads/%s" % (repo, branch))["object"]["sha"]
        if e.get("expect_head") and e["expect_head"] != head:
            print("PUSH_ABORT head moved: expected", e["expect_head"], "got", head)
            return {"ok": False}
        base_tree = gh(tok, "GET", "/repos/%s/git/commits/%s" % (repo, head))["tree"]["sha"]
        tree = []
        for path, b64 in e.get("files", {}).items():
            blob = gh(tok, "POST", "/repos/%s/git/blobs" % repo, {"content": b64, "encoding": "base64"})
            tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        for path in e.get("delete", []):
            tree.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        nt = gh(tok, "POST", "/repos/%s/git/trees" % repo, {"base_tree": base_tree, "tree": tree})
        cm = gh(tok, "POST", "/repos/%s/git/commits" % repo,
                {"message": e["message"], "tree": nt["sha"], "parents": [head]})
        gh(tok, "PATCH", "/repos/%s/git/refs/heads/%s" % (repo, branch), {"sha": cm["sha"], "force": False})
        print("PUSHED", repo, branch, cm["sha"], "files", len(tree))
        return {"ok": True, "commit": cm["sha"]}
    except RuntimeError as ex:
        print("PUSH_ERR", str(ex))
        return {"ok": False}
