"""Offline tests for the Koji build spider."""

import asyncio
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from core.types import RunStatus, StepSpec
from plugins.spiders.koji import KojiSpider


class FakeConfig:
    server = "https://koji.example.internal/kojihub"
    weburl = "https://koji.example.internal/koji"
    topurl = "https://koji.example.internal/kojifiles"
    profile = "koji"


class FakePathInfo:
    def __init__(self, topdir=None, **kwargs):
        self.topdir = topdir

    def rpm(self, rpm):
        return (
            f"{self.topdir}/packages/{rpm['name']}/{rpm['version']}/"
            f"{rpm['release']}/{rpm['arch']}/{rpm['name']}-"
            f"{rpm['version']}-{rpm['release']}.{rpm['arch']}.rpm"
        )


class FakeSession:
    def __init__(self):
        self.state = 0
        self.cancelled = False

    def build(self, source, target, opts, priority=None, channel=None):
        self.submitted = (source, target, opts, priority, channel)
        return 1234

    def getTaskInfo(self, task_id, request=False, strict=False):
        return {"id": task_id, "state": self.state}

    def getTaskDescendents(self, task_id, request=False):
        return {str(task_id): [{"id": 1235}]}

    def listTaskOutput(self, task_id, stat=True):
        return {"build.log": {}} if task_id == 1235 else {}

    def downloadTaskOutput(self, task_id, filename, offset=0, size=-1):
        data = b"hello\nworld\n"
        return data[offset:]

    def listBuilds(self, taskID=None):
        return [{"id": 77}]

    def listBuildRPMs(self, build_id):
        return [{
            "id": 88,
            "name": "pkg",
            "version": "1.2.3",
            "release": "1",
            "arch": "x86_64",
        }]

    def cancelTask(self, task_id, recurse=True):
        self.cancelled = True


class FakeModule:
    config = FakeConfig()
    TASK_STATES = {
        "FREE": 0,
        "OPEN": 1,
        "CLOSED": 2,
        "CANCELED": 3,
        "ASSIGNED": 4,
        "FAILED": 5,
    }
    PathInfo = FakePathInfo

    def __init__(self, session):
        self._session = session

    def ClientSession(self, server, options):
        return self._session


class KojiSpiderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = FakeSession()
        self.module = FakeModule(self.session)
        self.spider = KojiSpider()

    def connect(self, profile):
        return self.module, self.session

    async def test_build_status_logs_and_artifacts(self):
        step = StepSpec(
            "build",
            "koji",
            "weave",
            with_={
                "source": "git+https://git.example/pkg?#deadbeef",
                "target": "redos8",
                "scratch": False,
            },
        )
        with patch.object(self.spider, "_connect", side_effect=self.connect):
            handle = self.spider.dispatch(step, {})

        self.assertEqual(handle.external_id, "1234")
        self.assertEqual(self.session.submitted[1], "redos8")

        async def settle():
            await asyncio.sleep(0)
            self.session.state = 2

        task = asyncio.create_task(settle())
        with patch("plugins.spiders.koji.KOJI_POLL_INTERVAL", 0):
            logs = [line.text async for line in self.spider.stream_logs(handle)]
        await task

        self.assertTrue(any("hello" in line for line in logs))
        self.assertEqual(self.spider.get_status(handle), RunStatus.SUCCESS)
        artifacts = self.spider.get_artifacts(handle)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].name, "pkg-1.2.3-1.x86_64.rpm")
        self.assertTrue(artifacts[0].download_url.endswith("pkg-1.2.3-1.x86_64.rpm"))

    def test_cancel(self):
        state = {
            "task_id": 1234,
            "session": self.session,
            "status": RunStatus.RUNNING,
        }
        self.spider._runs["1234"] = state
        from core.types import RunHandle
        handle = RunHandle("koji", "1234")
        self.assertTrue(self.spider.cancel(handle))
        self.assertTrue(self.session.cancelled)
        self.assertEqual(self.spider.get_status(handle), RunStatus.CANCELLED)


if __name__ == "__main__":
    unittest.main()
