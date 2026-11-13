"""Isolated native custom-image probe; no product or ownership changes.

Recovered parser keys assetId/useDefaultImage select the native pack image.
The image download contract and normal-account admission remain separate.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "store-single-artwork-candidate.json"
IMAGE_TARGET = "/FUTPackImages/packs_backgrounds_5000011.png"
METADATA_TARGET = IMAGE_TARGET + ".cmmetadata"
IMAGE_SHA256 = "3a556a57eec02c466f9d3d022666835cf19bcc66c967b0f650f8d18a62615460"


@lru_cache(maxsize=8)
def _validate(raw):
    value = json.loads(raw)
    expected = {"version", "account", "definition", "asset_id"}
    if (
        type(value) is not dict or set(value) not in (
            expected, expected | {"manifest_stage"}, expected | {"manifest_stage", "image_path"},
        )
        or value["version"] != "store_single_artwork_probe_v1"
        or type(value["account"]) is not str
        or type(value["definition"]) is not str
        or type(value["asset_id"]) is not int
        or value["asset_id"] != 5000011
        or value.get("manifest_stage") not in (
            None, "empty_descriptor", "one_image_descriptor", "file_descriptor", "file_metadata", "file_image",
        )
        or ("image_path" in value and type(value["image_path"]) is not str)
        or (value.get("manifest_stage") == "file_image" and "image_path" not in value)
    ):
        raise ValueError("Unsupported isolated Store artwork probe")
    return value


@lru_cache(maxsize=2)
def _image(raw):
    if hashlib.sha256(raw).hexdigest() != IMAGE_SHA256:
        raise ValueError("Store probe image differs from unchanged supplied PNG")
    return raw


def candidate(account):
    account = Path(account).resolve()
    marker = account / MARKER
    if not marker.exists():
        return None
    if (
        ROOT / "reports" not in account.parents
        or account.name != "isolated-account"
        or not (account / ".lab-snapshot.json").is_file()
        or marker.is_symlink()
    ):
        raise ValueError("Store artwork probe requires an archived isolated account")
    value = deepcopy(_validate(marker.read_bytes()))
    if value["account"] != str(account):
        raise ValueError("Store artwork probe account differs")
    return value


def project(value, store, references):
    policy = candidate(store.path.parent)
    if policy is None:
        return value
    rows = []
    matched = False
    for row in value["purchase"]:
        row = dict(row)
        if references.get(row["id"]) == policy["definition"]:
            row.update(assetId=policy["asset_id"], useDefaultImage=False)
            matched = True
        rows.append(row)
    if not matched:
        raise ValueError("Store artwork probe definition is absent from catalog")
    return {**value, "purchase": rows}


def content_response_for(method, target, headers, body, account):
    """The captured ProtoHttp GET, held until an isolated probe is selected."""
    if (
        method != "GET" or target not in ("/UX.cmconfig", METADATA_TARGET, IMAGE_TARGET) or body
        or headers.get(b"host") != b"10.0.2.2:18081"
        or account is None
    ):
        return None
    policy = candidate(account)
    if policy is None or policy.get("manifest_stage") is None:
        return None
    from .identity import json_response
    if target == IMAGE_TARGET:
        if policy["manifest_stage"] != "file_image":
            return None
        path = Path(policy["image_path"])
        if path.is_symlink() or ROOT / "reports" not in path.resolve().parents:
            raise ValueError("Store probe image requires a separate reports artifact")
        raw = _image(path.read_bytes())
        return (
            b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nConnection: close\r\nContent-Length: "
            + str(len(raw)).encode() + b"\r\n\r\n" + raw
        )
    if target == METADATA_TARGET:
        if policy["manifest_stage"] not in ("file_metadata", "file_image"):
            return None
        # 00ebb0d4 parses this boolean. Checksum validation is the native
        # default-off configuration, observed separately; no hash guessed.
        return json_response({"encrypted": False})
    if policy["manifest_stage"] == "empty_descriptor":
        return json_response({"descFileVersion": "1.0.0", "contents": {}, "groups": {}})
    filename = "UTPackImages"
    version = "1.0.1"
    if policy["manifest_stage"] in ("file_descriptor", "file_metadata", "file_image"):
        filename = IMAGE_TARGET.rsplit("/", 1)[1]
        version = "1.0.4"
    return json_response({
        "descFileVersion": version,
        "contents": {
            filename: {
                "filename": filename,
                "baseUrl": (
                    "http://10.0.2.2:18081/FUTPackImages/"
                    if version == "1.0.4" else "http://10.0.2.2:18081/"
                ),
                "baseLocalPath": "",
            },
        },
        "groups": {},
    })
