from sentry_copilot.encounter.desktop import _locale_label


def test_live_preview_friendly_locale_labels_keep_existing_locale_ids_internal() -> None:
    assert _locale_label("zh_CN") == "简体中文"
    assert _locale_label("en") == "English"
