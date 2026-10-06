import unittest
from post_layout import apply_layout

class LayoutTests(unittest.TestCase):
    def test_header_and_odd_body_rows(self):
        s=apply_layout('<table><tr><th>A</th><th>B</th></tr><tr><td>X</td><td>Y</td><td>Z</td></tr><tr><td>W</td><td>Second</td></tr><tr><td>Third</td></tr></table><table><tr><td>First</td></tr></table>')
        self.assertEqual(s.count('background-color:#dce5ef'),2)
        self.assertEqual(s.count('background-color:#f6f8fb'),5)
        self.assertEqual(s.count('background-color:#ffffff'),2)
    def test_images_cannot_exceed_container(self):
        s=apply_layout('<img src="https://example.com/a.jpg" width="400"><img src="https://example.com/b.jpg">')
        self.assertIn('width:400px;max-width:100%;height:auto',s)
        self.assertIn('width:100%;max-width:100%;height:auto',s)
    def test_layout_is_idempotent_preserves_content(self):
        s='<p>A &amp; B</p><h3><strong>Heading</strong></h3><!-- blog-image-0 -->'
        styled=apply_layout(s)
        self.assertEqual(apply_layout(styled),styled)
        self.assertIn('A &amp; B',styled)
        self.assertIn('margin:0 0 28px',styled)
        self.assertIn('margin:44px 0 18px',styled)
        self.assertIn('<!-- blog-image-0 -->',styled)
