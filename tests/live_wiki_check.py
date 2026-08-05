#!/usr/bin/env python3
"""
live_wiki_check.py — an opt-in, human-invoked check of the JSON-RPC deploy
transport against a REAL DokuWiki install.

WHY THIS FILE EXISTS AND IS NOT A unittest.TestCase: every other test in this
suite is offline by design — `_dokuwiki_rpc.RpcClient` takes an injectable
transport precisely so nothing here ever opens a socket, and the design spec
this pipeline implements says so explicitly: "no test touches the network;
CI never needs a live wiki." That posture is deliberately never broken. This
script is the escape hatch for the one thing a fake transport cannot prove:
that a *real* DokuWiki, with its own quirks (see the two bugs this script
was written to prevent from recurring, below), actually accepts what
bunnyforge sends it. It is discovered by nobody: `unittest discover`'s
default pattern is `test*.py`, and this file is named so it never matches —
verified by running the full suite before and after adding it and confirming
the count does not move.

WHAT IT PROVES. A first-time deployer configures `[wiki] url` and a token,
then runs this script to gain confidence *before* pointing the real
`deploy-export --go` at their campaign — the same way `check_portability.py`
lets a culture author gain confidence before publishing a name file. Two
genuine bugs were found this way during this feature's first live deploy
(both fixed, both now permanent assertions here so they can never silently
regress):

  1. `get_page()` on a missing page must return None. On the API v14 install
     this was verified against, a missing page comes back as an EMPTY STRING
     with a success error object, never the error code the original design
     assumed — see check 2 below.
  2. The credential must go out as `X-DokuWiki-Token`, not just
     `Authorization: Bearer` — some hosts run PHP as CGI/FastCGI and Apache
     strips the Authorization header before PHP ever sees it. This script
     does not re-test that directly (it is a header the client always sends,
     not something observable from here), but the very fact that check 1's
     handshake succeeds at all is live proof the credential got through.

WHAT IT DOES NOT PROVE. This tool cannot delete wiki pages, so this script
cannot either — it never claims to. It cannot check that the `~~NOTOC~~`
placeholder body actually *renders* blank; that needs a browser (see check
11). It is not exhaustive: it is the specific battery the human asked for,
built around one property that makes it safe to run repeatedly — see below.

SAFETY. Three separate guarantees, each load-bearing:

  - **Never runs by accident.** Checks 1-3 are read-only and always run.
    Checks 4-11 write to the wiki and run ONLY with the explicit --go flag,
    matching this package's dry-run/--go convention everywhere else.
  - **Never touches the operator's real deploy state.** The real
    `<workspace>/.bunnyforge/wiki-manifest.json` is a committed baseline for
    a real campaign; this script never opens it. Every write check builds
    its OWN temporary workspace — a throwaway `campaign.toml` copying only
    `namespace` and `[wiki] url` from the real one, and its own manifest —
    so nothing this script does can perturb the operator's real baseline.
    The credential travels via the `BUNNYFORGE_WIKI_TOKEN` environment
    variable, so the real token file is read once (to get the value) and
    never copied anywhere.
  - **Bounded, reusable footprint.** The tool cannot delete pages, so
    proliferation would be a real cost of re-running this script. Every
    write check uses a small number of STABLE page IDs under a
    `live-wiki-check` sub-path of the operator's own namespace, and running
    the whole script ten times in a row updates those same IDs in place
    rather than minting new ones each time — this is what makes checks 4-9
    (create, idempotent, edit, drift, overwrite, adopt) a coherent story
    instead of a pile of one-off pages. See the module-level PROBE_* names.

Usage:
    python3 tests/live_wiki_check.py --workspace PATH
        Read-only checks only (1-3): handshake, missing-page contract,
        protected-page guard. Writes nothing to the wiki.

    python3 tests/live_wiki_check.py --workspace PATH --go
        All checks (1-11), including the roundtrip-edit, drift-holdback,
        --overwrite, adopt, and empty-page/placeholder checks. Writes to
        the live wiki named in PATH/campaign.toml's [wiki] url.

PYTHONPATH=src is required, exactly as for the rest of the suite — a
published bunnyforge in site-packages otherwise shadows this working tree.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from bunnyforge import _config
from bunnyforge import deploy_export
from bunnyforge._dokuwiki import page_id as _page_id
from bunnyforge._dokuwiki_rpc import RpcClient, RpcError

# ---------------------------------------------------------------------------
# Stable probe identity. Everything this script writes lives under this one
# sub-path of the operator's own namespace, so a human who wants to clean up
# afterwards (this tool cannot: see the module docstring) knows exactly
# where to look, and re-running the script never mints a new page.
# ---------------------------------------------------------------------------

PROBE_DIR = "live-wiki-check"
PROBE_STEM = "probe"
PROBE_REL_PATH = f"{PROBE_DIR}/{PROBE_STEM}.md"

# Two source bodies for the same probe page. V1 is what checks 4/5 deploy and
# confirm; V2 is what check 6 (the roundtrip *edit*, as opposed to check 4's
# create) changes to and confirms again. Both are deliberately inert prose —
# nothing here should ever look like real campaign content to a passerby.
PROBE_BODY_V1 = (
    "# bunnyforge live-wiki-check probe\n\n"
    "This page is maintained by an opt-in diagnostic script "
    "(tests/live_wiki_check.py in the bunnyforge repository) that exercises "
    "the JSON-RPC deploy transport against this wiki installation. It is "
    "safe to ignore. Edits made directly on this page will be reported as "
    "drift the next time the script runs with --go.\n\n"
    "State marker: v1\n"
)
PROBE_BODY_V2 = (
    "# bunnyforge live-wiki-check probe\n\n"
    "This page is maintained by an opt-in diagnostic script "
    "(tests/live_wiki_check.py in the bunnyforge repository) that exercises "
    "the JSON-RPC deploy transport against this wiki installation. It is "
    "safe to ignore. Edits made directly on this page will be reported as "
    "drift the next time the script runs with --go.\n\n"
    "State marker: v2 -- this text proves the roundtrip EDIT path, not just "
    "the initial create.\n"
)

# What a human editing the probe directly on the wiki looks like, for the
# drift-holdback check (7). Deliberately unlike either body above, so a
# comparison failure is unambiguous about which text won.
MANUAL_EDIT_BODY = (
    "====== drifted ======\n\n"
    "Someone edited this page directly on the wiki, bypassing bunnyforge. "
    "If bunnyforge is working, this text survives the next deploy and is "
    "reported as held-back drift instead of being silently overwritten.\n"
)

# Actions plan_deploy can report that mean "held back, not written". Mirrors
# deploy_export's own private _HELD tuple; kept as a local literal rather than
# reaching into that module's underscore-prefixed name, since it is not part
# of the interface this script was asked to use.
_HELD_ACTIONS = frozenset({"drift", "drift-manual-era", "deleted-on-wiki"})

_DEPLOY_SUMMARY_RE = re.compile(r"Deployed (\d+) page\(s\), adopted (\d+)\.")


# ---------------------------------------------------------------------------
# Small helpers shared by the write checks
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Compare wiki text against rendered text ignoring only a trailing
    newline: DokuWiki normalizes that much on save (see deploy_export's own
    page_hash docstring), and comparing on anything more forgiving would
    risk masking a real content mismatch."""
    return text.rstrip("\n")


