import base64
import io
import json
import tempfile
import time
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from dotenv import load_dotenv
from lxml import etree

from oreilly_downloader import (
    CONTAINER,
    DEFAULT_HEADERS,
    RESPONSIVE_CSS,
    build_parser,
    check_auth,
    extract_book_id,
    fetch_book,
    get_auth_config,
    get_jwt_expiration,
    isbn13_check_digit,
    normalize_book_id,
    resolve_jwt,
    resolve_output_path,
    to_xhtml,
)


def test_resolve_jwt(monkeypatch):
    # Case 1: Explicit CLI argument passed
    assert resolve_jwt("custom_token_123") == "custom_token_123"

    # Case 2: Sanitization of quotes, spaces, Bearer prefix
    assert resolve_jwt("  'Bearer eyJhbGciOiJIUzI1NiJ9'  ") == "eyJhbGciOiJIUzI1NiJ9"
    assert resolve_jwt('  "Bearer token_xyz"  ') == "token_xyz"

    # Case 3: Fallback to environment variable when CLI is None
    monkeypatch.setenv("OREILLY_JWT", "env_token_456")
    assert resolve_jwt(None) == "env_token_456"

    # Case 4: CLI argument takes precedence over environment variable
    assert resolve_jwt("cli_token_override") == "cli_token_override"

    # Case 5: Neither CLI nor environment variable set
    monkeypatch.delenv("OREILLY_JWT", raising=False)
    assert resolve_jwt(None) is None
    assert resolve_jwt("") is None
    assert resolve_jwt("   ") is None


def test_get_jwt_expiration():
    # Synthetic JWT with known exp
    exp_time = 1800000000.0
    payload = {"sub": "user_123", "exp": int(exp_time)}
    b64_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    token = f"eyJhbGciOiJIUzI1NiJ9.{b64_payload}.signature"

    assert get_jwt_expiration(token) == exp_time
    assert get_jwt_expiration("invalid.token") is None
    assert get_jwt_expiration("") is None
    assert get_jwt_expiration(None) is None


def test_get_auth_config():
    # With token
    headers, cookies = get_auth_config("valid_jwt_token")
    assert headers["Authorization"] == "Bearer valid_jwt_token"
    assert headers["User-Agent"] == DEFAULT_HEADERS["User-Agent"]
    assert cookies == {"orm-jwt": "valid_jwt_token"}

    # Without token
    headers_no_auth, cookies_no_auth = get_auth_config(None)
    assert "Authorization" not in headers_no_auth
    assert headers_no_auth["User-Agent"] == DEFAULT_HEADERS["User-Agent"]
    assert cookies_no_auth == {}


def test_isbn13_check_digit():
    # Known ISBN-13 values (full 13 digits): check digit must match
    assert isbn13_check_digit("978163343453") == "0"  # 9781633434530
    assert isbn13_check_digit("978149195869") == "8"  # 9781491958698
    assert isbn13_check_digit("978149205634") == "8"  # 9781492056348


