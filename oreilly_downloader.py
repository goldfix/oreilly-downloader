# /// script
# dependencies = [
#   "aiohttp",
#   "lxml",
#   "python-dotenv",
# ]
# ///

import argparse
import asyncio
import base64
import json
import os
import posixpath
import re
import sys
import time
import zipfile
from pathlib import Path

import aiohttp
from lxml import etree
from lxml import html as lhtml

try:
    from dotenv import load_dotenv

    # .env is the authoritative source: override any stale value already
    # exported in the environment (e.g. from a previous shell export).
    load_dotenv(override=True)
except ImportError:
    pass

BASE_URL = "https://learning.oreilly.com"

DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://learning.oreilly.com/",
}

RESPONSIVE_CSS = """
img, svg {
  max-width: 100% !important;
  height: auto !important;
  object-fit: contain;
  box-sizing: border-box;
}
img.emoji {
  width: 1.2em !important;
  height: 1.2em !important;
  max-width: 1.2em !important;
  max-height: 1.2em !important;
  vertical-align: -0.2em !important;
  display: inline !important;
  margin: 0 0.1em !important;
}
figure, div.figure, div.informalfigure {
  max-width: 100% !important;
  box-sizing: border-box;
}
""".strip()

CONTAINER = b"""<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
    <rootfiles>
        <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>
"""


def resolve_jwt(cli_jwt: str | None = None) -> str | None:
    """Resolve and sanitize JWT token from CLI argument or OREILLY_JWT in .env/environment."""
    raw_token = cli_jwt if cli_jwt is not None else os.getenv("OREILLY_JWT")
    if not raw_token:
        return None
    token = raw_token.strip().strip("'\"").removeprefix("Bearer ").strip()
    return token if token else None


def get_jwt_expiration(token: str | None) -> float | None:
    """Extract expiration epoch timestamp ('exp') from JWT payload if present."""
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload_bytes = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_bytes))
            exp = payload.get("exp")
            if isinstance(exp, (int, float)):
                return float(exp)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return None


def get_auth_config(jwt: str | None) -> tuple[dict[str, str], dict[str, str]]:
    """Generate HTTP headers and cookies configured with the JWT token if present."""
    headers = dict(DEFAULT_HEADERS)
    cookies: dict[str, str] = {}
    if jwt:
        cookies["orm-jwt"] = jwt
        headers["Authorization"] = f"Bearer {jwt}"
    return headers, cookies


def extract_book_id(input_val: str) -> str:
    """Extract book ID or ISBN from raw ID, URN, or O'Reilly URL."""
    val = input_val.strip()
    if val.startswith("urn:orm:book:"):
        return val.removeprefix("urn:orm:book:").rstrip("/")

    urn_match = re.search(r"urn:orm:book:([a-zA-Z0-9_\-]+)", val)
    if urn_match:
        return urn_match.group(1)

    url_match = re.search(r"/library/view/[^/]+/([a-zA-Z0-9_\-]+)", val)
    if url_match:
        return url_match.group(1)

    if "/" in val:
        val = val.rstrip("/").split("/")[-1]

    return val


def isbn13_check_digit(prefix: str) -> str:
    """Compute the ISBN-13 check digit for a 12-digit prefix."""
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(prefix))
    return str((10 - total % 10) % 10)


def normalize_book_id(raw_id: str) -> str:
    """Extract the book ID, auto-correcting ISBN-13 prefixes missing the check digit."""
    book_id = extract_book_id(raw_id)
    if re.fullmatch(r"97[89]\d{9}", book_id):
        corrected = book_id + isbn13_check_digit(book_id)
        print(f"Note: '{book_id}' is a 12-digit ISBN-13 prefix; using corrected ID '{corrected}'.")
        return corrected
    return book_id


def resolve_output_path(output_arg: str | None, book_id: str) -> Path:
    """Resolve destination EPUB file path from CLI argument."""
    if not output_arg:
        return Path(f"{book_id}.epub")

    out_path = Path(output_arg)
    if out_path.is_dir() or output_arg.endswith(("/", "\\")):
        out_path.mkdir(parents=True, exist_ok=True)
        return out_path / f"{book_id}.epub"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path


def to_xhtml(s: bytes | str, root_path: str, dest_path: str) -> bytes:
    """Convert HTML content to valid XHTML conforming to EPUB specifications.

    `root_path` is the API prefix removed from absolute resource URLs; `dest_path`
    is the EPUB-relative destination of this file (e.g. 'Text/chapter-1.html') so
    that resource references are rewritten relative to its directory.
    """
    tree = lhtml.fromstring(s, parser=lhtml.HTMLParser(encoding="utf-8"))
    dest_dir = posixpath.dirname(dest_path)

    for el in list(tree.iter()):
        for attr in ["href", "src"]:
            val = el.get(attr)
            if not val or not isinstance(val, str):
                continue
            if val.startswith(root_path):
                rel = val.removeprefix(root_path)
                if dest_dir:
                    rel = posixpath.relpath(rel, dest_dir)
                el.set(attr, rel)

    if not isinstance(tree.tag, str) or tree.tag.lower() != "html":
        wrapper = etree.Element(
            "html",
            nsmap={
                None: "http://www.w3.org/1999/xhtml",
                "epub": "http://www.idpf.org/2007/ops",
            },
        )
        head = etree.SubElement(wrapper, "head")

        h1 = tree.find(".//h1") if isinstance(tree.tag, str) else None
        if h1 is not None:
            title = etree.SubElement(head, "title")
            title.text = "".join(h1.itertext()).strip()

        style_el = etree.SubElement(head, "style")
        style_el.set("type", "text/css")
        style_el.text = RESPONSIVE_CSS

        body = etree.SubElement(wrapper, "body")
        body.append(tree)
        tree = wrapper
    else:
        head = tree.find(".//{http://www.w3.org/1999/xhtml}head")
        if head is None:
            head = tree.find(".//head")
        if head is None:
            head = etree.Element("head")
            tree.insert(0, head)
        style_el = etree.SubElement(head, "style")
        style_el.set("type", "text/css")
        style_el.text = RESPONSIVE_CSS

    return etree.tostring(
        tree,
        xml_declaration=True,
        doctype="<!DOCTYPE html>",
        pretty_print=True,
        encoding="utf-8",
    )


