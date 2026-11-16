"""Concurrent dispatches must bind only the metadata of their own response."""
import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from plugins.spiders.forgejo import ForgejoSpider


class ForgejoDispatchTests(unittest.TestCase):
    def test_same_repo_and_ref_keep_distinct_response_ids(self):
        spider = ForgejoSpider()
        barrier = threading.Barrier(2)

        def post(url, **kwargs):
            barrier.wait(timeout=2)
            run_id = kwargs['json']['inputs']['build']
            return httpx.Response(200, json={'id': int(run_id)},
                                  request=httpx.Request('POST', url))

        def dispatch(run_id):
            step = SimpleNamespace(with_={
                'repo': 'same', 'workflow': 'build.yml', 'ref': 'main',
                'build': run_id,
            })
            return spider.dispatch(step, {})

        with patch.object(spider, '_preflight_workflow_ref', return_value=None), \
                patch('plugins.spiders.forgejo.httpx.post', side_effect=post):
            with ThreadPoolExecutor(max_workers=2) as pool:
                handles = list(pool.map(dispatch, [101, 102]))
        self.assertEqual([h.external_id for h in handles], ['101', '102'])
        self.assertEqual(set(spider._runs), {'101', '102'})
        self.assertIsNot(spider._runs['101'], spider._runs['102'])

    def test_missing_id_never_binds_an_unrelated_latest_run(self):
        spider = ForgejoSpider()
        step = SimpleNamespace(with_={'repo': 'same', 'workflow': 'build.yml'})
        response = httpx.Response(204, request=httpx.Request('POST', 'https://forgejo/dispatch'))
        with patch.object(spider, '_preflight_workflow_ref', return_value=None), \
                patch('plugins.spiders.forgejo.httpx.post', return_value=response), \
                patch('plugins.spiders.forgejo.httpx.get') as get:
            with self.assertRaisesRegex(RuntimeError, 'return_run_info'):
                spider.dispatch(step, {})
            get.assert_not_called()
        self.assertEqual(spider._runs, {})