def _write_probe(export_dir: Path, body: str) -> None:
    dest = export_dir / PROBE_REL_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")


def _render_expected(export_dir: Path, ns: str) -> dict[str, str]:
    """What deploy_export would stage right now, computed independently of
    any actual deploy run. Used both to know what to compare live wiki
    content against, and (via plan_deploy below) to inspect a classification
    before ever invoking main()."""
    staging = Path(tempfile.mkdtemp(prefix="live-wiki-check-render-"))
    try:
        deploy_export.render_tree(export_dir, staging, base=ns)
        return deploy_export.staged_pages(staging)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _plan_now(export_dir: Path, ns: str, manifest_path: Path, client):
    """The plan deploy_export.main() would compute right now, without
    running it -- lets each check assert on a structured DeployPlan.action
    rather than scraping the CLI's printed report."""
    staged = _render_expected(export_dir, ns)
    manifest = deploy_export.load_manifest(manifest_path)
    plan = deploy_export.plan_deploy(staged, manifest, client.get_page, ns)
    return staged, plan


def _run_main(ws_root: Path, export_dir: Path, go: bool, overwrite=()):
    """Drive the real deploy_export CLI in-process, capturing its stdout and
    stderr so this script controls its own report and can surface the
    captured text when a check fails."""
    argv = ["--workspace", str(ws_root), "--export-dir", str(export_dir)]
    if go:
        argv.append("--go")
    for pid in overwrite:
        argv += ["--overwrite", pid]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = deploy_export.main(argv)
    return rc, out.getvalue(), err.getvalue()


