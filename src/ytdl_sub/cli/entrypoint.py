import gc
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List
from typing import Optional
from typing import Tuple

from yt_dlp.utils import sanitize_filename

from ytdl_sub.cli.output_summary import output_summary
from ytdl_sub.cli.output_transaction_log import _maybe_validate_transaction_log_file
from ytdl_sub.cli.output_transaction_log import output_transaction_log
from ytdl_sub.cli.parsers.dl import DownloadArgsParser
from ytdl_sub.cli.parsers.main import DEFAULT_CONFIG_FILE_NAME
from ytdl_sub.cli.parsers.main import parser
from ytdl_sub.config.config_file import ConfigFile
from ytdl_sub.subscriptions.subscription import Subscription
from ytdl_sub.utils.exceptions import ExperimentalFeatureNotEnabled
from ytdl_sub.utils.exceptions import ValidationException
from ytdl_sub.utils.file_handler import FileHandler
from ytdl_sub.utils.file_handler import FileHandlerTransactionLog
from ytdl_sub.utils.file_lock import working_directory_lock
from ytdl_sub.utils.logger import Logger

logger = Logger.get()

# View is a command to run a simple dry-run on a URL using the `_view` preset.
# Use ytdl-sub dl arguments to use the preset
_VIEW_EXTRA_ARGS_FORMATTER = "--preset _view --overrides.url {}"


def _maybe_write_subscription_log_file(
    config: ConfigFile,
    subscription: Subscription,
    dry_run: bool,
    exception: Optional[Exception] = None,
) -> None:
    success: bool = exception is None

    # If dry-run, do nothing
    if dry_run:
        return

    # If persisting logs is disabled, do nothing
    if not config.config_options.persist_logs:
        return

    # If persisting successful logs is disabled, do nothing
    if success and not config.config_options.persist_logs.keep_successful_logs:
        return

    log_time = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_subscription_name = sanitize_filename(subscription.name).lower().replace(" ", "_")
    log_success = "success" if success else "error"

    log_filename = f"{log_time}.{log_subscription_name}.{log_success}.log"
    persist_log_path = Path(config.config_options.persist_logs.logs_directory) / log_filename

    if not success:
        Logger.log_exit_exception(exception=exception, log_filepath=persist_log_path)

    os.makedirs(os.path.dirname(persist_log_path), exist_ok=True)
    FileHandler.copy(Logger.debug_log_filename(), persist_log_path)


def _download_subscriptions_from_yaml_files(
    config: ConfigFile, subscription_paths: List[str], update_with_info_json: bool, dry_run: bool
) -> List[Tuple[Subscription, FileHandlerTransactionLog]]:
    """
    Downloads all subscriptions from one or many subscription yaml files.

    Parameters
    ----------
    config
        Configuration file
    subscription_paths
        Path to subscription files to download
    update_with_info_json
        Whether to actually download or update using existing info json
    dry_run
        Whether to dry run or not

    Returns
    -------
    List of (subscription, transaction_log)

    Raises
    ------
    Exception
        Any exception during download
    """
    subscriptions: List[Subscription] = []
    output: List[Tuple[Subscription, FileHandlerTransactionLog]] = []

    # Load all the subscriptions first to perform all validation before downloading
    for path in subscription_paths:
        subscriptions += Subscription.from_file_path(config=config, subscription_path=path)

    for subscription in subscriptions:
        logger.info(
            "Beginning subscription %s for %s",
            ("dry run" if dry_run else "download"),
            subscription.name,
        )
        logger.debug("Subscription full yaml:\n%s", subscription.as_yaml())

        try:
            if update_with_info_json:
                transaction_log = subscription.update_with_info_json(dry_run=dry_run)
            else:
                transaction_log = subscription.download(dry_run=dry_run)
        except Exception as exc:  # pylint: disable=broad-except
            _maybe_write_subscription_log_file(
                config=config, subscription=subscription, dry_run=dry_run, exception=exc
            )
            raise
        else:
            output.append((subscription, transaction_log))
            _maybe_write_subscription_log_file(
                config=config, subscription=subscription, dry_run=dry_run
            )
            Logger.cleanup()  # Cleanup logger after each successful subscription download
        finally:
            gc.collect()  # Garbage collect after each subscription download

    return output


