"""Agents that fail in ways that would take an in-process runner down."""

import os


def sends_then_exits(task, tools):
    p = tools.list_prospects()["prospects"][0]
    tools.send_email(p["email"], "Hi", "Hello")
    os._exit(3)


def eats_memory(task, tools):
    hog = []
    while True:
        hog.append(bytearray(50 * 1024 * 1024))


def hangs(task, tools):
    import time

    time.sleep(3600)