class Ctx:
    """Bag of values every write check needs. A plain object rather than a
    namedtuple -- nothing here is ever reconstructed positionally."""

    def __init__(self, client, ns, ws_root, export_dir, manifest_path):
        self.client = client
        self.ns = ns
        self.ws_root = ws_root
        self.export_dir = export_dir
        self.manifest_path = manifest_path
        self.content_id = _page_id(PROBE_REL_PATH, f"{ns}:export")
        self.wrapper_id = _page_id(PROBE_REL_PATH, ns)
        self.players_id = _page_id(PROBE_REL_PATH, f"{ns}:players")


# ---------------------------------------------------------------------------
# Read-only checks (1-3) -- always run, never write to the wiki
# ---------------------------------------------------------------------------

def check_handshake(client: RpcClient) -> str:
    """1. Endpoint and auth handshake: core.getAPIVersion must succeed at
    all, which proves the URL is reachable, the endpoint exists, and both
    credential headers were accepted."""
    version = client.call("core.getAPIVersion", {})
    return f"core.getAPIVersion() -> {version!r}"


def check_missing_page_returns_none(client: RpcClient, ns: str) -> str:
    """2. get_page() on a page that cannot exist must return None. This is
    the exact assumption that was WRONG on the live install this transport
    was verified against (API v14 returns "" with a success error object,
    never error 121) -- worth asserting on every install, not just the one
    that first surfaced it."""
    missing_id = f"{ns}:{PROBE_DIR}:__this-page-must-never-exist__"
    result = client.get_page(missing_id)
    assert result is None, (
        f"get_page({missing_id!r}) returned {result!r}, not None. Either "
        "this page id has genuinely been created on the wiki (rename the "
        "check), or get_page's 'missing page' contract has regressed -- see "
        "_dokuwiki_rpc.RpcClient.get_page's docstring for the two shapes "
        "(error 121, or a success response whose result is empty) it must "
        "both treat as 'does not exist'.")
    return f"get_page({missing_id!r}) -> None, as expected"


def check_protected_guard(ns: str) -> str:
    """3. The protected-page guard: a staged page id equal to <ns>:main or
    under <ns>:players: must never be fetched and never be written, even if
    something upstream of plan_deploy staged it by mistake. Exercised
    entirely offline with a fake fetch that records every id it is called
    with -- no network needed, so this check runs even without --go."""
    calls: list[str] = []

    def fake_fetch(pid: str):
        calls.append(pid)
        return None

    protected_main = f"{ns}:main"
    protected_player_page = f"{ns}:players:some-players-page"
    ordinary = f"{ns}:{PROBE_DIR}:guard-contrast"
    staged = {
        protected_main: "must never be fetched or written",
        protected_player_page: "must never be fetched or written",
        ordinary: "an ordinary staged page, for contrast",
    }
    plan = deploy_export.plan_deploy(staged, {}, fake_fetch, ns)

    for pid in (protected_main, protected_player_page):
        assert pid not in calls, (
            f"the protected-page guard fetched {pid!r} -- it must never be "
            "fetched, let alone written")
        assert pid not in plan.pages, (
            f"{pid!r} appears in plan.pages -- the protected-page guard "
            "must exclude it entirely, not merely skip writing it")
        assert pid in plan.refused, (
            f"{pid!r} was not reported in plan.refused")
    assert ordinary in calls, (
        "the guard's contrast page was never fetched either -- this check "
        "would pass even if plan_deploy fetched nothing at all, so it "
        "proves nothing about the guard specifically")
    return (f"plan_deploy() never fetched or staged {protected_main!r} or "
            f"{protected_player_page!r} (both reported refused); an "
            f"ordinary page ({ordinary!r}) staged alongside them WAS "
            "fetched, ruling out a guard that simply fetches nothing")


