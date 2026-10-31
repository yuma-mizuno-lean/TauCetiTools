import unittest

from tauceti_tools.survey_facts import rebase_heads


class RebaseHandoffTests(unittest.TestCase):
    head = 'e53dccb6abd43a803fb90a84e8b4aee50fc16f7e'

    def comment(self, login, head=None):
        return {'user': {'login': login}, 'body':
                'Merge-queue recovery for head `e53dccb`: integration repair\n\n'
                '<!--tauceti-rebase:v1 ' + (head or self.head) + '-->'}

    def test_mei_and_existing_tau_ceti_handoffs(self):
        for login in ['mei-automation[bot]', 'tauceti-review-bot[bot]', 'tau-ceti-bors[bot]']:
            with self.subTest(login=login):
                self.assertEqual(rebase_heads([self.comment(login)]), [self.head])

    def test_unrecognized_authors_cannot_request_repair(self):
        for login in ['mei-automation', 'untrusted[bot]', 'author', 'MEI-AUTOMATION[bot]']:
            with self.subTest(login=login):
                self.assertEqual(rebase_heads([self.comment(login)]), [])

    def test_prefix_and_exact_head_marker_remain_required(self):
        for head in ['e53dccb', self.head.upper(), 'g' * 40]:
            self.assertEqual(rebase_heads([self.comment('mei-automation[bot]', head)]), [])
        comment = self.comment('mei-automation[bot]')
        comment['body'] = 'Quoted\n' + comment['body']
        self.assertEqual(rebase_heads([comment]), [])


if __name__ == '__main__':
    unittest.main()
