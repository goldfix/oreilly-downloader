# /// script
# dependencies = [
#   "aiohttp",
#   "lxml",
#   "python-dotenv",
# ]
# ///

import argparse
import asyncio
import os
import re
import sys
import zipfile
from pathlib import Path

import aiohttp
from lxml import etree
from lxml import html as lhtml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_URL = "https://learning.oreilly.com"

CONTAINER = b"""<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
    <rootfiles>
        <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>
"""


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


def to_xhtml(s: bytes | str, root_path: str) -> bytes:
    """Convert HTML content to valid XHTML conforming to EPUB specifications."""
    tree = lhtml.fromstring(s, parser=lhtml.HTMLParser(encoding="utf-8"))

    for el in list(tree.iter()):
        for attr in ["href", "src"]:
            val = el.get(attr, "")
            if val.startswith(root_path):
                el.set(attr, val.removeprefix(root_path))

    if tree.tag != "html":
        wrapper = etree.Element(
            "html",
            nsmap={
                None: "http://www.w3.org/1999/xhtml",
                "epub": "http://www.idpf.org/2007/ops",
            },
        )

        h1 = tree.find(".//h1")
        if h1 is not None:
            head = etree.SubElement(wrapper, "head")
            title = etree.SubElement(head, "title")
            title.text = "".join(h1.itertext()).strip()

        body = etree.SubElement(wrapper, "body")
        body.append(tree)
        tree = wrapper

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
            return r.ok
    except aiohttp.ClientError:
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

    async def download(url: str, path: str):
        async with sem, session.get(url) as r:
            r.raise_for_status()
            content = await r.read()
            if path.endswith(".html"):
                content = to_xhtml(content, root_path)
            zfh.writestr(path, content)

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
            await asyncio.gather(*[download(result["url"], f"EPUB/{result['full_path']}") for result in results])
            total_files += len(results)

        url = data.get("next")
        page += 1

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
        default=os.getenv("OREILLY_JWT"),
        help="O'Reilly 'orm-jwt' cookie value (defaults to OREILLY_JWT environment variable)",
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
    cookies = {"orm-jwt": jwt} if jwt else {}

    with zipfile.ZipFile(output_file, "w") as zfh:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            if not jwt:
                print("Warning: No JWT provided (via --jwt or OREILLY_JWT). Chapters may be truncated.")
            elif await check_auth(session):
                print("Authentication successful.")
            else:
                print("Warning: Authentication failed or token expired. Chapters may be truncated.")

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
    book_id = extract_book_id(raw_id)
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