# ---------------------------------------------------------------------------
# Write checks (4-11) -- only with --go
# ---------------------------------------------------------------------------

def check_create_or_update(ctx: Ctx) -> str:
    """4. Create or update the probe page -- the roundtrip the human
    specifically asked for. This script's temp manifest starts empty on
    EVERY invocation (by design: it must never persist across runs), so if
    the wiki already carries a probe page from an earlier invocation of this
    script, plan_deploy sees "no baseline, content differs" -- the same
    shape as manual-era drift. That is reconciled here with --overwrite
    (this script's own leftover test data, not a real editor's drift) so the
    check is robust to any starting state; the genuine day-to-day 'update'
    path is exercised for real by check 6 below, within a manifest this run
    itself created."""
    _write_probe(ctx.export_dir, PROBE_BODY_V1)
    staged, plan = _plan_now(ctx.export_dir, ctx.ns, ctx.manifest_path, ctx.client)
    content_action = plan.pages[ctx.content_id].action
    overwrite = [ctx.content_id] if content_action in _HELD_ACTIONS else []
    verb = ("reconciled (leftover content from an earlier run of this "
            "script)" if overwrite else content_action)

    rc, out, err = _run_main(ctx.ws_root, ctx.export_dir, go=True, overwrite=overwrite)
    assert rc == 0, (
        f"deploying the probe page failed unexpectedly (rc={rc}).\n"
        f"--- stdout ---\n{out}--- stderr ---\n{err}")

    wiki_text = ctx.client.get_page(ctx.content_id)
    expected = staged[ctx.content_id]
    assert wiki_text is not None and _norm(wiki_text) == _norm(expected), (
        f"after deploying the probe page ({verb}), the wiki content does "
        f"not match what was rendered.\nexpected:\n{expected!r}\n"
        f"wiki:\n{wiki_text!r}\n--- stdout ---\n{out}")
    return (f"probe page {verb} at {ctx.content_id}; wiki content matches "
            f"the rendered source ({len(expected)} bytes)")


def check_idempotent(ctx: Ctx) -> str:
    """5. Idempotency: deploying again immediately, with nothing changed,
    must write zero pages and classify every page 'unchanged'. This is also
    what proves the read-back-hash discipline (page_hash() hashes what
    get_page returns, never the bytes sent) -- hashing sent bytes instead
    would make every page look self-drifted on exactly this check."""
    _staged, plan_before = _plan_now(
        ctx.export_dir, ctx.ns, ctx.manifest_path, ctx.client)
    for pid in (ctx.content_id, ctx.wrapper_id):
        action = plan_before.pages[pid].action
        assert action == "unchanged", (
            f"expected {pid} to classify 'unchanged' before the idempotency "
            f"redeploy, got {action!r} -- either check 4 did not leave a "
            "clean baseline, or the wiki page changed between checks")

    rc, out, err = _run_main(ctx.ws_root, ctx.export_dir, go=True)
    assert rc == 0, (
        f"the idempotent redeploy failed (rc={rc}).\n"
        f"--- stdout ---\n{out}--- stderr ---\n{err}")
    m = _DEPLOY_SUMMARY_RE.search(out)
    assert m, f"could not find the deploy summary line in stdout:\n{out}"
    written, adopted = int(m.group(1)), int(m.group(2))
    assert written == 0, (
        f"a redeploy with no source change wrote {written} page(s); a "
        "second consecutive run should write zero, or the read-back hash "
        f"discipline has regressed.\n--- stdout ---\n{out}")
    return (f"redeploy with no source change wrote 0 page(s) (adopted "
            f"{adopted}); both probe pages classified 'unchanged' beforehand")


