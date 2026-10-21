"""Filesystem snapshot and non-destructive restore test inside the LOCAL OpenSearch container."""

import subprocess

CODE = """
import httpx, uuid
with httpx.Client(base_url="http://opensearch:9200",timeout=120) as client:
    client.put("/_snapshot/local-backups",json={"type":"fs","settings":{"location":"/usr/share/opensearch/data/snapshots"}}).raise_for_status()
    suffix=uuid.uuid4().hex[:12]
    snapshot="verify-"+suffix
    client.post("/security-events-*/_refresh").raise_for_status()
    before=client.get("/security-events-*/_count").json()["count"]
    client.put("/_snapshot/local-backups/"+snapshot,params={"wait_for_completion":"true"},json={"indices":"security-events-*","include_global_state":False}).raise_for_status()
    prefix="restore-"+suffix+"-"
    try:
        result=client.post("/_snapshot/local-backups/"+snapshot+"/_restore",params={"wait_for_completion":"true"},json={"indices":"security-events-*","include_global_state":False,"rename_pattern":"(.+)","rename_replacement":prefix+"$1"})
        result.raise_for_status()
        client.post("/"+prefix+"*/_refresh").raise_for_status()
        after=client.get("/"+prefix+"*/_count").json()["count"]
        assert before==after
        print({"snapshot":snapshot,"original_events":before,"restored_events":after})
    finally:
        names=client.get("/_cat/indices/"+prefix+"*",params={"format":"json","h":"index"}).json()
        for row in names:
            if row["index"].startswith(prefix):
                client.delete("/"+row["index"]).raise_for_status()
"""
if __name__ == "__main__":
    subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", CODE], check=True)
