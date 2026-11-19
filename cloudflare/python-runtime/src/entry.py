from workers import Response, WorkerEntrypoint

from runtime import build_verified_artifact, verify_execution_request


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if request.method != "POST" or request.url.split("?", 1)[0].endswith("/internal/execute") is False:
            return Response("Not found", status=404)
        try:
            raw = await request.array_buffer()
            body = bytes(raw)
            payload = verify_execution_request(
                body,
                request.headers.get("x-aae-execution-timestamp", ""),
                request.headers.get("x-aae-execution-signature", ""),
                self.env.AAE_EXECUTION_BRIDGE_SECRET,
            )
            artifact, digest, qa = build_verified_artifact()
            headers = {
                "content-type": "application/zip",
                "cache-control": "no-store",
                "x-aae-job-id": payload["job_id"],
                "x-aae-sha256": digest,
                "x-aae-size": str(len(artifact)),
                "x-aae-qa": "passed",
            }
            return Response(artifact, status=200, headers=headers)
        except Exception:
            # Never return source paths, secrets, or internal exception details.
            return Response('{"error":"execution rejected"}', status=400, headers={"content-type":"application/json","cache-control":"no-store"})
