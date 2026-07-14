from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any


def main() -> None:
    args = parse_args()
    client = ApiClient(args.base_url)
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    run_id = now.strftime("%Y%m%d%H%M%S")

    result: dict[str, Any] = {
        "run_id": run_id,
        "base_url": args.base_url,
        "started_at": now.isoformat(),
        "config": {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "synthetic_docs": args.synthetic_docs,
            "synthetic_repeat": args.synthetic_repeat,
            "top_k": args.top_k,
        },
        "before_stats": client.get("/similarity/stats").get("data", {}),
        "baseline": {},
        "synthetic": {},
        "created_document_ids": [],
    }

    documents = client.get("/similarity/documents/search?limit=10&offset=0").get("data", [])
    query_texts = build_queries(documents)
    document_ids = [str(item.get("document_id") or "") for item in documents if item.get("document_id")]

    result["baseline"] = run_suite(
        client,
        query_texts=query_texts,
        document_ids=document_ids,
        requests=args.requests,
        concurrency=args.concurrency,
        top_k=args.top_k,
    )

    created_ids: list[str] = []
    if args.synthetic_docs > 0:
        created_ids = create_synthetic_documents(client, run_id, args.synthetic_docs, args.synthetic_repeat)
        result["created_document_ids"] = created_ids
        result["after_insert_stats"] = client.get("/similarity/stats").get("data", {})
        synthetic_queries = build_synthetic_queries(run_id) + query_texts
        result["synthetic"] = run_suite(
            client,
            query_texts=synthetic_queries,
            document_ids=created_ids + document_ids,
            requests=args.requests,
            concurrency=args.concurrency,
            top_k=args.top_k,
        )
        if args.cleanup:
            result["cleanup"] = cleanup_documents(client, created_ids)
            result["after_cleanup_stats"] = client.get("/similarity/stats").get("data", {})

    result["finished_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="xcn-similarity API performance smoke benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--synthetic-docs", type=int, default=0)
    parser.add_argument("--synthetic-repeat", type=int, default=24)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--output", default="")
    return parser.parse_args()


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def get(self, path: str) -> dict[str, Any]:
        with urllib.request.urlopen(self.base_url + path, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))

    def delete(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(self.base_url + path, method="DELETE")
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))


