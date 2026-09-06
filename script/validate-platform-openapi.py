#!/usr/bin/env python3
"""Validate the public OpenAPI contract against the Sanic platform routes."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs/api/openapi.yaml"
ROUTER_PATH = ROOT / "server/router/platform.py"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def route_inventory() -> set[tuple[str, str]]:
    tree = ast.parse(ROUTER_PATH.read_text(encoding="utf-8"), filename=str(ROUTER_PATH))
    class_methods: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_methods[node.name] = {
                child.name.lower()
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.lower() in HTTP_METHODS
            }

    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "add_route":
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant) or not isinstance(node.args[1].value, str):
            continue
        route = node.args[1].value
        if not route.startswith("/api/v1/"):
            continue
        view = node.args[0]
        if not isinstance(view, ast.Call) or not isinstance(view.func, ast.Attribute) or view.func.attr != "as_view":
            continue
        if not isinstance(view.func.value, ast.Name):
            continue
        class_name = view.func.value.id
        normalized = route
        parts = []
        for part in normalized.split("/"):
            if part.startswith("<") and part.endswith(">"):  # Sanic: <name:type>
                parts.append("{" + part[1:-1].split(":", 1)[0] + "}")
            else:
                parts.append(part)
        normalized = "/".join(parts)
        for method in class_methods.get(class_name, set()):
            routes.add((normalized, method))
    return routes


def local_ref_names(value: Any) -> Iterator[str]:
    for item in walk(value):
        if isinstance(item, dict) and isinstance(item.get("$ref"), str) and item["$ref"].startswith("#/"):
            yield item["$ref"]


def main() -> int:
    try:
        spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"cannot read OpenAPI document: {exc}", file=sys.stderr)
        return 1
    errors: list[str] = []
    if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3.1"):
        errors.append("openapi must be 3.1.x")
    if not isinstance(spec.get("info"), dict) or not spec["info"].get("version"):
        errors.append("info.version is required")
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        errors.append("paths must be an object")
        paths = {}
    schemas = spec.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict) or not schemas:
        errors.append("components.schemas must not be empty")

    for path, item in paths.items():
        if not path.startswith("/api/v1/"):
            errors.append(f"non-public path is documented: {path}")
            continue
        if not isinstance(item, dict):
            errors.append(f"path item is not an object: {path}")
            continue
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                errors.append(f"operation is not an object: {method.upper()} {path}")
                continue
            if not operation.get("operationId"):
                errors.append(f"missing operationId: {method.upper()} {path}")
            if not operation.get("responses"):
                errors.append(f"missing responses: {method.upper()} {path}")

    expected = route_inventory()
    documented = {
        (path, method)
        for path, item in paths.items()
        if isinstance(item, dict)
        for method in item
        if method in HTTP_METHODS
    }
    for path, method in sorted(expected - documented):
        errors.append(f"route missing from OpenAPI: {method.upper()} {path}")
    for path, method in sorted(documented - expected):
        errors.append(f"OpenAPI route missing from Sanic router: {method.upper()} {path}")

    for ref in local_ref_names(spec):
        pieces = ref[2:].split("/")
        current: Any = spec
        try:
            for piece in pieces:
                current = current[piece]
        except (KeyError, TypeError):
            errors.append(f"unresolved local reference: {ref}")

    if errors:
        print("platform OpenAPI validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"platform OpenAPI is valid: {len(documented)} public operations, {len(schemas)} schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
