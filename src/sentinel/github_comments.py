"""Maintain our own inline threads while retaining GitHub's revision anchors."""
import hashlib
import re
import requests
from typing import Any

MARKER = re.compile(r"<!-- sentinel-finding:([a-f0-9]{64}) -->")


def comment_key(comment):
    title = comment["body"].splitlines()[0]
    value = f"{comment['path']}:{comment['line']}:{title}"
    return hashlib.sha256(value.encode()).hexdigest()


def reconcile_comments(url, headers, comments, head, complete, retained_notes=()):
    existing: dict[str, list[dict[str, Any]]] = {}
    page = 1
    while True:
        response = requests.get(url + "/comments", params={"per_page": 100, "page": page}, headers=headers, timeout=30)
        response.raise_for_status()
        batch = response.json()
        for item in batch:
            marker = MARKER.search(item.get("body", ""))
            if marker and item.get("user", {}).get("login") == "github-actions[bot]":
                existing.setdefault(marker[1], []).append(item)
        if len(batch) < 100:
            break
        page += 1
    new = []
    current = {comment_key(note) for note in retained_notes}
    for comment in comments:
        key = comment_key(comment)
        current.add(key)
        marker_text = f"<!-- sentinel-finding:{key} -->"
        body = comment["body"] + f"\n\nReviewed at `{head}`.\n" + marker_text
        previous = next((item for item in reversed(existing.get(key, []))
                         if item.get("line") == comment["line"] and item.get("path") == comment["path"]), None)
        if previous:
            # PATCH changes text only. Outdated anchors receive a new current comment.
            endpoint = url.split("/pulls/")[0] + f"/pulls/comments/{previous['id']}"
            response = requests.patch(endpoint, json={"body": body}, headers=headers, timeout=30)
            response.raise_for_status()
        else:
            new.append({**comment, "body": body})
    if complete:
        for key in existing.keys() - current:
            for previous in existing[key]:
                suffix = "\n\n_Not retained in the latest completed review; see the current report._"
                if suffix not in previous["body"]:
                    endpoint = url.split("/pulls/")[0] + f"/pulls/comments/{previous['id']}"
                    response = requests.patch(endpoint, json={"body": previous["body"] + suffix}, headers=headers, timeout=30)
                    response.raise_for_status()
    return new