def _download_subscription_from_cli(
    config: ConfigFile, dry_run: bool, extra_args: List[str]
) -> Tuple[Subscription, FileHandlerTransactionLog]:
    """
    Downloads a one-off subscription using the CLI

    Parameters
    ----------
    config
        Configuration file
    dry_run
        Whether this is a dry-run
    extra_args
        Extra arguments from argparse that contain dynamic subscription options

    Returns
    -------
    Subscription and its download transaction log
    """
    dl_args_parser = DownloadArgsParser(
        extra_arguments=extra_args, config_options=config.config_options
    )
    subscription_args_dict = dl_args_parser.to_subscription_dict()
    subscription_name = f"cli-dl-{dl_args_parser.get_args_hash()}"

    subscription = Subscription.from_dict(
        config=config, preset_name=subscription_name, preset_dict=subscription_args_dict
    )

    logger.info("Beginning CLI %s", ("dry run" if dry_run else "download"))
    return subscription, subscription.download(dry_run=dry_run)


def _view_url_from_cli(
    config: ConfigFile, url: str, split_chapters: bool
) -> Tuple[Subscription, FileHandlerTransactionLog]:
    """
    `ytdl-sub view` dry-runs a URL to print its source variables. Use the pre-built `_view` preset,
    inject the URL argument, and dry-run.
    """
    preset = "_view_split_chapters" if split_chapters else "_view"
    subscription = Subscription.from_dict(
        config=config,
        preset_name="ytdl-sub-view",
        preset_dict={"preset": preset, "overrides": {"url": url}},
    )

    logger.info(
        "Viewing source variables for URL '%s'%s",
        url,
        " with split chapters" if split_chapters else "",
    )
    return subscription, subscription.download(dry_run=True)


def main() -> List[Tuple[Subscription, FileHandlerTransactionLog]]:
    """
    Entrypoint for ytdl-sub, without the error handling
    """
    # If no args are provided, print help and exit
    if len(sys.argv) < 2:
        parser.print_help()
        return []

    args, extra_args = parser.parse_known_args()

    # Load the config
    config: ConfigFile = ConfigFile(name="default_config", value={})
    if args.config:
        config = ConfigFile.from_file_path(args.config)
    elif os.path.isfile(DEFAULT_CONFIG_FILE_NAME):
        config = ConfigFile.from_file_path(DEFAULT_CONFIG_FILE_NAME)
    else:
        logger.info("No config specified, using defaults.")

    transaction_logs: List[Tuple[Subscription, FileHandlerTransactionLog]] = []

    # If transaction log file is specified, make sure we can open it
    _maybe_validate_transaction_log_file(transaction_log_file_path=args.transaction_log)

    with working_directory_lock(config=config):
        if args.subparser == "sub":
            if (
                args.update_with_info_json
                and not config.config_options.experimental.enable_update_with_info_json
            ):
                raise ExperimentalFeatureNotEnabled(
                    "--update-with-info-json requires setting"
                    " configuration.experimental.enable_update_with_info_json to True. This"
                    " feature is ",
                    "still being tested and has the ability to destroy files. Ensure you have a ",
                    "full backup before usage. You have been warned!",
                )

            transaction_logs = _download_subscriptions_from_yaml_files(
                config=config,
                subscription_paths=args.subscription_paths,
                update_with_info_json=args.update_with_info_json,
                dry_run=args.dry_run,
            )

        # One-off download
        elif args.subparser == "dl":
            transaction_logs.append(
                _download_subscription_from_cli(
                    config=config, dry_run=args.dry_run, extra_args=extra_args
                )
            )
        elif args.subparser == "view":
            transaction_logs.append(
                _view_url_from_cli(config=config, url=args.url, split_chapters=args.split_chapters)
            )
        else:
            raise ValidationException("Must provide one of the commands: sub, dl, view")

    if not args.suppress_transaction_log:
        output_transaction_log(
            transaction_logs=transaction_logs,
            transaction_log_file_path=args.transaction_log,
        )

    output_summary(transaction_logs)

    return transaction_logs