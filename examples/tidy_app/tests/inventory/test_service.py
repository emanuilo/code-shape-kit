from tidy_app.inventory import Inventory


def test_add_cleans_names_and_sums_counts(tmp_path):
    inventory = Inventory.open(tmp_path / "stock.json")
    inventory.add(" Apples ", 2)
    inventory.add("apples")
    assert inventory.counts() == {"apples": 3}
