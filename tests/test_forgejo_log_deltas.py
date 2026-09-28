import sys
from pathlib import Path
import json
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from plugins.spiders.forgejo import ForgejoSpider

PREFIX = '::arachne-log-scope::'
def snapshot(a, b=()):
    return '\n'.join(['::group::Forgejo job: A', *a, '::endgroup::',
                      '::group::Forgejo job: B', *b, '::endgroup::'])
def payload(lines):
    return [x for x in lines if not x.startswith(PREFIX)]
def scoped(lines):
    path = []
    out = []
    for line in lines:
        if line.startswith(PREFIX):
            path = [x['title'] for x in json.loads(line[len(PREFIX):])]
        else:
            out.append((path[:], line))
    return out

class LogDeltaTests(unittest.TestCase):
    def test_poll_end_does_not_end_group(self):
        old = snapshot(['::group::Compile', 'first', '::endgroup::'])
        new = snapshot(['::group::Compile', 'first', 'second', '::endgroup::'])
        self.assertEqual(scoped(ForgejoSpider._new_log_lines(old,new)),
                         [(['Forgejo job: A','Compile'], 'second')])

    def test_matrix_growth_does_not_repeat_other_jobs(self):
        old = snapshot(['a1'],['b1'])
        new = snapshot(['a1','a2'],['b1','b2'])
        self.assertEqual(scoped(ForgejoSpider._new_log_lines(old,new)),
                         [(['Forgejo job: A'],'a2'),(['Forgejo job: B'],'b2')])

    def test_truncated_poll_and_wrapper_change_do_not_replay_lines(self):
        cursor = {}
        first = '2026-09-25T12:00:00Z hello'
        second = '2026-09-25T12:00:01Z world'
        self.assertEqual(payload(ForgejoSpider._new_log_lines('',first,cursor)),[first])
        self.assertEqual(payload(ForgejoSpider._new_log_lines(first,snapshot([first,second]),cursor)),[second])
        self.assertEqual(payload(ForgejoSpider._new_log_lines('',snapshot([first]),cursor)),[])
        self.assertEqual(payload(ForgejoSpider._new_log_lines('',snapshot([first,second]),cursor)),[])

    def test_repeated_payload_occurrences_are_preserved(self):
        self.assertEqual(payload(ForgejoSpider._new_log_lines(snapshot(['same']),snapshot(['same','same']))), ['same'])

    def test_timestamped_end_marker_restores_parent(self):
        text = snapshot(['2026-09-25T12:00:00Z ##[group]Checkout','inside',
                         '2026-09-25T12:00:01Z ##[endgroup]','outside'])
        self.assertEqual(scoped(ForgejoSpider._new_log_lines('',text)),
                         [(['Forgejo job: A','Checkout'],'inside'),(['Forgejo job: A'],'outside')])

    def test_identical_lines_growing_in_one_matrix_job_keep_their_job(self):
        old = snapshot(['same'], ['same'])
        new = snapshot(['same','same'], ['same'])
        self.assertEqual(scoped(ForgejoSpider._new_log_lines(old,new)),
                         [(['Forgejo job: A'],'same')])

    def test_snapshot_end_inside_open_runner_group_keeps_next_job_independent(self):
        text='\n'.join(['::group::Forgejo job: A','::group::Forgejo step 1: Build',
                        '2026-09-25T12:00:00Z ##[group]Inner','a',
                        '::arachne-endgroup::step','::arachne-endgroup::job',
                        '::group::Forgejo job: B','b','::arachne-endgroup::job'])
        self.assertEqual(scoped(ForgejoSpider._new_log_lines('',text)),
                         [(['Forgejo job: A','Forgejo step 1: Build','Inner'],'a'),
                          (['Forgejo job: B'],'b')])

    def test_unchanged_snapshot_is_silent(self):
        text=snapshot(['line'])
        self.assertEqual(ForgejoSpider._new_log_lines(text,text),[])

if __name__ == '__main__':
    unittest.main()
