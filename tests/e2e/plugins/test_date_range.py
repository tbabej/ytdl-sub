import copy

import mergedeep
import pytest
from conftest import assert_debug_log
from e2e.expected_download import assert_expected_downloads
from e2e.expected_transaction_log import assert_transaction_log_matches

import ytdl_sub.downloaders.downloader
from ytdl_sub.subscriptions.subscription import Subscription


@pytest.fixture
def recent_preset_dict(output_directory):
    return {
        "preset": "yt_channel_as_tv",
        "youtube": {"channel_url": "https://youtube.com/channel/UCcRSMoQqXc_JrBZRHDFGbqA"},
        "date_range": {"after": "20150101"},
        # override the output directory with our fixture-generated dir
        "output_options": {"output_directory": output_directory},
        # download the worst format so it is fast
        "ytdl_options": {
            "format": "worst[ext=mp4]",
            "max_views": 100000,  # do not download the popular PJ concert
        },
        "subtitles": {
            "subtitles_name": "{episode_name}.{lang}.{subtitles_ext}",
            "allow_auto_generated_subtitles": True,
        },
        "overrides": {"tv_show_name": "Project / Zombie"},
    }


@pytest.fixture
def rolling_recent_channel_preset_dict(recent_preset_dict):
    preset_dict = copy.deepcopy(recent_preset_dict)
    return mergedeep.merge(
        preset_dict,
        {
            "output_options": {"keep_files_after": "20181101"},
        },
    )


class TestDateRange:
    @pytest.mark.parametrize("dry_run", [True, False])
    def test_recent_channel_download(
        self,
        recent_preset_dict,
        channel_as_tv_show_config,
        output_directory,
        dry_run,
    ):
        recent_channel_subscription = Subscription.from_dict(
            config=channel_as_tv_show_config,
            preset_name="recent",
            preset_dict=recent_preset_dict,
        )

        transaction_log = recent_channel_subscription.download(dry_run=dry_run)
        assert_transaction_log_matches(
            output_directory=output_directory,
            transaction_log=transaction_log,
            transaction_log_summary_file_name="plugins/date_range/test_channel_recent.txt",
        )
        assert_expected_downloads(
            output_directory=output_directory,
            dry_run=dry_run,
            expected_download_summary_file_name="plugins/date_range/test_channel_recent.json",
        )
        if not dry_run:
            # try downloading again, ensure nothing more was downloaded
            with assert_debug_log(
                logger=ytdl_sub.downloaders.downloader.download_logger,
                expected_message="ExistingVideoReached, stopping additional downloads",
            ):
                transaction_log = recent_channel_subscription.download()
                assert_transaction_log_matches(
                    output_directory=output_directory,
                    transaction_log=transaction_log,
                    transaction_log_summary_file_name=("plugins/date_range/no_downloads.txt"),
                )
                assert_expected_downloads(
                    output_directory=output_directory,
                    dry_run=dry_run,
                    expected_download_summary_file_name="plugins/date_range/test_channel_recent.json",
                )

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_recent_channel_download__no_vids_in_range(
        self,
        channel_as_tv_show_config,
        recent_preset_dict,
        output_directory,
        dry_run,
    ):
        recent_preset_dict["date_range"]["after"] = "21000101"

        recent_channel_no_vids_in_range_subscription = Subscription.from_dict(
            config=channel_as_tv_show_config,
            preset_name="recent",
            preset_dict=recent_preset_dict,
        )

        # Run twice, ensure nothing changes between runsyoutube
        for _ in range(2):
            transaction_log = recent_channel_no_vids_in_range_subscription.download(dry_run=dry_run)
            assert_transaction_log_matches(
                output_directory=output_directory,
                transaction_log=transaction_log,
                transaction_log_summary_file_name="plugins/date_range/no_downloads.txt",
            )
            assert_expected_downloads(
                output_directory=output_directory,
                dry_run=dry_run,
                expected_download_summary_file_name="plugins/date_range/no_downloads.json",
            )

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_rolling_recent_channel_download(
        self,
        channel_as_tv_show_config,
        recent_preset_dict,
        rolling_recent_channel_preset_dict,
        output_directory,
        dry_run,
    ):
        recent_channel_subscription = Subscription.from_dict(
            config=channel_as_tv_show_config,
            preset_name="recent",
            preset_dict=recent_preset_dict,
        )
        rolling_recent_channel_subscription = Subscription.from_dict(
            config=channel_as_tv_show_config,
            preset_name="recent",
            preset_dict=rolling_recent_channel_preset_dict,
        )

        # First, download recent vids. Always download since we want to test dry-run
        # on the rolling recent portion.
        with assert_debug_log(
            logger=ytdl_sub.downloaders.downloader.download_logger,
            expected_message="RejectedVideoReached, stopping additional downloads",
        ):
            transaction_log = recent_channel_subscription.download(dry_run=False)

        assert_transaction_log_matches(
            output_directory=output_directory,
            transaction_log=transaction_log,
            transaction_log_summary_file_name="plugins/date_range/test_channel_recent.txt",
        )
        assert_expected_downloads(
            output_directory=output_directory,
            dry_run=False,
            expected_download_summary_file_name="plugins/date_range/test_channel_recent.json",
        )

        # Then, download the rolling recent vids subscription. This should remove one of the
        # two videos
        with assert_debug_log(
            logger=ytdl_sub.downloaders.downloader.download_logger,
            expected_message="ExistingVideoReached, stopping additional downloads",
        ):
            transaction_log = rolling_recent_channel_subscription.download(dry_run=dry_run)

        expected_downloads_summary = (
            "plugins/date_range/test_channel_recent.json"
            if dry_run
            else "plugins/date_range/test_channel_rolling_recent.json"
        )

        assert_transaction_log_matches(
            output_directory=output_directory,
            transaction_log=transaction_log,
            transaction_log_summary_file_name="plugins/date_range/test_channel_rolling_recent.txt",
        )
        assert_expected_downloads(
            output_directory=output_directory,
            dry_run=False,
            expected_download_summary_file_name=expected_downloads_summary,
        )

        # Invoke the rolling download again, ensure downloading stopped early from it already
        # existing
        if not dry_run:
            with assert_debug_log(
                logger=ytdl_sub.downloaders.downloader.download_logger,
                expected_message="ExistingVideoReached, stopping additional downloads",
            ):
                transaction_log = rolling_recent_channel_subscription.download()

            assert_transaction_log_matches(
                output_directory=output_directory,
                transaction_log=transaction_log,
                transaction_log_summary_file_name="plugins/date_range/no_downloads.txt",
            )
            assert_expected_downloads(
                output_directory=output_directory,
                dry_run=False,
                expected_download_summary_file_name=expected_downloads_summary,
            )