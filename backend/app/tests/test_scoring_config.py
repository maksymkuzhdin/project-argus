from app.scoring.tuning import config_value, load_scoring_config


def test_load_scoring_config_from_custom_yaml(tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """layer1:
  legacy:
    unexplained_wealth:
      threshold_ratio: 4.5
""",
        encoding="utf-8",
    )

    config = load_scoring_config(config_path)

    assert config_value(
        config,
        "layer1",
        "legacy",
        "unexplained_wealth",
        "threshold_ratio",
        default=3.0,
    ) == 4.5
