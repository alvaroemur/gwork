from __future__ import annotations

import json
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

import pypandoc

from . import docs_ast
from .gog import (
    batch_execute,
    docs_info,
    docs_raw,
    drive_get,
    extract_modified_time,
    GogError,
)


def fetch_doc_modified_time(drive_id: str, account: Optional[str] = None) -> str:
    try:
        mt = extract_modified_time(docs_info(drive_id, account))
        if mt:
            return mt
    except GogError:
        pass
    meta = drive_get(drive_id, account)
    return extract_modified_time(meta)


def fetch_doc_plain_text(drive_id: str, account: Optional[str] = None,
                         access_token: Optional[str] = None) -> str:
    """Return plain text from the Google Doc body with paragraphs joined.

    Used only by `gwork sync fetch --diff` for an approximate preview.
    Apply uses docs_ast and replace_doc_content_ast instead.
    """
    if access_token is None:
        from .auth import get_access_token
        acct = account or _infer_account()
        access_token = get_access_token(acct)

    url = f"https://docs.googleapis.com/v1/documents/{drive_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req) as resp:
        doc = json.loads(resp.read())

    parts: list[str] = []
    for el in doc.get("body", {}).get("content", []):
        paragraph = el.get("paragraph")
        if not paragraph:
            continue
        text = "".join(
            (run.get("textRun") or {}).get("content", "")
            for run in paragraph.get("elements", [])
        ).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def md_to_docx(md_path: Path, out_path: Optional[Path] = None) -> Path:
    if out_path is None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
        tmp.close()
        out_path = Path(tmp.name)
    pypandoc.convert_file(str(md_path), "docx", outputfile=str(out_path))
    return out_path


def update_doc_content(drive_id: str, docx_path: Path,
                       account: Optional[str] = None,
                       access_token: Optional[str] = None) -> str:
    """Replace Google Doc content by uploading the DOCX.

    Uses Drive API v3 directly with the gog access token because
    `gog drive upload` does not convert DOCX to a native Google Doc.

    Returns the new modifiedTime.
    """
    if access_token is None:
        from .auth import get_access_token
        from .gog import _run
        # Infer the account from gog when omitted.
        acct = account or _infer_account()
        access_token = get_access_token(acct)

    url = f"https://www.googleapis.com/upload/drive/v3/files/{drive_id}?uploadType=media&supportsAllDrives=true"
    docx_bytes = docx_path.read_bytes()
    req = urllib.request.Request(url, data=docx_bytes, method="PATCH")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    req.add_header("Content-Length", str(len(docx_bytes)))
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    return extract_modified_time(result)


def _infer_account() -> str:
    """Read the authenticated account from the gog config."""
    import subprocess
    res = subprocess.run(
        ["gog", "auth", "list", "--json"],
        capture_output=True, text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        data = json.loads(res.stdout)
        accounts = data if isinstance(data, list) else data.get("accounts", [])
        if accounts:
            return accounts[0].get("email", accounts[0]) if isinstance(accounts[0], dict) else accounts[0]
    raise RuntimeError("Could not infer the gog account. Pass --account explicitly.")


def replace_doc_content_ast(drive_id: str, md_text: str,
                            tab_id: Optional[str] = None,
                            account: Optional[str] = None,
                            code_font: str = docs_ast.CODE_FONT) -> str:
    """Replace Doc content by building its native document tree.

    Unlike `update_doc_content`, this emits `deleteContentRange`,
    `insertText` or `insertTable`, and styles through `batchUpdate` instead
    of uploading a file. Document margins, tabs, and `namedStyles` remain,
    and inserted content inherits them.

    See `docs/ast-insertion.md` for the three-batch, two-read design.
    """
    blocks = docs_ast.markdown_to_blocks(md_text)

    raw = docs_raw(drive_id, tab_id=tab_id, account=account)
    requests = docs_ast.clear_body_requests(raw, tab_id)
    requests += docs_ast.insert_requests(blocks, tab_id)
    batch_execute(drive_id, requests, account=account, source="gwork.sync.ast")

    raw = docs_raw(drive_id, tab_id=tab_id, account=account)
    cell_requests = docs_ast.cell_text_requests(raw, blocks, tab_id)
    if cell_requests:
        batch_execute(drive_id, cell_requests, account=account, source="gwork.sync.ast")
        raw = docs_raw(drive_id, tab_id=tab_id, account=account)

    style = docs_ast.style_requests(raw, blocks, tab_id, code_font=code_font)
    if style:
        batch_execute(drive_id, style, account=account, source="gwork.sync.ast")

    return extract_modified_time(drive_get(drive_id, account))