def run_suite(
    client: ApiClient,
    *,
    query_texts: list[str],
    document_ids: list[str],
    requests: int,
    concurrency: int,
    top_k: int,
) -> dict[str, Any]:
    results = {
        "catalog_list": benchmark(
            "GET /similarity/documents/search",
            lambda i: client.get(f"/similarity/documents/search?limit=30&offset={0 if i % 2 == 0 else 30}"),
            requests=max(10, requests // 2),
            concurrency=min(concurrency, 4),
        ),
        "search_documents": benchmark(
            "POST /similarity/search/documents",
            lambda i: client.post_json(
                "/similarity/search/documents",
                {
                    "text": query_texts[i % len(query_texts)],
                    "top_k": top_k,
                    "min_score": 0.0,
                    "metadata_filter": {},
                },
            ),
            requests=requests,
            concurrency=concurrency,
        ),
        "search_logs_text": benchmark(
            "POST /similarity/search/logs/text",
            lambda i: client.post_json(
                "/similarity/search/logs/text",
                {
                    "text": query_texts[i % len(query_texts)],
                    "top_k": min(max(top_k, 10), 20),
                    "min_score": 0.0,
                    "metadata_filter": {},
                },
            ),
            requests=max(10, requests // 2),
            concurrency=min(concurrency, 3),
        ),
    }
    if document_ids:
        results["search_logs_by_document"] = benchmark(
            "POST /similarity/search/logs",
            lambda i: client.post_json(
                "/similarity/search/logs",
                {
                    "document_id": document_ids[i % len(document_ids)],
                    "top_k": min(max(top_k, 10), 50),
                    "min_score": 0.0,
                    "metadata_filter": {},
                },
            ),
            requests=max(10, requests // 2),
            concurrency=min(concurrency, 3),
        )
    return results


def benchmark(name: str, func, *, requests: int, concurrency: int) -> dict[str, Any]:
    started = time.perf_counter()
    samples: list[float] = []
    errors: list[str] = []

    def one(index: int) -> float:
        t0 = time.perf_counter()
        func(index)
        return (time.perf_counter() - t0) * 1000.0

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(one, i) for i in range(max(1, requests))]
        for future in as_completed(futures):
            try:
                samples.append(future.result())
            except Exception as exc:  # noqa: BLE001 - benchmark should capture errors.
                errors.append(str(exc))
    elapsed = time.perf_counter() - started
    samples.sort()
    return {
        "name": name,
        "requests": requests,
        "concurrency": concurrency,
        "errors": len(errors),
        "error_samples": errors[:5],
        "elapsed_sec": round(elapsed, 3),
        "rps": round((len(samples) / elapsed) if elapsed > 0 else 0.0, 3),
        "latency_ms": summarize(samples),
    }


def summarize(samples: list[float]) -> dict[str, float | int | None]:
    if not samples:
        return {"count": 0, "min": None, "p50": None, "p95": None, "p99": None, "max": None, "avg": None}
    return {
        "count": len(samples),
        "min": round(samples[0], 3),
        "p50": round(percentile(samples, 50), 3),
        "p95": round(percentile(samples, 95), 3),
        "p99": round(percentile(samples, 99), 3),
        "max": round(samples[-1], 3),
        "avg": round(statistics.mean(samples), 3),
    }


def percentile(samples: list[float], pct: float) -> float:
    if len(samples) == 1:
        return samples[0]
    rank = (len(samples) - 1) * (pct / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(samples) - 1)
    weight = rank - lower
    return samples[lower] * (1.0 - weight) + samples[upper] * weight


def build_queries(documents: list[dict[str, Any]]) -> list[str]:
    queries = []
    for doc in documents[:8]:
        title = str(doc.get("title") or "")
        metadata = doc.get("metadata") or {}
        file_name = str(metadata.get("file_name") or "")
        if title or file_name:
            queries.append(f"{title}\n{file_name}\n기밀 문서 유사도 검색 성능 측정")
    queries.extend(
        [
            "재난 안전 통신망 서버 운영 매뉴얼 장애 조치 보안 정책",
            "EMS 로그 첨부파일 외부 전송 내부정보 유출 유사도 분석",
            "관리자 계정 서버 구축 변경 이력 문서 보안 검토",
        ]
    )
    return queries or ["xcn similarity performance benchmark query"]


def build_synthetic_queries(run_id: str) -> list[str]:
    return [
        f"xcn synthetic performance document run {run_id} confidential gateway policy",
        f"xcn synthetic benchmark run {run_id} attachment leakage prevention",
        f"xcn synthetic vector search scale test {run_id} retention security",
    ]


def create_synthetic_documents(client: ApiClient, run_id: str, count: int, repeat: int) -> list[str]:
    created: list[str] = []
    base = (
        "xcn synthetic performance document "
        "confidential gateway policy attachment leakage prevention vector search benchmark "
    )
    for index in range(1, count + 1):
        text = (
            f"run_id={run_id} synthetic_doc={index}\n"
            + (base + f"unique_token_{run_id}_{index} ") * max(1, repeat)
        )
        payload = {
            "title": f"perf_{run_id}_{index:05d}",
            "text": text,
            "security_level": "일반",
            "metadata": {
                "source": "perf_test",
                "run_id": run_id,
                "synthetic": True,
                "file_retained": False,
                "sequence": index,
            },
        }
        body = client.post_json("/similarity/documents", payload)
        data = body.get("data") or {}
        if data.get("document_id"):
            created.append(str(data["document_id"]))
    return created


def cleanup_documents(client: ApiClient, document_ids: list[str]) -> dict[str, Any]:
    deleted = []
    errors = []
    for document_id in document_ids:
        try:
            client.delete(f"/similarity/documents/{urllib.parse.quote(document_id)}")
            deleted.append(document_id)
        except urllib.error.HTTPError as exc:
            errors.append(f"{document_id}: {exc.code}")
        except Exception as exc:  # noqa: BLE001 - cleanup should continue.
            errors.append(f"{document_id}: {exc}")
    return {"deleted": len(deleted), "errors": errors[:10]}


if __name__ == "__main__":
    main()