def check_roundtrip_edit(ctx: Ctx) -> str:
    """6. Roundtrip edit: change the probe's source and redeploy. This is
    the literal 'update an existing test page' case the human asked for,
    distinct from check 4's first-run create -- here the manifest this run
    itself built has a real baseline, so the classification is genuinely
    'update', not the reconciliation check 4 sometimes needs."""
    _write_probe(ctx.export_dir, PROBE_BODY_V2)
    staged, plan = _plan_now(ctx.export_dir, ctx.ns, ctx.manifest_path, ctx.client)
    action = plan.pages[ctx.content_id].action
    assert action == "update", (
        f"expected the content page to classify 'update' after changing its "
        f"source text, got {action!r}")

    rc, out, err = _run_main(ctx.ws_root, ctx.export_dir, go=True)
    assert rc == 0, (
        f"the roundtrip-edit redeploy failed (rc={rc}).\n"
        f"--- stdout ---\n{out}--- stderr ---\n{err}")
    wiki_text = ctx.client.get_page(ctx.content_id)
    expected = staged[ctx.content_id]
    assert wiki_text is not None and _norm(wiki_text) == _norm(expected), (
        "after redeploying with changed source, the wiki content does not "
        f"match the new render.\nexpected:\n{expected!r}\n"
        f"wiki:\n{wiki_text!r}\n--- stdout ---\n{out}")
    return ("changed the probe's source text and redeployed: classified "
            "'update'; wiki content now matches the new text")


def check_drift_holdback(ctx: Ctx) -> str:
    """7. Drift hold-back: edit the page directly on the wiki (bypassing
    bunnyforge entirely), then redeploy. Must hold the page back rather than
    clobber the manual edit, report a unified diff, write an inbound copy
    under wiki-drift/, and exit non-zero."""
    ctx.client.save_page(ctx.content_id, MANUAL_EDIT_BODY)
    assert ctx.client.get_page(ctx.content_id) is not None

    rc, out, err = _run_main(ctx.ws_root, ctx.export_dir, go=True)
    assert rc != 0, (
        "redeploying after a manual wiki edit should exit non-zero (a page "
        f"was held back), but rc=0.\n--- stdout ---\n{out}")
    assert re.search(rf"HELD\s+{re.escape(ctx.content_id)}\b", out), (
        f"expected a HELD report naming {ctx.content_id} in stdout:\n{out}")
    assert "--- wiki (current)" in out and "+++ deploy (target)" in out, (
        f"expected a unified diff in the deploy report:\n{out}")

    survived = ctx.client.get_page(ctx.content_id)
    assert survived is not None and _norm(survived) == _norm(MANUAL_EDIT_BODY), (
        "the manual wiki edit did not survive the redeploy -- the held-back "
        f"page was overwritten anyway.\nwiki now:\n{survived!r}")

    drift_copy = deploy_export.page_path(
        ctx.content_id, ctx.ws_root / deploy_export.DRIFT_DIR)
    assert drift_copy.is_file(), (
        f"expected an inbound drift copy at {drift_copy}, but it does not "
        "exist")
    copy_text = drift_copy.read_text(encoding="utf-8")
    assert _norm(copy_text) == _norm(MANUAL_EDIT_BODY), (
        f"the drift copy at {drift_copy} does not match the wiki's current "
        f"text.\ncopy:\n{copy_text!r}")
    return (f"manual edit to {ctx.content_id} survived the redeploy; held "
            "back with a unified diff; inbound copy written under "
            f"{drift_copy.relative_to(ctx.ws_root)}; exit code was non-zero")


