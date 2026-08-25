import tempfile
from pathlib import Path

from lxml import etree

from oreilly_downloader import (
    CONTAINER,
    build_parser,
    extract_book_id,
    resolve_output_path,
    to_xhtml,
)


def test_extract_book_id():
    # Simple ID / ISBN
    assert extract_book_id("9781491958698") == "9781491958698"

    # URN format
    assert extract_book_id("urn:orm:book:9781491958698") == "9781491958698"
    assert extract_book_id("urn:orm:book:9781491958698/") == "9781491958698"

    # Standard O'Reilly web URL
    url = "https://learning.oreilly.com/library/view/fluent-python-2nd/9781492056348/"
    assert extract_book_id(url) == "9781492056348"

    url_no_slash = "https://learning.oreilly.com/library/view/fluent-python-2nd/9781492056348"
    assert extract_book_id(url_no_slash) == "9781492056348"

    # API URL
    api_url = "https://learning.oreilly.com/api/v2/epubs/urn:orm:book:9781491958698/files/"
    assert extract_book_id(api_url) == "9781491958698"


def test_resolve_output_path():
    # Default without -o
    p1 = resolve_output_path(None, "12345")
    assert p1 == Path("12345.epub")

    # Explicit filename
    p2 = resolve_output_path("custom_name.epub", "12345")
    assert p2 == Path("custom_name.epub")

    # Directory
    with tempfile.TemporaryDirectory() as tmpdir:
        p3 = resolve_output_path(f"{tmpdir}/", "12345")
        assert p3 == Path(tmpdir) / "12345.epub"


def test_to_xhtml_strips_root_path_and_converts():
    root_path = "/api/v2/epubs/urn:orm:book:12345/files/"
    html_input = f"""
    <div>
        <h1>Chapter 1: Welcome</h1>
        <p>Look at <img src="{root_path}images/pic.png" /> and <a href="{root_path}ch02.html">Next</a>.</p>
    </div>
    """
    output = to_xhtml(html_input, root_path)
    assert isinstance(output, bytes)

    tree = etree.fromstring(output)
    # Check root namespace and tag
    assert tree.tag == "{http://www.w3.org/1999/xhtml}html"

    # Check title extracted from h1
    title_el = tree.find(".//{http://www.w3.org/1999/xhtml}title")
    assert title_el is not None
    assert title_el.text == "Chapter 1: Welcome"

    # Check relative attributes
    img_el = tree.find(".//{http://www.w3.org/1999/xhtml}img")
    assert img_el.get("src") == "images/pic.png"

    a_el = tree.find(".//{http://www.w3.org/1999/xhtml}a")
    assert a_el.get("href") == "ch02.html"


def test_container_xml_valid():
    tree = etree.fromstring(CONTAINER)
    assert tree.tag == "{urn:oasis:names:tc:opendocument:xmlns:container}container"
    rootfile = tree.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
    assert rootfile is not None
    assert rootfile.get("full-path") == "EPUB/content.opf"
    assert rootfile.get("media-type") == "application/oebps-package+xml"


def test_build_parser():
    parser = build_parser()
    args = parser.parse_args(["9781491958698", "--jwt", "test_token", "-o", "output.epub", "-c", "5"])
    assert args.book_id == "9781491958698"
    assert args.jwt == "test_token"
    assert args.output == "output.epub"
    assert args.concurrency == 5
