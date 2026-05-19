from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


OPENCLAW_DIR = Path(os.environ.get("OPENCLAW_DIR", "/root/autodl-tmp/external/openclaw"))
_MODEL_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{1,120}$")
_MODEL_REF_EMBEDDED_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,120}")


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _extract_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    best: dict[str, Any] | None = None
    best_score = -1
    best_end = -1
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, end = decoder.raw_decode(text[idx:])
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        score = 0
        if "payloads" in obj:
            score += 10
        if "meta" in obj:
            score += 10
        meta = obj.get("meta")
        if isinstance(meta, dict) and "executionTrace" in meta:
            score += 30
        if isinstance(meta, dict) and "agentMeta" in meta:
            score += 10
        if score > best_score or (score == best_score and end > best_end):
            best = obj
            best_score = score
            best_end = end
    if best is None:
        raise ValueError("no JSON object found")
    return best


def _run_cmd(args: list[str], *, cwd: Path, timeout: int = 20) -> tuple[int, str, str]:
    proc = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _try_openclaw_config_get(target: str) -> tuple[Any | None, str | None]:
    commands = [
        ["node", "openclaw.mjs", "config", "get", target],
        ["pnpm", "openclaw", "config", "get", target],
    ]
    last_err = None
    for cmd in commands:
        exe = cmd[0]
        if shutil.which(exe) is None:
            continue
        try:
            code, out, err = _run_cmd(cmd, cwd=OPENCLAW_DIR, timeout=20)
        except Exception as exc:
            last_err = repr(exc)
            continue
        if code != 0:
            last_err = (err or out or f"nonzero_returncode_{code}").strip()
            continue
        txt = out.strip() or err.strip()
        try:
            return json.loads(out), None
        except Exception:
            try:
                return _extract_json_object(txt), None
            except Exception as exc:
                last_err = repr(exc)
                continue
    return None, last_err or f"unable_to_read_config:{target}"