def check_overwrite(ctx: Ctx) -> str:
    """8. --overwrite: rerun naming the drifted page. Must be written and
    re-baselined, and the wiki edit from check 7 must be gone."""
    staged, plan = _plan_now(ctx.export_dir, ctx.ns, ctx.manifest_path, ctx.client)
    action = plan.pages[ctx.content_id].action
    assert action == "drift", (
        f"expected {ctx.content_id} to still classify 'drift' going into "
        f"the --overwrite check, got {action!r}")

    rc, out, err = _run_main(
        ctx.ws_root, ctx.export_dir, go=True, overwrite=[ctx.content_id])
    assert rc == 0, (
        f"the --overwrite redeploy failed (rc={rc}).\n"
        f"--- stdout ---\n{out}--- stderr ---\n{err}")

    wiki_text = ctx.client.get_page(ctx.content_id)
    expected = staged[ctx.content_id]
    assert wiki_text is not None and _norm(wiki_text) == _norm(expected), (
        "after --overwrite, the wiki content does not match the rendered "
        f"source.\nexpected:\n{expected!r}\nwiki:\n{wiki_text!r}")

    manifest = deploy_export.load_manifest(ctx.manifest_path)
    assert manifest.get(ctx.content_id) == deploy_export.page_hash(wiki_text), (
        "the manifest was not re-baselined to the new wiki content after "
        "--overwrite")
    return (f"--overwrite {ctx.content_id}: written and re-baselined; the "
            "manual edit from the drift check is gone")


def check_adopt_resume(ctx: Ctx) -> str:
    """9. Adopt / resume-after-crash: clobber the manifest's recorded
    hashes (simulating a run that saved a page but died before writing the
    manifest), then redeploy. Must classify 'adopt', write zero pages
    (the wiki already matches what would be sent), and re-baseline the
    manifest to the real wiki hash."""
    manifest = deploy_export.load_manifest(ctx.manifest_path)
    for pid in (ctx.content_id, ctx.wrapper_id):
        assert pid in manifest, (
            f"expected {pid} to already be in the manifest before the "
            "adopt check")
    bogus = "0" * 64
    clobbered = dict(manifest)
    clobbered[ctx.content_id] = bogus
    clobbered[ctx.wrapper_id] = bogus
    deploy_export.save_manifest(ctx.manifest_path, clobbered)

    _staged, plan = _plan_now(ctx.export_dir, ctx.ns, ctx.manifest_path, ctx.client)
    for pid in (ctx.content_id, ctx.wrapper_id):
        action = plan.pages[pid].action
        assert action == "adopt", (
            f"expected {pid} to classify 'adopt' after clobbering its "
            f"manifest hash (wiki content unchanged), got {action!r}")

    rc, out, err = _run_main(ctx.ws_root, ctx.export_dir, go=True)
    assert rc == 0, (
        f"the adopt redeploy failed (rc={rc}).\n"
        f"--- stdout ---\n{out}--- stderr ---\n{err}")
    m = _DEPLOY_SUMMARY_RE.search(out)
    assert m, f"could not find the deploy summary line in stdout:\n{out}"
    written, adopted = int(m.group(1)), int(m.group(2))
    assert written == 0, (
        f"the adopt redeploy wrote {written} page(s); expected 0.\n{out}")
    assert adopted >= 2, (
        f"expected at least 2 adopted pages, got {adopted}.\n{out}")

    new_manifest = deploy_export.load_manifest(ctx.manifest_path)
    for pid in (ctx.content_id, ctx.wrapper_id):
        wiki_text = ctx.client.get_page(pid)
        assert new_manifest.get(pid) == deploy_export.page_hash(wiki_text), (
            f"the manifest entry for {pid} was not re-baselined to the "
            "real wiki hash after adopt")
    return (f"clobbered manifest hashes for {ctx.content_id} and "
            f"{ctx.wrapper_id}; redeploy classified both 'adopt', wrote 0 "
            "pages, and re-baselined the manifest to the real wiki hash")


