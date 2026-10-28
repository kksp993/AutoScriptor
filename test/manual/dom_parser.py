"""DOM snapshots and explicit interactions with existing Chromium or Android WebView.

Optional dependency: ``uv pip install --python .venv/Scripts/python.exe "playwright>=1.64"``.
Attaching to an existing browser does NOT require ``playwright install``.
Importing this module never connects, reads AutoScriptor config, or starts OCR.

Use ``DomParser(page_or_frame)`` with an existing synchronous Playwright session,
or use ``connect_dom`` / ``connect_android_dom`` as context managers. Snapshot
selectors are standard CSS; actions use Playwright selectors. The caller owns
all selectors and task logic; no website-specific behavior is built in.
All rectangles are CSS pixels in the supplied document's viewport, NOT Android
screen coordinates. Snapshots are read-only observations, not element handles;
``element`` exposes native Playwright interactions and media actions are explicit.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Iterator, Sequence

if TYPE_CHECKING:
    from playwright.sync_api import Frame, Locator, Page

__all__ = [
    "DomParser", "DomElement", "DomList", "DomRect", "ScrollState", "MediaState",
    "DomConnectionError", "DomSelectionError", "connect_dom", "connect_android_dom",
]


class DomConnectionError(RuntimeError):
    """Device, debugging socket, CDP endpoint or page could not be selected."""


class DomSelectionError(ValueError):
    """A unique container or selected list item could not be determined."""


@dataclass(frozen=True)
class MediaState:
    """Native HTML video/audio state; unknown or infinite duration is None.

    An ended video is not proof of server-side completion. Source may contain
    private tokens; use it for identity comparisons, not routine logging.
    """

    source: str
    current_time: float
    duration: float | None
    paused: bool
    ended: bool
    seeking: bool
    ready_state: int
    network_state: int
    error_code: int | None


@dataclass(frozen=True)
class DomRect:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class ScrollState:
    top: float
    left: float
    height: float
    width: float
    client_height: float
    client_width: float
    overflow_y: str

    @property
    def can_scroll_down(self) -> bool:
        return self.overflow_y in {"auto", "scroll"} and self.top + self.client_height < self.height - 1


@dataclass(frozen=True)
class DomElement:
    """One mounted element; index is query order, not a stable item identity.

    ``receives_pointer`` is a hit test at the visible rectangle's center, not
    a promise of clickability. None means there is no visible rectangle.
    Requested attributes/styles can contain private data; do not log blindly.
    """

    index: int
    tag: str
    text: str
    classes: tuple[str, ...]
    attributes: dict[str, str | None]
    styles: dict[str, str]
    bounds: DomRect
    visible_bounds: DomRect | None
    rendered: bool
    fully_visible: bool
    receives_pointer: bool | None
    scroll: ScrollState


@dataclass(frozen=True)
class DomList:
    """A single-evaluation snapshot of mounted rows, including clipped rows.

    DOM order need not equal CSS visual order. Unmounted virtual/infinite-list
    items cannot be discovered here. A missing next_item does NOT prove that
    the remote list, course, or business process is complete.
    """

    container: DomElement
    items: tuple[DomElement, ...]
    selected_indices: tuple[int, ...]

    @property
    def current_item(self) -> DomElement:
        if len(self.selected_indices) != 1:
            raise DomSelectionError(
                f"Expected one selected item, found {len(self.selected_indices)}; "
                "check selected_selector and page state instead of guessing."
            )
        return self.items[self.selected_indices[0]]

    @property
    def next_item(self) -> DomElement | None:
        """Next mounted sibling in query order; raises if selection is unclear."""
        next_index = self.current_item.index + 1
        return self.items[next_index] if next_index < len(self.items) else None


# Read geometry, selection and text in one browser task, without mutating DOM.
_READ_DOM = r"""request => {
    const rectangle = bounds => ({
        x: bounds.left, y: bounds.top,
        width: bounds.right - bounds.left, height: bounds.bottom - bounds.top
    });
    const describe = (element, index) => {
        const bounds = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        const viewport = window.visualViewport;
        const visible = {
            left: Math.max(bounds.left, viewport ? viewport.offsetLeft : 0),
            top: Math.max(bounds.top, viewport ? viewport.offsetTop : 0),
            right: Math.min(bounds.right, viewport ? viewport.offsetLeft + viewport.width : innerWidth),
            bottom: Math.min(bounds.bottom, viewport ? viewport.offsetTop + viewport.height : innerHeight)
        };
        let rendered = bounds.width > 0 && bounds.height > 0
            && style.visibility === 'visible' && element.getClientRects().length > 0;
        for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
            const ancestorStyle = getComputedStyle(ancestor);
            if (ancestorStyle.display === 'none' || Number(ancestorStyle.opacity) === 0) {
                rendered = false;
            }
            if (ancestor === element) continue;
            const ancestorBounds = ancestor.getBoundingClientRect();
            const scaleX = ancestor.offsetWidth ? ancestorBounds.width / ancestor.offsetWidth : 1;
            const scaleY = ancestor.offsetHeight ? ancestorBounds.height / ancestor.offsetHeight : 1;
            const clipLeft = ancestorBounds.left + ancestor.clientLeft * scaleX;
            const clipTop = ancestorBounds.top + ancestor.clientTop * scaleY;
            if (ancestorStyle.overflowX !== 'visible') {
                visible.left = Math.max(visible.left, clipLeft);
                visible.right = Math.min(visible.right, clipLeft + ancestor.clientWidth * scaleX);
            }
            if (ancestorStyle.overflowY !== 'visible') {
                visible.top = Math.max(visible.top, clipTop);
                visible.bottom = Math.min(visible.bottom, clipTop + ancestor.clientHeight * scaleY);
            }
        }
        const hasVisibleArea = rendered && visible.right > visible.left && visible.bottom > visible.top;
        const hit = hasVisibleArea ? document.elementFromPoint(
            (visible.left + visible.right) / 2, (visible.top + visible.bottom) / 2
        ) : null;
        return {
            index, tag: element.tagName.toLowerCase(),
            text: (element.innerText ?? element.textContent ?? '').trim(),
            classes: Array.from(element.classList),
            attributes: Object.fromEntries(request.attributes.map(name => [name, element.getAttribute(name)])),
            styles: Object.fromEntries(request.styles.map(name => [name, style.getPropertyValue(name)])),
            bounds: rectangle(bounds),
            visible_bounds: hasVisibleArea ? rectangle(visible) : null,
            rendered,
            fully_visible: hasVisibleArea && visible.left <= bounds.left + 0.5
                && visible.top <= bounds.top + 0.5 && visible.right >= bounds.right - 0.5
                && visible.bottom >= bounds.bottom - 0.5,
            receives_pointer: hasVisibleArea ? !!hit && element.contains(hit) : null,
            scroll: {
                top: element.scrollTop, left: element.scrollLeft,
                height: element.scrollHeight, width: element.scrollWidth,
                client_height: element.clientHeight, client_width: element.clientWidth,
                overflow_y: style.overflowY
            }
        };
    };
    if (request.mode === 'query') {
        return Array.from(document.querySelectorAll(request.selector), describe);
    }
    const containers = document.querySelectorAll(request.container_selector);
    if (containers.length !== 1) return {container_count: containers.length};
    const container = containers[0];
    // Validate even on an empty list: malformed selectors must not look healthy.
    container.matches(request.selected_selector);
    const items = Array.from(container.querySelectorAll(request.item_selector));
    return {
        container_count: 1,
        container: describe(container, 0),
        items: items.map(describe),
        selected_indices: items.flatMap((element, index) =>
            element.matches(request.selected_selector) ? [index] : [])
    };
}"""


def _read_element(payload: dict) -> DomElement:
    return DomElement(
        **{
            **payload,
            "classes": tuple(payload["classes"]),
            "bounds": DomRect(**payload["bounds"]),
            "visible_bounds": DomRect(**payload["visible_bounds"]) if payload["visible_bounds"] else None,
            "scroll": ScrollState(**payload["scroll"]),
        }
    )


def _require_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _field_names(values: Sequence[str], name: str) -> list[str]:
    if isinstance(values, str):
        raise TypeError(f"{name} must be a sequence of names, not a single string")
    return [_require_text(value, name) for value in values]


class DomParser:
    """Read or explicitly control a caller-owned synchronous Page or Frame.

    query/read_list do not wait, scroll or traverse shadow roots. Interactions
    through element() use native Locator semantics, including actionability
    checks and auto-scrolling. Read a NEW snapshot after actions. Frames must
    be supplied explicitly; local hit tests cannot detect external overlays.
    Geometry is axis-aligned; complex clipping/transforms need caller checks.
    """

    def __init__(self, page: Page | Frame):
        self.page = page

    def element(self, selector: str) -> Locator:
        """Return a live Locator for click/fill/press/scroll/wait operations.

        Uses Playwright selectors, unlike the standard-CSS snapshot queries.
        Native strictness, timeouts and overlay checks apply; no forced clicks,
        silent first-match selection or stale snapshot indices are injected.
        """
        return self.page.locator(_require_text(selector, "selector"))

    def read_media(self, selector: str = "video", *, timeout_ms: float = 10000) -> MediaState:
        """Read one HTMLMediaElement, even with hidden controls; never hover.

        Waits for attachment, not loaded metadata or playback. Missing/multiple
        elements and non-media targets raise instead of inventing zero progress.
        """
        _validate_timeout(timeout_ms)
        payload = self.element(selector).evaluate("""element => {
            if (!(element instanceof HTMLMediaElement)) throw new Error('Expected HTMLMediaElement');
            return {
                source: element.currentSrc || element.src,
                current_time: element.currentTime,
                duration: Number.isFinite(element.duration) ? element.duration : null,
                paused: element.paused, ended: element.ended, seeking: element.seeking,
                ready_state: element.readyState, network_state: element.networkState,
                error_code: element.error ? element.error.code : null
            };
        }""", timeout=timeout_ms)
        return MediaState(**payload)

    def play_media(self, selector: str = "video", *, timeout_ms: float = 10000) -> None:
        """Request normal playback; never seek, reload or replay ended media.

        play() rejection propagates (including autoplay restrictions). Its
        promise has a separate deadline: Locator.evaluate's timeout only bounds
        finding the element. Success does not prove time will keep advancing.
        """
        _validate_timeout(timeout_ms)
        self.element(selector).evaluate("""async (element, timeoutMs) => {
            if (!(element instanceof HTMLMediaElement)) throw new Error('Expected HTMLMediaElement');
            if (element.ended) return;
            let timer;
            try {
                await Promise.race([
                    new Promise((resolve, reject) => {
                        timer = setTimeout(() => reject(new Error('Media play() timed out')), timeoutMs);
                    }),
                    element.play()
                ]);
            } catch (error) {
                // Cancel pending playback so it cannot start after a reported failure.
                element.pause();
                throw error;
            } finally {
                clearTimeout(timer);
            }
        }""", timeout_ms, timeout=timeout_ms)

    def pause_media(self, selector: str = "video", *, timeout_ms: float = 10000) -> None:
        """Pause one native media element without changing its playback position."""
        _validate_timeout(timeout_ms)
        self.element(selector).evaluate("""element => {
            if (!(element instanceof HTMLMediaElement)) throw new Error('Expected HTMLMediaElement');
            element.pause();
        }""", timeout=timeout_ms)

    def query(
        self, selector: str, *, attributes: Sequence[str] = (), styles: Sequence[str] = (),
    ) -> tuple[DomElement, ...]:
        """Read all matching elements; no matches returns an empty tuple.

        Invalid CSS or a detached/closed document propagates Playwright's error.
        Attribute values (including href, inputs and data-*) are opt-in.
        """
        payload = self.page.evaluate(_READ_DOM, {
            "mode": "query", "selector": _require_text(selector, "selector"),
            "attributes": _field_names(attributes, "attributes"),
            "styles": _field_names(styles, "styles"),
        })
        return tuple(_read_element(element) for element in payload)

    def read_list(
        self, container_selector: str, item_selector: str, *, selected_selector: str,
        attributes: Sequence[str] = (), styles: Sequence[str] = (),
    ) -> DomList:
        """Read one container and its rows in DOM order, without scrolling.

        item_selector is scoped to the container (``:scope > ...`` is supported).
        selected_selector matches the row ITSELF, e.g. ``.active`` or
        ``[aria-selected="true"]``. Site-specific choices belong to the caller.
        """
        payload = self.page.evaluate(_READ_DOM, {
            "mode": "list",
            "container_selector": _require_text(container_selector, "container_selector"),
            "item_selector": _require_text(item_selector, "item_selector"),
            "selected_selector": _require_text(selected_selector, "selected_selector"),
            "attributes": _field_names(attributes, "attributes"),
            "styles": _field_names(styles, "styles"),
        })
        if payload["container_count"] != 1:
            raise DomSelectionError(
                f"Expected one container for {container_selector!r}, found {payload['container_count']}"
            )
        return DomList(
            container=_read_element(payload["container"]),
            items=tuple(_read_element(element) for element in payload["items"]),
            selected_indices=tuple(payload["selected_indices"]),
        )


def _validate_timeout(timeout_ms: float) -> None:
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, (int, float)):
        raise ValueError("timeout_ms must be a positive finite number")
    if not math.isfinite(timeout_ms) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive finite number")


@contextmanager
def connect_dom(
    endpoint: str, *, url_pattern: str = "*", timeout_ms: float = 10000,
) -> Iterator[DomParser]:
    """Attach to existing Chromium over CDP and select exactly one existing tab.

    url_pattern uses fnmatch glob syntax, not regex. No tabs are opened, closed,
    navigated or silently selected on ambiguity. Exit stops our Playwright
    transport only; it does not close the user's browser. Use DomParser(page)
    directly when the caller already owns Playwright (including its event loop).
    """
    endpoint = _require_text(endpoint, "endpoint")
    url_pattern = _require_text(url_pattern, "url_pattern")
    _validate_timeout(timeout_ms)
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as error:
        raise DomConnectionError(
            'Install the optional client: uv pip install --python .venv/Scripts/python.exe "playwright>=1.64"'
        ) from error

    with sync_playwright() as driver:
        try:
            browser = driver.chromium.connect_over_cdp(endpoint, timeout=timeout_ms, no_defaults=True)
        except PlaywrightError as error:
            raise DomConnectionError("Cannot attach to the CDP endpoint; check its address and debugging access") from error
        pages = [
            page for context in browser.contexts for page in context.pages
            if not page.is_closed() and fnmatchcase(page.url, url_pattern)
        ]
        if len(pages) != 1:
            raise DomConnectionError(
                f"Expected one matching tab, found {len(pages)}; refine url_pattern or open the target manually."
            )
        yield DomParser(pages[0])


def _run_adb(adb_path: str, serial: str, arguments: list[str], timeout_ms: float) -> str:
    command = [adb_path, "-s", serial, *arguments]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_ms / 1000,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DomConnectionError(f"ADB failed for serial={serial!r}, arguments={arguments!r}: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DomConnectionError(
            f"ADB failed for serial={serial!r}, arguments={arguments!r}, exit={result.returncode}: {detail}"
        )
    return result.stdout.strip()


@contextmanager
def connect_android_dom(
    *, adb_path: str, serial: str, url_pattern: str = "*",
    socket_name: str | None = None, timeout_ms: float = 10000,
) -> Iterator[DomParser]:
    """Attach to an already connected Android Chrome/debuggable WebView.

    No global config, emulator-index guesses, adb reconnect, app launch or
    debugging toggles. Multiple debug sockets require explicit socket_name.
    Owns one adb-allocated TCP forward and removes only that forward on exit,
    including failed connections. Use a trusted local machine: CDP grants
    control of the browser; attachment itself performs no page interactions.
    """
    adb_path = _require_text(adb_path, "adb_path")
    serial = _require_text(serial, "serial")
    _require_text(url_pattern, "url_pattern")
    _validate_timeout(timeout_ms)
    state = _run_adb(adb_path, serial, ["get-state"], timeout_ms)
    if state != "device":
        raise DomConnectionError(f"ADB serial={serial!r} is not ready: {state!r}")
    socket_listing = _run_adb(adb_path, serial, ["shell", "cat", "/proc/net/unix"], timeout_ms)
    sockets = sorted(set(re.findall(r"@([^\s@]*devtools_remote[^\s]*)", socket_listing)))
    if socket_name is None:
        if len(sockets) != 1:
            raise DomConnectionError(
                f"Expected one debugging socket, found {sockets!r}; supply socket_name when ambiguous. "
                "Chrome must be open, or WebView debugging must already be enabled."
            )
        socket_name = sockets[0]
    else:
        socket_name = _require_text(socket_name, "socket_name").removeprefix("@")
        if socket_name not in sockets:
            raise DomConnectionError(f"Debugging socket {socket_name!r} not found on serial={serial!r}")

    port_text = _run_adb(
        adb_path, serial, ["forward", "tcp:0", f"localabstract:{socket_name}"], timeout_ms
    )
    if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise DomConnectionError(f"ADB did not return an allocated TCP port: {port_text!r}")
    try:
        with connect_dom(f"http://127.0.0.1:{port_text}", url_pattern=url_pattern, timeout_ms=timeout_ms) as parser:
            yield parser
    finally:
        has_primary_error = sys.exc_info()[0] is not None
        try:
            _run_adb(adb_path, serial, ["forward", "--remove", f"tcp:{port_text}"], timeout_ms)
        except DomConnectionError as cleanup_error:
            if not has_primary_error:
                raise
            warnings.warn(f"Failed to remove our ADB forward tcp:{port_text}: {cleanup_error}", RuntimeWarning)