def test_normalize_book_id():
    # 12-digit ISBN-13 prefix gets auto-corrected with the check digit
    assert normalize_book_id("978163343453") == "9781633434530"
    assert normalize_book_id("978149195869") == "9781491958698"

    # Full 13-digit ISBNs are left unchanged
    assert normalize_book_id("9781633434530") == "9781633434530"

    # URN and URL forms are still parsed and corrected
    assert normalize_book_id("urn:orm:book:978163343453") == "9781633434530"
    url = "https://learning.oreilly.com/library/view/some-book/978163343453/"
    assert normalize_book_id(url) == "9781633434530"

    # Non-ISBN IDs are left unchanged
    assert normalize_book_id("some_book_slug") == "some_book_slug"


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
        <p>Look at <img src="{root_path}Images/pic.png" /> and <a href="{root_path}Text/ch02.html">Next</a>.</p>
    </div>
    """
    output = to_xhtml(html_input, root_path, "Text/ch01.html")
    assert isinstance(output, bytes)

    tree = etree.fromstring(output)
    # Check root namespace and tag
    assert tree.tag == "{http://www.w3.org/1999/xhtml}html"

    # Check title extracted from h1
    title_el = tree.find(".//{http://www.w3.org/1999/xhtml}title")
    assert title_el is not None
    assert title_el.text == "Chapter 1: Welcome"

    # Resources in a sibling directory need ../ prefix; same-dir files stay bare
    img_el = tree.find(".//{http://www.w3.org/1999/xhtml}img")
    assert img_el.get("src") == "../Images/pic.png"

    a_el = tree.find(".//{http://www.w3.org/1999/xhtml}a")
    assert a_el.get("href") == "ch02.html"


def test_to_xhtml_root_level_destination():
    root_path = "/api/v2/epubs/urn:orm:book:12345/files/"
    html_input = f'<div><img src="{root_path}Images/pic.png" /></div>'
    output = to_xhtml(html_input, root_path, "index.html")
    tree = etree.fromstring(output)
    img_el = tree.find(".//{http://www.w3.org/1999/xhtml}img")
    assert img_el.get("src") == "Images/pic.png"


def test_to_xhtml_handles_comments_and_none_attributes():
    root_path = "/api/v2/epubs/urn:orm:book:12345/files/"
    html_input = f"""
    <div>
        <!-- This is a comment that would break HtmlComment.get() -->
        <h1>Comment Test</h1>
        <a href="{root_path}Text/valid.html">Valid</a>
        <a href="">Empty</a>
        <a>No href</a>
    </div>
    """
    output = to_xhtml(html_input, root_path, "Text/comment.html")
    assert isinstance(output, bytes)
    tree = etree.fromstring(output)
    links = tree.findall(".//{http://www.w3.org/1999/xhtml}a")
    assert len(links) == 3
    assert links[0].get("href") == "valid.html"
    assert links[1].get("href") == ""
    assert links[2].get("href") is None


def test_to_xhtml_already_complete_html():
    root_path = "/api/v2/epubs/urn:orm:book:12345/files/"
    html_input = f"""<!DOCTYPE html>
    <html xmlns="http://www.w3.org/1999/xhtml">
        <head><title>Existing Title</title></head>
        <body>
            <p><a href="{root_path}Text/sec1.html">Section 1</a></p>
        </body>
    </html>
    """
    output = to_xhtml(html_input, root_path, "Text/sec1.html")
    assert isinstance(output, bytes)
    tree = etree.fromstring(output)
    assert tree.tag == "{http://www.w3.org/1999/xhtml}html"
    a_el = tree.find(".//{http://www.w3.org/1999/xhtml}a")
    assert a_el.get("href") == "sec1.html"


def test_to_xhtml_injects_responsive_css_fragment():
    root_path = "/api/v2/epubs/urn:orm:book:12345/files/"
    html_input = "<div><h1>Responsive Chapter</h1><img src='Images/pic.png'/></div>"
    output = to_xhtml(html_input, root_path, "Text/ch01.html")
    tree = etree.fromstring(output)

    style_el = tree.find(".//{http://www.w3.org/1999/xhtml}style")
    assert style_el is not None
    assert "max-width: 100% !important" in style_el.text
    assert "img.emoji" in style_el.text
    assert "figure" in style_el.text


def test_to_xhtml_injects_responsive_css_full_document():
    root_path = "/api/v2/epubs/urn:orm:book:12345/files/"
    html_input = """<!DOCTYPE html>
    <html xmlns="http://www.w3.org/1999/xhtml">
        <head><title>Full Doc</title></head>
        <body><p>Hello</p></body>
    </html>"""
    output = to_xhtml(html_input, root_path, "Text/doc.html")
    tree = etree.fromstring(output)

    style_el = tree.find(".//{http://www.w3.org/1999/xhtml}style")
    assert style_el is not None
    assert "max-width: 100% !important" in style_el.text


def test_responsive_css_content():
    assert "img, svg" in RESPONSIVE_CSS
    assert "max-width: 100% !important" in RESPONSIVE_CSS
    assert "height: auto !important" in RESPONSIVE_CSS
    assert "object-fit: contain" in RESPONSIVE_CSS
    assert "img.emoji" in RESPONSIVE_CSS


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


def test_default_headers_present():
    assert "User-Agent" in DEFAULT_HEADERS
    assert "Accept" in DEFAULT_HEADERS
    assert "Referer" in DEFAULT_HEADERS


@pytest.mark.asyncio
async def test_check_auth_success():
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.ok = True

    # Setup async context manager for session.get
    mock_get_ctx = MagicMock()
    mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_get_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.get.return_value = mock_get_ctx

    assert await check_auth(mock_session) is True


@pytest.mark.asyncio
async def test_check_auth_failure():
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_response = MagicMock()
    mock_response.status = 401
    mock_response.reason = "Unauthorized"
    mock_response.ok = False

    mock_get_ctx = MagicMock()
    mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_get_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.get.return_value = mock_get_ctx

    assert await check_auth(mock_session) is False


@pytest.mark.asyncio
async def test_fetch_book_structure():
    book_id = "12345"
    zip_buffer = io.BytesIO()
    root_path = f"/api/v2/epubs/urn:orm:book:{book_id}/files/"

    # Mock responses for fetch_book
    page_data = {
        "results": [
            {
                "url": f"https://learning.oreilly.com/api/v2/epubs/urn:orm:book:{book_id}/files/content.opf",
                "full_path": "content.opf",
            },
            {
                "url": f"https://learning.oreilly.com/api/v2/epubs/urn:orm:book:{book_id}/files/Text/ch01.html",
                "full_path": "Text/ch01.html",
            },
            {
                "url": f"https://learning.oreilly.com/api/v2/epubs/urn:orm:book:{book_id}/files/Text/titlepage.xhtml",
                "full_path": "Text/titlepage.xhtml",
            },
            {
                "url": f"https://learning.oreilly.com/api/v2/epubs/urn:orm:book:{book_id}/files/Styles/style.css",
                "full_path": "Styles/style.css",
            },
            {
                "url": f"https://learning.oreilly.com/api/v2/epubs/urn:orm:book:{book_id}/files/Images/pic.png",
                "full_path": "Images/pic.png",
            },
        ],
        "next": None,
    }

    mock_session = MagicMock(spec=aiohttp.ClientSession)

    def mock_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status = 200
        resp.raise_for_status = MagicMock()

        if "files/?page=" in url or url.endswith(f"/urn:orm:book:{book_id}/files/"):
            resp.json = AsyncMock(return_value=page_data)
        elif url.endswith("content.opf"):
            resp.read = AsyncMock(return_value=b"<package>mock opf</package>")
        elif url.endswith("Text/ch01.html"):
            resp.read = AsyncMock(return_value=f'<div><h1>Chapter 1</h1><img src="{root_path}Images/pic.png" /></div>'.encode())
        elif url.endswith("Text/titlepage.xhtml"):
            resp.read = AsyncMock(return_value=f'<div><image href="{root_path}Images/pic.png" /></div>'.encode())
        elif url.endswith("Styles/style.css"):
            resp.read = AsyncMock(return_value=b"body { font-size: 1em; }")
        elif url.endswith("Images/pic.png"):
            resp.read = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n")

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    mock_session.get.side_effect = mock_get

    with zipfile.ZipFile(zip_buffer, "w") as zfh:
        await fetch_book(book_id, zfh, mock_session, concurrency=2)

    # Verify zip contents
    with zipfile.ZipFile(zip_buffer, "r") as zfh:
        names = zfh.namelist()
        assert "mimetype" in names
        assert "META-INF/container.xml" in names
        assert "EPUB/content.opf" in names
        assert "EPUB/Text/ch01.html" in names
        assert "EPUB/Text/titlepage.xhtml" in names
        assert "EPUB/Styles/style.css" in names
        assert "EPUB/Images/pic.png" in names

        # Check mimetype is uncompressed
        mimetype_info = zfh.getinfo("mimetype")
        assert mimetype_info.compress_type == zipfile.ZIP_STORED
        assert zfh.read("mimetype") == b"application/epub+zip"

        # HTML image path rewritten relative to Text/ directory
        ch1 = zfh.read("EPUB/Text/ch01.html").decode()
        assert "../Images/pic.png" in ch1
        assert root_path not in ch1

        # XHTML is also processed and wrapped into a valid XHTML document
        tp = zfh.read("EPUB/Text/titlepage.xhtml").decode()
        assert "../Images/pic.png" in tp
        assert "<html" in tp
        assert root_path not in tp

        # CSS file has responsive overrides appended
        css = zfh.read("EPUB/Styles/style.css").decode()
        assert "body { font-size: 1em; }" in css
        assert "max-width: 100% !important" in css

        # Binary asset untouched
        assert zfh.read("EPUB/Images/pic.png") == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_live_auth_from_env():
    """Live authentication verification using OREILLY_JWT from .env or environment."""
    load_dotenv(override=True)
    jwt = resolve_jwt()

    if not jwt:
        pytest.skip("OREILLY_JWT is not configured in .env or environment")

    exp = get_jwt_expiration(jwt)
    if exp is not None and time.time() > exp:
        exp_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(exp))
        pytest.skip(f"OREILLY_JWT token in .env is expired (expired at {exp_str})")

    headers, cookies = get_auth_config(jwt)

    async with aiohttp.ClientSession(cookies=cookies, headers=headers) as session:
        is_authenticated = await check_auth(session)
        assert is_authenticated is True, "Authentication failed with the provided OREILLY_JWT token."