def check_empty_page_refused(ctx: Ctx) -> str:
    """10. core.savePage must refuse an empty page with error 132 -- the
    premise both the ~~NOTOC~~ placeholder design and get_page's empty-result
    handling rest on. Uses a page id that has never been written by anything
    in this script, so a refusal can never be misread as "deleted real
    content"."""
    probe_id = f"{ctx.ns}:{PROBE_DIR}:empty-page-refusal-probe"
    pre = ctx.client.get_page(probe_id)
    assert pre is None, (
        f"{probe_id} already exists on the wiki -- this check needs a page "
        "that has never existed, so a refused empty save can never be "
        "misread as deleting real content. Delete it by hand, or pick a "
        "different id, before re-running.")
    try:
        ctx.client.save_page(probe_id, "")
    except RpcError as exc:
        assert exc.code == 132, (
            f"expected error 132 (empty page refused), got code "
            f"{exc.code!r}: {exc.message}")
    else:
        raise AssertionError(
            f"core.savePage accepted an empty body for {probe_id} instead "
            "of refusing it with error 132 -- the ~~NOTOC~~ placeholder "
            "design assumes this call always fails")
    post = ctx.client.get_page(probe_id)
    assert post is None, (
        f"{probe_id} exists after the refused empty save -- expected it to "
        "still not exist")
    return f"core.savePage({probe_id!r}, '') refused with error 132, as expected"


def check_notoc_placeholder(ctx: Ctx) -> str:
    """11. The ~~NOTOC~~ placeholder body must save and count as existing.
    Whether it actually *renders* blank cannot be checked programmatically
    from here -- that needs a browser -- so this check only proves the
    "exists" half and says so."""
    probe_id = f"{ctx.ns}:{PROBE_DIR}:placeholder-probe"
    ctx.client.save_page(probe_id, deploy_export.PLACEHOLDER_BODY)
    result = ctx.client.get_page(probe_id)
    assert result is not None, (
        f"{probe_id} does not exist after saving the ~~NOTOC~~ placeholder "
        "body -- get_page treats an empty result as 'does not exist', so a "
        "wiki that renders ~~NOTOC~~ down to a truly empty stored page "
        "would break the placeholder design")
    return (f"saved the ~~NOTOC~~ placeholder body to {probe_id}; get_page "
            "confirms it exists. Whether it RENDERS blank cannot be checked "
            "from this script -- open the page in a browser to confirm.")


# ---------------------------------------------------------------------------
# Runner / report
# ---------------------------------------------------------------------------

