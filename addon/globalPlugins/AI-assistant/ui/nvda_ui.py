# -*- coding: utf-8 -*-
from __future__ import annotations

import collections.abc
import functools
import threading
from typing import Any, Callable

import queueHandler
import ui


def message(text: str) -> None:
    ui.message(text)


def browseable_message(
    text: str,
    title: str | None = None,
    is_html: bool = False,
    close_button: bool = False,
    copy_button: bool = False,
    sanitize_html_func: collections.abc.Callable[[str], str] = ui.nh3.clean,
) -> None:
    ui.browseableMessage(
        text,
        title=title,
        isHtml=is_html,
        closeButton=close_button,
        copyButton=copy_button,
        sanitizeHtmlFunc=sanitize_html_func,
    )


def queue(callback: Callable[..., None], *args: Any, **kwargs: Any) -> None:
    if kwargs:
        callback = functools.partial(callback, **kwargs)
    queueHandler.queueFunction(queueHandler.eventQueue, callback, *args)


def call(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if threading.current_thread() is threading.main_thread():
        return callback(*args, **kwargs)

    done = threading.Event()
    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = callback(*args, **kwargs)
        except Exception as error:
            result["error"] = error
        finally:
            done.set()

    queueHandler.queueFunction(queueHandler.eventQueue, runner)
    done.wait()
    if "error" in result:
        raise result["error"]
    return result.get("value")
