#!/usr/bin/env python3
"""Validate and extract Kustomize-generated tracing ConfigMap data.

Feed the concatenated JSON objects emitted by:
  kubectl create --dry-run=client -f rendered.yaml -o json
"""

import argparse
import hashlib
import json
import pathlib
import sys


COMPONENTS = {
    "otel-collector": ("otel-collector-config-", "collector.yaml"),
    "jaeger": ("jaeger-config-", "jaeger.yaml"),
}


def decode_stream(payload):
    decoder = json.JSONDecoder()
    offset = 0
    objects = []
    while offset < len(payload):
        while offset < len(payload) and payload[offset].isspace():
            offset += 1
        if offset == len(payload):
            break
        item, offset = decoder.raw_decode(payload, offset)
        if item.get("kind") == "List":
            objects.extend(item.get("items", []))
        else:
            objects.append(item)
    return objects


def named(objects, kind, name):
    matches = [
        item
        for item in objects
        if item.get("kind") == kind and item.get("metadata", {}).get("name") == name
    ]
    assert len(matches) == 1, "expected one {}/{}; found {}".format(kind, name, len(matches))
    return matches[0]


def generated_config_map(objects, prefix):
    matches = [
        item
        for item in objects
        if item.get("kind") == "ConfigMap"
        and item.get("metadata", {}).get("name", "").startswith(prefix)
    ]
    assert len(matches) == 1, "expected one generated ConfigMap with prefix {!r}; found {}".format(
        prefix, len(matches)
    )
    config_map = matches[0]
    assert config_map.get("metadata", {}).get("namespace") == "observability"
    assert config_map["metadata"]["name"] != prefix.rstrip("-")
    return config_map


def deployment_config_ref(deployment):
    volumes = deployment["spec"]["template"]["spec"].get("volumes", [])
    matches = [volume for volume in volumes if volume.get("name") == "config"]
    assert len(matches) == 1, "deployment must have one config volume"
    return matches[0]["configMap"]["name"]


def validate_component_config(config, key):
    assert config, "{} is empty".format(key)
    forbidden = ("apiVersion:", "kind:", "metadata:", "data:")
    top_level = [line for line in config.splitlines() if line and not line[0].isspace()]
    wrapped = sorted(line for line in top_level if line.startswith(forbidden))
    assert not wrapped, "{} contains a Kubernetes wrapper: {}".format(key, wrapped)
    if key == "collector.yaml":
        assert config.startswith("receivers:\n")
        assert "exporters:\n" in config
    else:
        assert config.startswith("extensions:\n")
        assert "receivers:\n" in config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=pathlib.Path)
    args = parser.parse_args()

    objects = decode_stream(sys.stdin.read())
    assert len(objects) == 9, "expected nine rendered resources; found {}".format(len(objects))

    extracted = {}
    for deployment_name, (prefix, key) in COMPONENTS.items():
        config_map = generated_config_map(objects, prefix)
        assert set(config_map.get("data", {})) == {key}
        config = config_map["data"][key]
        validate_component_config(config, key)

        deployment = named(objects, "Deployment", deployment_name)
        assert deployment.get("metadata", {}).get("namespace") == "observability"
        assert deployment_config_ref(deployment) == config_map["metadata"]["name"]
        extracted[key] = config

    if args.output_dir:
        assert args.output_dir.is_dir(), "output directory must already exist"
        for key, config in extracted.items():
            (args.output_dir / key).write_text(config, encoding="utf-8")

    for key in sorted(extracted):
        digest = hashlib.sha256(extracted[key].encode("utf-8")).hexdigest()
        print("PASS {} sha256:{}".format(key, digest))


if __name__ == "__main__":
    main()