def _run_one(name: str, fn, *args) -> tuple[bool, str]:
    print(f"--- {name} ---")
    try:
        detail = fn(*args)
    except AssertionError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return False, str(exc)
    except RpcError as exc:
        print(f"FAILED (RPC error): {exc}", file=sys.stderr)
        return False, str(exc)
    print(f"PASSED: {detail}")
    return True, detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Opt-in, human-invoked check of the JSON-RPC deploy "
                    "transport against a real DokuWiki. Never runs in CI "
                    "or the normal test suite.")
    parser.add_argument(
        "--workspace", metavar="PATH", default=None,
        help="Campaign workspace root (default: $BUNNYFORGE_WORKSPACE, else "
             "the nearest campaign.toml above the current directory) -- "
             "the REAL workspace, read only for its [wiki] url, namespace, "
             "and token; never written to")
    parser.add_argument(
        "--go", action="store_true",
        help="Also run the write checks (4-11): create/update a probe page "
             "on the live wiki, edit it, hold back drift, overwrite, adopt, "
             "and probe two RPC edge cases. Without --go, only the "
             "read-only checks (1-3) run and nothing is written.")
    args = parser.parse_args(argv)

    try:
        real_ws = _config.resolve_workspace(args.workspace)
    except Exception as exc:  # ConfigError / WorkspaceError, both user-facing
        print(f"error: {exc}", file=sys.stderr)
        return 1

    ns = real_ws.config.namespace
    wiki_url = real_ws.config.wiki_url
    if not wiki_url:
        print("error: campaign.toml has no [wiki] url -- this check needs a "
              "real wiki to talk to. Add:\n\n"
              "  [wiki]\n"
              '  url = "https://<wiki>"\n', file=sys.stderr)
        return 1

    try:
        token = _config.resolve_wiki_token(real_ws.root)
    except Exception as exc:  # ConfigError
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        client = RpcClient(wiki_url, token)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"live_wiki_check: namespace={ns!r}, --go={args.go}\n")

    results: list[tuple[str, bool]] = []
    ok, _ = _run_one("1. handshake", check_handshake, client)
    results.append(("1. handshake", ok))
    ok, _ = _run_one("2. missing-page contract", check_missing_page_returns_none,
                     client, ns)
    results.append(("2. missing-page contract", ok))
    ok, _ = _run_one("3. protected-page guard", check_protected_guard, ns)
    results.append(("3. protected-page guard", ok))

    read_only_ok = all(ok for _, ok in results)

    touched_pages: list[str] = []

    if not args.go:
        print("\nWrite checks (4-11) SKIPPED: pass --go to run them. Without "
              "--go this script never writes to the wiki, matching the "
              "package-wide dry-run/--go convention.")
    elif not read_only_ok:
        print("\nWrite checks (4-11) SKIPPED: a read-only check failed "
              "above. Fixing the misconfiguration it reports is safer than "
              "writing to a wiki this script cannot yet talk to correctly.",
              file=sys.stderr)
    else:
        real_token_env = os.environ.get("BUNNYFORGE_WIKI_TOKEN")
        os.environ["BUNNYFORGE_WIKI_TOKEN"] = token
        tmp_root = Path(tempfile.mkdtemp(prefix="bunnyforge-live-wiki-check-"))
        try:
            (tmp_root / "campaign.toml").write_text(
                f'[campaign]\nnamespace = "{ns}"\n\n'
                f'[wiki]\nurl = "{wiki_url}"\n',
                encoding="utf-8")
            export_dir = tmp_root / "Export"
            export_dir.mkdir()
            manifest_path = tmp_root / deploy_export.MANIFEST_FILE
            ctx = Ctx(client, ns, tmp_root, export_dir, manifest_path)

            write_checks = [
                ("4. create or update probe page", check_create_or_update),
                ("5. idempotency", check_idempotent),
                ("6. roundtrip edit", check_roundtrip_edit),
                ("7. drift hold-back", check_drift_holdback),
                ("8. --overwrite", check_overwrite),
                ("9. adopt / resume-after-crash", check_adopt_resume),
                ("10. savePage refuses empty page", check_empty_page_refused),
                ("11. ~~NOTOC~~ placeholder", check_notoc_placeholder),
            ]
            for i, (name, fn) in enumerate(write_checks):
                ok, _ = _run_one(name, fn, ctx)
                results.append((name, ok))
                if not ok:
                    for skipped_name, _ in write_checks[i + 1:]:
                        print(f"--- {skipped_name} ---\nSKIPPED: an earlier "
                              "check failed and later checks assume its "
                              "state.")
                        results.append((skipped_name, False))
                    break

            touched_pages = [ctx.wrapper_id, ctx.content_id,
                             f"{ns}:{PROBE_DIR}:placeholder-probe"]
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)
            if real_token_env is None:
                os.environ.pop("BUNNYFORGE_WIKI_TOKEN", None)
            else:
                os.environ["BUNNYFORGE_WIKI_TOKEN"] = real_token_env

    print("\n--- summary ---")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    if touched_pages:
        print("\nPage(s) this run created or updated on the live wiki:")
        for pid in touched_pages:
            print(f"  {pid}")
        print("This tool cannot delete wiki pages -- removing them, if "
              "ever wanted, is a manual act on the wiki itself.")

    passed = all(ok for _, ok in results)
    print(f"\n{'PASSED' if passed else 'FAILED'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
