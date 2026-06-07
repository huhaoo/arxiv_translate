import unittest

from arxiv_translate.metadata import parse_arxiv_metadata


class MetadataTests(unittest.TestCase):
    def test_parse_arxiv_metadata(self):
        xml = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>http://arxiv.org/abs/2401.12345v1</id>
            <updated>2024-01-02T00:00:00Z</updated>
            <published>2024-01-01T00:00:00Z</published>
            <title> A  Short
              Paper </title>
            <summary> This is
              an abstract. </summary>
            <author><name>Ada Lovelace</name></author>
            <author><name>Emmy Noether</name></author>
            <arxiv:primary_category term="math.CO" scheme="http://arxiv.org/schemas/atom"/>
            <category term="math.CO" scheme="http://arxiv.org/schemas/atom"/>
            <arxiv:doi>10.1000/test</arxiv:doi>
            <arxiv:journal_ref>Test Journal</arxiv:journal_ref>
          </entry>
        </feed>"""

        metadata = parse_arxiv_metadata(xml, "2401.12345v1")

        self.assertEqual(metadata.title, "A Short Paper")
        self.assertEqual(metadata.authors, ["Ada Lovelace", "Emmy Noether"])
        self.assertEqual(metadata.abstract, "This is an abstract.")
        self.assertEqual(metadata.year, "2024")
        self.assertEqual(metadata.primary_category, "math.CO")
        self.assertEqual(metadata.doi, "10.1000/test")


if __name__ == "__main__":
    unittest.main()
