import unittest

from somawave.player import track_metadata


class MetadataTests(unittest.TestCase):
    def test_structured_and_icy_fields(self):
        self.assertEqual(track_metadata({"ARTIST": " Partner ", "TITLE": "Play The Field"}),
                         ("Partner", "Play The Field", ""))
        self.assertEqual(track_metadata({"icy-title": "Partner - Play The Field - Live"}),
                         ("Partner", "Play The Field - Live", ""))
        self.assertEqual(track_metadata({"title": "Track - Live"}), ("", "Track - Live", ""))

    def test_missing_and_unclassified_fields(self):
        self.assertEqual(track_metadata(None), ("", "", ""))
        self.assertEqual(track_metadata({"icy-title": "Live from the studio"}),
                         ("", "", "Live from the studio"))
