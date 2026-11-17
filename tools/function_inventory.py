#!/usr/bin/env python3
"""Inventory of the system-library functions this repository declares.

For every function tools/progress.py counts under core/libs/prx/<library>, write
one row with the library, the name, its NID, the definition's signature, the
state the progress scanner gives it, how many test sources name it and whether
the library's technical-debt file names it. The rows describe the repository,
not the console: a function no library declares is absent, and a function is
"implemented" when its body does not reach NotImplemented_nid_no_patch, which
says nothing about whether the behaviour matches the console.

The reference, proprietary and importance columns are assigned per library from
the tables in this file. They are a reading aid, not a per-function review.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import nid_names
import progress

ROOT = Path(__file__).resolve().parent.parent
POSTFIXES = ("_nid_postfix", "_nid_no_patch_cut", "_nid_no_patch")
SIGNATURE = re.compile(r"(?P<result>[\w:<>,*&\s]*?)\bAPS5_VABI\s+(?P<name>\w+)\s*\((?P<parameters>[^;{]*)\)\s*(?:noexcept\s*)?(?:->\s*[^;{]+)?(?:try\s*)?\{")
EXPLICIT_EXPORT = re.compile(r'\bAPS5_EXPORT\s*\(\s*"([A-Za-z0-9+\-]{11})"\s*,\s*(\w+)\s*\)')
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
TEST_SUFFIXES = {".cpp", ".hpp", ".h", ".c", ".py", ".mjs", ".js"}

STATES = ("implemented", "inert", "pending")
CATEGORIES = (
    "implemented_tested",
    "implemented_documented_gap",
    "implemented_untested",
    "inert",
    "pending",
    "pending_unknown_name",
)

REFERENCES = (
    (r"libc|libSceLibcInternal|libScePosix|libSceLibm", "ISO C, POSIX and FreeBSD libc"),
    (r"libkernel|libkernel_sys|libkernel_web|libScePthread", "FreeBSD kernel and libthr, POSIX"),
    (r"libSceLibreSsl\d*|libSceSsl\d*", "LibreSSL and Mbed TLS sources"),
    (r"libSceIcu|libicu.*", "ICU sources"),
    (r"libSceFreeType.*|libSceFont.*", "FreeType sources"),
    (r"libharfbuzz|libSceHarfbuzz.*", "HarfBuzz sources"),
    (r"libSceNKWebKit.*|libSceJsc.*|libSceWebKit.*|libSceWeb$", "WebKit sources"),
    (r"libwebrtc|libSceWebrtc.*", "WebRTC sources"),
    (r"libcurl|libSceCurl.*", "curl sources"),
    (r"libSceZlib|libz|libpng|libSceLibPng.*|libSceJpeg.*|libScePng.*", "zlib, libpng and libjpeg sources"),
    (r"libSceVorbisDec|libSceOpus.*|libSceAjm.*|libSceAudiodec.*", "Xiph and codec sources"),
    (r"libcairo|libSceCairo.*|libpixman", "cairo and pixman sources"),
    (r"libSceXml.*|libxml2|libSceSqlite.*|libsqlite.*", "libxml2 and SQLite sources"),
    (r"libSceHttp2|libnghttp2", "nghttp2 sources, RFC 9113"),
    (r"libSceNet$|libSceNetCtl|libSceHttp$", "BSD sockets and HTTP RFCs for the wrapped parts"),
    (r"libSceAgc.*|libSceGnm.*", "AMD GPU register and ISA documentation, Mesa"),
)

PROPRIETARY = (
    (r"libSceNp.*|libSceNpToolkit.*|Party|libSceParty.*|libSceGameLiveStreaming|libSceShare.*|libSceSocialScreen.*|libSceRemoteplay.*|libSceSigninDialog|libSceCommerce.*|libSceIpmi|libSceVsh.*|libSceBgft.*|libSceEntitlement.*|libSceNpEntitlement.*|libSceAbstract.*|libSceMessages.*|libSceActivity.*|libSceUniversalDataSystem.*|libSceMatching.*", "PlayStation Network or system service"),
    (r"libSceHmd.*|libSceVr.*|libSceMove.*|libSceCamera.*|libSceDepth.*|libScePadTracker|libSceHand.*|libMozaSDK|libSceUsbd|libSceBluetooth.*|libSceVideoRecording|libSceMouse|libSceKeyboard|libSceVoice.*|libSceAudioIn|libSceHidControl", "console peripheral or sensor hardware"),
    (r"libAacs|libCprm|libCss|libSceBdjava.*|libSceBluray.*|libSceDiscMap|libSceVdec.*|libSceVideodec.*|libSceAvcap.*|libSceHdmi.*|libSceDseehx|libSceS3da|libSceAc3Enc|libSceDtsEnc|libSceDolby.*", "licensed media, DRM or codec component"),
    (r"libSceSysCore|libSceSysUtil.*|libSceRegMgr|libSceKernelForVsh|libSceFsInternalForVsh|libSceSystemStateMgr|libSceMbus.*|libSceShellCoreUtil|libSceLncUtil|libSceAppInstUtil|libSceDevUsb|libSceDeci.*|libSceDbg.*|libSceAddressSanitizer|libSceFios2Debug", "console-internal or development facility"),
)

IMPORTANCE = (
    (r"libkernel|libkernel_sys|libc|libSceLibcInternal|libSceAgc|libSceAgcDriver|libSceVideoOut|libSceAudioOut2?|libScePad|libSceUserService|libSceSystemService|libSceSysmodule|libSceSaveData.*|libSceFiber|libSceAmpr|libSceRtc|libSceNet|libSceNetCtl|libSceAjm.*|libSceNgs2.*|libSceAudio3d|libSceGnmDriver|libScePosix|libSceFios2|libSceRandom|libSceIme.*|libSceMsgDialog|libSceCommonDialog|libSceErrorDialog|libSceNpManager|libSceNpTrophy2?|libSceNpUniversalDataSystem|libSceAppContent|libScePlayGo|libSceAvPlayer.*|libSceVideodec2|libSceJobManager|libSceRazorCpu|libSceHttp2?|libSceSsl2?|libSceJson2?|libSceFont.*|libSceFreeType.*", "core: reached by ordinary titles"),
    (r"libSceNKWebKit.*|libSceJsc.*|libSceIcu|libwebrtc|libSceNpCppWebApi|libSceNp.*|libSceLibreSsl\d*|libharfbuzz|libcurl|libcairo|libSceVoice.*|libSceMove.*|libSceHmd.*|libSceCamera.*|libSceVr.*|libSceUsbd|libSceGameLiveStreaming|libSceShare.*", "optional: middleware, network service or peripheral"),
)


def lookup(table, library, default):
    for pattern, value in table:
        if re.fullmatch(pattern, library):
            return value
    return default


def canonical(name):
    stripped = nid_names.strip_nid_postfix(name)
    for postfix in POSTFIXES:
        stripped = stripped.removesuffix(postfix)
    return stripped


def library_sources(path):
    for source in sorted(path.rglob("*.cpp")):
        if "tests" not in source.relative_to(path).parts:
            yield source


def signatures(path):
    found, explicit = {}, {}
    for source in library_sources(path):
        raw = source.read_text(encoding="utf-8", errors="ignore")
        for match in SIGNATURE.finditer(progress.code(raw)):
            result = " ".join(match.group("result").split()).rpartition(";")[2].rpartition("}")[2].strip()
            parameters = " ".join(match.group("parameters").split())
            found.setdefault(match.group("name"), (result, parameters, source))
        for nid, name in EXPLICIT_EXPORT.findall(raw):
            explicit.setdefault(name, nid)
    return found, explicit


def identifier_index(files):
    index = Counter()
    for file in files:
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        index.update(set(IDENTIFIER.findall(text)))
    return index


def test_sources(root):
    libraries = root / "core" / "libs"
    if not libraries.is_dir():
        return
    for file in libraries.rglob("*"):
        if file.suffix in TEST_SUFFIXES and "tests" in file.relative_to(libraries).parts and file.is_file():
            yield file


def debt_identifiers(root, library):
    file = root / "docs" / "dev" / "debt" / f"{library}.md"
    if not file.is_file():
        return set()
    return set(IDENTIFIER.findall(file.read_text(encoding="utf-8", errors="ignore")))


def category(state, unknown_name, tests, debt):
    if state == "pending":
        return "pending_unknown_name" if unknown_name else "pending"
    if state == "inert":
        return "inert"
    if debt:
        return "implemented_documented_gap"
    return "implemented_tested" if tests else "implemented_untested"


def library_rows(root, path, tests):
    group = progress.scan_library(path)
    owner = group.get("shared_sources")
    if owner:
        return [], owner
    found, explicit = signatures(path)
    debt = debt_identifiers(root, path.name)
    inert = set(group["inert_names"])
    reference = lookup(REFERENCES, path.name, "")
    proprietary = lookup(PROPRIETARY, path.name, "")
    importance = lookup(IMPORTANCE, path.name, "other: library-specific")
    rows = []
    for state_names, pending in ((group["done_names"], False), (group["todo_names"], True)):
        for name in state_names:
            bare = canonical(name)
            state = "pending" if pending else "inert" if name in inert else "implemented"
            unknown_name = "unknown" in bare.lower() and name in explicit
            result, parameters, source = found.get(name, ("", None, None))
            named = tests[name] + (tests[bare] if bare != name else 0)
            documented = bare in debt or name in debt
            standard = bool(reference) and not re.match(r"_?sce[A-Z]", bare)
            rows.append({
                "library": path.name,
                "name": bare,
                "symbol": name,
                "nid": explicit.get(name) or nid_names.compute_nid(bare),
                "nid_source": "explicit" if name in explicit else "computed from the name",
                "state": state,
                "category": category(state, unknown_name, named, documented),
                "result": result,
                "parameters": "" if parameters is None else parameters,
                "signature_known": "no" if unknown_name or parameters is None or (pending and parameters in ("", "void")) else "yes",
                "tests": named,
                "debt": "yes" if documented else "no",
                "reference": reference if standard else "",
                "proprietary": proprietary,
                "console_needed": "no" if standard and not proprietary else "yes",
                "importance": importance,
                "source": "" if source is None else source.relative_to(root).as_posix(),
            })
    return rows, None


def collect(root, modules=None):
    prx = root / "core" / "libs" / "prx"
    tests = identifier_index(test_sources(root))
    rows, shared, empty = [], {}, []
    for path in sorted(item for item in prx.iterdir() if item.is_dir()):
        if modules and path.name not in modules:
            continue
        library, owner = library_rows(root, path, tests)
        if owner:
            shared[path.name] = owner
        elif not library:
            empty.append(path.name)
        rows.extend(library)
    return rows, shared, empty


def summarize(rows, shared, empty):
    libraries = {}
    for row in rows:
        states, categories = libraries.setdefault(row["library"], (Counter(), Counter()))
        states[row["state"]] += 1
        categories[row["category"]] += 1
    by_library = {name: {"states": {key: states[key] for key in STATES}, "categories": {key: categories[key] for key in CATEGORIES}}
                  for name, (states, categories) in sorted(libraries.items())}
    return {
        "functions": len(rows),
        "libraries_with_functions": len(libraries),
        "libraries_sharing_sources": dict(sorted(shared.items())),
        "libraries_without_functions": sorted(empty),
        "states": {key: sum(1 for row in rows if row["state"] == key) for key in STATES},
        "categories": {key: sum(1 for row in rows if row["category"] == key) for key in CATEGORIES},
        "signature_unknown": sum(1 for row in rows if row["signature_known"] == "no"),
        "unknown_names": sum(1 for row in rows if row["category"] == "pending_unknown_name"),
        "proprietary": dict(sorted(Counter(row["proprietary"] for row in rows if row["proprietary"]).items())),
        "with_public_reference": sum(1 for row in rows if row["reference"]),
        "console_needed": dict(sorted(Counter((row["console_needed"], row["state"]) for row in rows).items(), key=str)),
        "importance": {tier: {key: sum(1 for row in rows if row["importance"] == tier and row["state"] == key) for key in STATES}
                       for tier in sorted({row["importance"] for row in rows})},
        "by_library": by_library,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="source tree to scan instead of the one containing this script")
    parser.add_argument("--module", action="append", metavar="NAME", help="limit the scan to these core/libs/prx directories; repeat for several")
    parser.add_argument("--csv", type=Path, help="write one row per function to this file")
    parser.add_argument("--json", type=Path, help="write the summary to this file")
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    rows, shared, empty = collect(root, set(arguments.module) if arguments.module else None)
    summary = summarize(rows, shared, empty)
    summary["console_needed"] = {f"{needed} ({state})": count for (needed, state), count in summary["console_needed"].items()}
    if arguments.csv:
        with open(arguments.csv, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["library"])
            writer.writeheader()
            writer.writerows(rows)
    if arguments.json:
        arguments.json.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"libraries with functions {summary['libraries_with_functions']}, sharing sources {len(shared)}, without functions {len(empty)}")
    print(f"functions {summary['functions']}: " + ", ".join(f"{key} {value}" for key, value in summary["states"].items()))
    for key, value in summary["categories"].items():
        print(f"  {key} {value}")
    print(f"signature not established {summary['signature_unknown']}, with a public reference {summary['with_public_reference']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