def _looks_like_model_ref(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if value.startswith("./") or value.startswith("../"):
        return False
    if not _MODEL_REF_RE.match(value):
        return False
    return any(sep in value for sep in ["/", ".", "-"])


def _record_ref(refs: set[str], source_counts: dict[str, int], source: str, value: str | None) -> None:
    if isinstance(value, str) and value:
        refs.add(value)
        source_counts[source] = source_counts.get(source, 0) + 1


def _collect_model_refs_from_agents_config(data: Any) -> tuple[set[str], list[dict[str, Any]]]:
    refs: set[str] = set()
    source_counts: dict[str, int] = {}

    if isinstance(data, dict):
        defaults = data.get("defaults")
        if isinstance(defaults, dict):
            model = defaults.get("model")
            if isinstance(model, dict):
                _record_ref(refs, source_counts, "config:get agents defaults.model.primary", model.get("primary") if isinstance(model.get("primary"), str) else None)
                fallbacks = model.get("fallbacks")
                if isinstance(fallbacks, list):
                    for item in fallbacks:
                        _record_ref(refs, source_counts, "config:get agents defaults.model.fallbacks", item if isinstance(item, str) else None)
            elif isinstance(model, str):
                _record_ref(refs, source_counts, "config:get agents defaults.model", model)

        agents = data.get("list")
        if isinstance(agents, list):
            for item in agents:
                if not isinstance(item, dict):
                    continue
                model = item.get("model")
                if isinstance(model, str):
                    _record_ref(refs, source_counts, "config:get agents list[*].model", model)
                elif isinstance(model, dict):
                    _record_ref(refs, source_counts, "config:get agents list[*].model.primary", model.get("primary") if isinstance(model.get("primary"), str) else None)
                    fallbacks = model.get("fallbacks")
                    if isinstance(fallbacks, list):
                        for fb in fallbacks:
                            _record_ref(refs, source_counts, "config:get agents list[*].model.fallbacks", fb if isinstance(fb, str) else None)

    sources = [{"source": source, "count": count} for source, count in sorted(source_counts.items())]
    return refs, sources


def _collect_model_refs_from_plugin_json(obj: Any, *, path: tuple[str, ...] = ()) -> set[str]:
    refs: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            lower = key.lower() if isinstance(key, str) else ""
            child_path = (*path, lower)
            if lower in {"model", "models", "primary", "provider", "providers", "defaults", "fallbacks"}:
                refs |= _collect_model_refs_from_plugin_json(value, path=child_path)
            else:
                refs |= _collect_model_refs_from_plugin_json(value, path=child_path)
    elif isinstance(obj, list):
        for item in obj:
            refs |= _collect_model_refs_from_plugin_json(item, path=path)
    elif isinstance(obj, str):
        if _looks_like_model_ref(obj):
            refs.add(obj)
        else:
            # Some plugin catalogs mention valid model refs in explanatory text.
            # Only accept embedded refs with an explicit provider separator to
            # avoid broadening matching to arbitrary words.
            for m in _MODEL_REF_EMBEDDED_RE.finditer(obj):
                token = m.group(0).strip(".,;:!?)(")
                if "/" not in token:
                    continue
                if _looks_like_model_ref(token):
                    refs.add(token)
    return refs


def _collect_model_refs_from_plugins(openclaw_dir: Path) -> tuple[set[str], list[dict[str, Any]]]:
    refs: set[str] = set()
    sources: list[dict[str, Any]] = []
    ext_root = openclaw_dir / "dist" / "extensions"
    if not ext_root.exists():
        return refs, sources
    for plugin_path in sorted(ext_root.glob("*/openclaw.plugin.json")):
        try:
            payload = json.loads(plugin_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        plugin_refs = _collect_model_refs_from_plugin_json(payload)
        if plugin_refs:
            refs |= plugin_refs
            sources.append({"source": f"plugin:{plugin_path.relative_to(openclaw_dir)}", "count": len(plugin_refs)})
    return refs, sources


def _discover_known_model_refs(openclaw_dir: Path = OPENCLAW_DIR) -> tuple[set[str] | None, list[dict[str, Any]], str, str | None]:
    refs: set[str] = set()
    sources: list[dict[str, Any]] = []
    errors: list[str] = []

    agents_data, err = _try_openclaw_config_get("agents")
    if agents_data is not None:
        agent_refs, agent_sources = _collect_model_refs_from_agents_config(agents_data)
        refs |= agent_refs
        sources.extend(agent_sources)
    else:
        errors.append(f"agents:{err}")

    defaults_data, err = _try_openclaw_config_get("defaults")
    if defaults_data is not None:
        default_refs, default_sources = _collect_model_refs_from_agents_config({"defaults": defaults_data, "list": []})
        refs |= default_refs
        sources.extend(default_sources)
    else:
        errors.append(f"defaults:{err}")

    plugin_refs, plugin_sources = _collect_model_refs_from_plugins(openclaw_dir)
    refs |= plugin_refs
    sources.extend(plugin_sources)

    if refs:
        return refs, sources, "ok", None
    return None, sources, f"catalog_unavailable:{';'.join(errors) if errors else 'no_refs_discovered'}", (
        "no model refs could be discovered from OpenClaw config/catalog"
    )


def _suggest_model_ref(provider_model: str, known_refs: set[str]) -> str | None:
    if provider_model in known_refs:
        return provider_model
    if provider_model.startswith("relay/"):
        stripped = provider_model[len("relay/"):]
        if stripped in known_refs:
            return stripped
        prefixed = f"qwen/{stripped}"
        if prefixed in known_refs:
            return prefixed
        stripped_suffix_matches = [ref for ref in known_refs if ref.endswith(f"/{stripped}")]
        if len(stripped_suffix_matches) == 1:
            return stripped_suffix_matches[0]
    else:
        relay_candidate = f"relay/{provider_model}"
        if relay_candidate in known_refs:
            return relay_candidate
    suffix_matches = [ref for ref in known_refs if ref.endswith(provider_model)]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    if not provider_model.startswith("relay/"):
        suffix_matches = [ref for ref in known_refs if ref.split("/", 1)[-1] == provider_model]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
    return None


def _classify_static_provider_model(provider_model: str | None, known_refs: set[str] | None, catalog_status: str) -> tuple[str, str, str | None]:
    if not provider_model or not str(provider_model).strip():
        return "unknown", "provider_model_missing", None
    if known_refs is None:
        return "unknown", "catalog_unavailable", None
    provider_model = str(provider_model).strip()
    if provider_model in known_refs:
        return "true", "exact_match_in_known_refs", provider_model
    suggested = _suggest_model_ref(provider_model, known_refs)
    if provider_model.startswith("relay/") and suggested is not None:
        stripped = provider_model[len("relay/"):]
        if suggested == stripped or suggested.endswith(f"/{stripped}"):
            return "true", f"canonical_alias_match={suggested}", suggested
    if suggested is not None:
        return "false", f"likely_match_suggested={suggested}", suggested
    return "false", "not_found_in_known_refs", None


def _provider_route_status(requested_provider_model: str | None, execution_trace: Any) -> tuple[str, str | None, str | None]:
    if not isinstance(execution_trace, dict):
        return "unknown", None, None
    actual_provider = execution_trace.get("winnerProvider")
    actual_model = execution_trace.get("winnerModel")
    if not isinstance(actual_provider, str) or not isinstance(actual_model, str):
        return "unknown", actual_provider if isinstance(actual_provider, str) else None, actual_model if isinstance(actual_model, str) else None
    if not requested_provider_model:
        return "unknown", actual_provider, actual_model
    req = requested_provider_model.lower()
    req_token = req.split("/", 1)[-1]
    ap = actual_provider.lower()
    am = actual_model.lower()
    if req_token in am or req_token in ap:
        return "matched", actual_provider, actual_model
    return "mismatch", actual_provider, actual_model


def _run_real(provider_model: str, timeout: int) -> dict:
    cmd = [
        "openclaw",
        "agent",
        "--local",
        "--json",
        "--agent",
        "main",
        "--model",
        provider_model,
        "--message",
        "Reply exactly ROUTE_OK.",
        "--timeout",
        str(timeout),
    ]
    proc = subprocess.run(
        cmd,
        cwd=OPENCLAW_DIR,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout + 20,
    )
    stdout_tail = (proc.stdout or "")[-2000:]
    stderr_tail = (proc.stderr or "")[-2000:]
    response = None
    if proc.returncode == 0:
        try:
            response = _extract_json_object((proc.stdout or "") + "\n" + (proc.stderr or ""))
        except Exception:
            response = None
    execution_trace = None
    if isinstance(response, dict):
        meta = response.get("meta")
        if isinstance(meta, dict):
            execution_trace = meta.get("executionTrace")
    status, actual_provider, actual_model = _provider_route_status(provider_model, execution_trace)
    success = bool(proc.returncode == 0 and status == "matched")
    errors = []
    if proc.returncode != 0:
        errors.append(f"openclaw_returncode={proc.returncode}")
    if status in {"mismatch", "unknown"}:
        errors.append(f"provider_route_status={status}")
    return {
        "requested_provider_model": provider_model,
        "actual_provider": actual_provider,
        "actual_model": actual_model,
        "provider_route_status": status,
        "openclaw_returncode": proc.returncode,
        "success": success,
        "errors": errors,
        "stderr_tail": stderr_tail,
        "stdout_tail": stdout_tail,
    }


def validate_models(models_path: Path, *, limit: int | None, real: bool, timeout: int) -> dict:
    cfg = _load_yaml(models_path)
    models = cfg.get("models", []) if isinstance(cfg, dict) else []
    if not isinstance(models, list):
        raise ValueError("models yaml must contain a models list")

    selected = models[:limit] if isinstance(limit, int) and limit > 0 else models
    known_refs, sources, catalog_status, catalog_error = _discover_known_model_refs() if not real else (None, [], "not_used_in_real_mode", None)

    entries = []
    for idx, item in enumerate(selected, start=1):
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        agent_id = item.get("agent_id")
        provider_model = item.get("provider_model")
        executor = item.get("executor")
        rec = {
            "index": idx,
            "id": model_id,
            "agent_id": agent_id,
            "provider_model": provider_model,
            "executor": executor,
            "valid_executor": executor == "openclaw-minimal",
            "provider_model_nonempty": isinstance(provider_model, str) and bool(provider_model.strip()),
        }
        if not rec["valid_executor"]:
            rec["validation_error"] = "executor_must_be_openclaw-minimal"
        if not rec["provider_model_nonempty"]:
            rec["validation_error"] = "provider_model_missing"

        if real and rec["valid_executor"] and rec["provider_model_nonempty"]:
            rec["real"] = _run_real(str(provider_model), timeout)
        else:
            static_known, notes, suggested = _classify_static_provider_model(str(provider_model or ""), known_refs, catalog_status)
            rec["static_known"] = static_known
            rec["notes"] = notes
            rec["suggested_model_ref"] = suggested
        entries.append(rec)

    return {
        "schema_version": "openclaw_model_route_validation_v1",
        "mode": "real" if real else "static",
        "models_path": str(models_path),
        "catalog_status": catalog_status,
        "catalog_error": catalog_error,
        "known_model_ref_count": len(known_refs) if known_refs is not None else 0,
        "known_model_ref_sources": sources,
        "expected_model_count": len(selected),
        "model_count": len(entries),
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="configs/models/openclaw_relay_current.yaml")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", default="logs/openclaw_model_route_validation.json")
    args = parser.parse_args()

    data = validate_models(Path(args.models), limit=args.limit, real=args.real, timeout=args.timeout)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote route validation: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