async def check_auth(session: aiohttp.ClientSession) -> bool:
    """Verify if the current session JWT is valid."""
    url = f"{BASE_URL}/api/v1/user-preferences/"
    try:
        async with session.get(url, raise_for_status=False) as r:
            if r.status == 200:
                return True
            print(f"Auth verification failed: HTTP {r.status} {r.reason}")
            return False
    except aiohttp.ClientError as e:
        print(f"Auth verification network error: {e}")
        return False


async def fetch_book(
    book_id: str,
    zfh: zipfile.ZipFile,
    session: aiohttp.ClientSession,
    concurrency: int = 10,
) -> None:
    """Download all files for a book and assemble them into the ZIP EPUB archive."""
    root_path = f"/api/v2/epubs/urn:orm:book:{book_id}/files/"
    sem = asyncio.Semaphore(concurrency)

    async def download(url: str, full_path: str):
        async with sem, session.get(url) as r:
            r.raise_for_status()
            content = await r.read()
            if full_path.endswith((".html", ".xhtml")):
                content = to_xhtml(content, root_path, full_path)
            elif full_path.endswith(".css"):
                content = content + f"\n\n/* Responsive image overrides */\n{RESPONSIVE_CSS}\n".encode()
            zfh.writestr(f"EPUB/{full_path}", content)

    zfh.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
    zfh.writestr("META-INF/container.xml", CONTAINER)

    url = f"{BASE_URL}{root_path}"
    page = 1
    total_files = 0

    while url:
        print(f"Fetching metadata page {page} ({url})...")
        async with session.get(url) as r:
            if r.status == 404:
                raise ValueError(f"Book ID '{book_id}' not found on O'Reilly.")
            r.raise_for_status()
            data = await r.json()

        results = data.get("results", [])
        if results:
            print(f"  Downloading {len(results)} files (concurrency limit: {concurrency})...")
            await asyncio.gather(*[download(result["url"], result["full_path"]) for result in results])
            total_files += len(results)

        url = data.get("next")
        page += 1

    if total_files == 0:
        print(f"Warning: no files returned for book ID '{book_id}'. The ID may be incorrect or the book is unavailable.")
    else:
        print(f"Completed download of {total_files} files.")


def build_parser() -> argparse.ArgumentParser:
    """Build command line argument parser."""
    parser = argparse.ArgumentParser(description="Download and package books from O'Reilly Online Learning into EPUB format.")
    parser.add_argument(
        "book_id",
        help="Book ID, ISBN, URN (urn:orm:book:...), or full O'Reilly book URL",
    )
    parser.add_argument(
        "--jwt",
        default=None,
        help="O'Reilly 'orm-jwt' cookie value (defaults to OREILLY_JWT environment variable from .env)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output destination file or directory path (default: <book_id>.epub in current directory)",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=10,
        help="Maximum concurrent file downloads (default: 10)",
    )
    return parser


async def amain(book_id: str, jwt: str | None, output_file: Path, concurrency: int) -> None:
    """Main async execution routine."""
    resolved_jwt = resolve_jwt(jwt)
    headers, cookies = get_auth_config(resolved_jwt)

    if resolved_jwt:
        exp = get_jwt_expiration(resolved_jwt)
        if exp is not None and time.time() > exp:
            exp_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(exp))
            print(f"Warning: The provided JWT expired at {exp_str}.")
            print("Please extract a fresh 'orm-jwt' cookie from your browser and update .env or --jwt.")

    with zipfile.ZipFile(output_file, "w") as zfh:
        async with aiohttp.ClientSession(cookies=cookies, headers=headers) as session:
            if not resolved_jwt:
                print("Warning: No JWT provided (via --jwt, .env, or OREILLY_JWT). Chapters may be truncated.")
            elif await check_auth(session):
                print("Authentication successful.")
            else:
                print("Warning: Authentication check failed. Chapters may be truncated.")

            await fetch_book(
                book_id=book_id,
                zfh=zfh,
                session=session,
                concurrency=concurrency,
            )


def main() -> None:
    """CLI synchronous entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    raw_id = args.book_id
    book_id = normalize_book_id(raw_id)
    if not book_id:
        print(f"Error: Could not extract a valid book ID from '{raw_id}'", file=sys.stderr)
        sys.exit(1)

    output_file = resolve_output_path(args.output, book_id)

    try:
        asyncio.run(amain(book_id=book_id, jwt=args.jwt, output_file=output_file, concurrency=args.concurrency))
        print(f"Successfully created {output_file}")
    except aiohttp.ClientResponseError as e:
        if output_file.exists():
            output_file.unlink(missing_ok=True)
        print(f"HTTP Error ({e.status}): {e.message}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        if output_file.exists():
            output_file.unlink(missing_ok=True)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
