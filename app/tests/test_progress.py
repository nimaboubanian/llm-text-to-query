from text2query.benchmark.progress import print_item_done, print_item_start


def test_print_item_start_writes_label_without_newline(capsys):
    print_item_start(2, 5, "Q01")
    captured = capsys.readouterr()
    assert captured.out == "  [2/5] Q01..."


def test_print_item_done_completes_the_line(capsys):
    print_item_done(" ✓ (3 rows)")
    captured = capsys.readouterr()
    assert captured.out == " ✓ (3 rows)\n"
