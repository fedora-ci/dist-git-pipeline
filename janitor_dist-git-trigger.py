#!/usr/bin/python3
# /// script
# dependencies = [
#   "requests",
#   "bodhi-client",
# ]
# ///
"""
Re-trigger dist-git-trigger jobs that were missed by rabbitmq.
"""

import dataclasses
import datetime
import enum
import json
import logging
import typing
import os
from pathlib import Path

from bodhi.client.bindings import BodhiClient
import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util import Retry


logging.basicConfig(level="INFO")
logger = logging.getLogger(Path(__file__).name)

# Configurable variables
dry_run: bool = False
"""Whether to submit Jenkins jobs or just print the CI_MESSAGE."""
recheck_datagrepper: bool = True
"""Check datagrepper history."""
search_window = datetime.timedelta(minutes=10)
"""How far back should we check datagrepper history."""
search_delay = datetime.timedelta(minutes=5)
"""From when should we check datagrepper."""

# Constants
JENKINS_URL: str = "https://osci-jenkins-1.ci.fedoraproject.org/job/fedora-ci/job/dist-git-trigger/job/master/buildWithParameters"
DATAGREPPER_URL: str = "https://apps.fedoraproject.org/datagrepper/v2/search"
RABBITMQ_TOPIC: str = (
    "org.fedoraproject.prod.bodhi.update.status.testing.koji-build-group.build.complete"
)
# Format: `{user}:{auth_token}`
JENKINS_TOKEN = os.environ.get("JENKINS_TOKEN", None)

if not dry_run:
    if not JENKINS_TOKEN:
        logger.error("JENKINS_TOKEN not passed, cannot do retriggger")
        exit(1)
    auth = HTTPBasicAuth(*JENKINS_TOKEN.split(":"))

REQUESTS_PER_PAGE: int = 50
CACHE_FILE = Path("cache.json")


class CacheState(enum.Enum):
    UNKNOWN = 0
    ALL_GREEN = 1
    FAILED = 2


@dataclasses.dataclass
class UpdateInfo:
    msg: dict[str, typing.Any] | None
    state: CacheState


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, CacheState):
            return str(o)
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


bodhi_updates: dict[str, UpdateInfo]
curr_page: int = 1
total_pages: int | None = None
expected_updates: int | None = None

search_end = datetime.datetime.now(datetime.UTC) - search_delay
search_start = search_end - search_window

session = requests.Session()
retries = Retry(total=3, backoff_factor=1)
session.mount("https://", HTTPAdapter(max_retries=retries))
bodhi_client = BodhiClient()

CACHE_FILE.touch(exist_ok=True)
with CACHE_FILE.open("rt") as f:
    try:
        bodhi_updates_dict = json.load(f)
    except json.JSONDecodeError:
        bodhi_updates_dict = {}
bodhi_updates = {
    updateid: UpdateInfo(
        msg=info["msg"],
        state=CacheState[info["state"].removeprefix("CacheState.")],
    )
    for updateid, info in bodhi_updates_dict.items()
}


def save_bodhi_update(msg: dict[str, typing.Any]) -> None:
    updateid = msg["body"]["update"]["updateid"]
    cached_msg = msg["body"]
    cached_state = CacheState.UNKNOWN
    if updateid in bodhi_updates:
        cached_update = bodhi_updates[updateid]
        cached_msg = cached_update.msg
        cached_state = cached_update.state
    bodhi_updates[updateid] = UpdateInfo(
        msg=cached_msg,
        state=cached_state,
    )


def get_bodhi_updates(page: int = 1) -> None:
    global total_pages, expected_updates
    params = dict(
        category="bodhi",
        topic=RABBITMQ_TOPIC,
        rows_per_page=REQUESTS_PER_PAGE,
        page=page,
        start=search_start.timestamp(),
        end=search_end.timestamp(),
    )
    response = session.get(
        DATAGREPPER_URL,
        params=params,
        timeout=5,
    )
    if response.status_code != 200:
        logger.error(f"Failed[{response.status_code}] at page {page}")
        exit(1)
    response_json = response.json()
    if not total_pages and not expected_updates:
        total_pages = response_json["pages"]
        expected_updates = response_json["total"]
    for msg in response_json["raw_messages"]:
        save_bodhi_update(msg)


def retigger_fedora_ci(update: UpdateInfo):
    if dry_run:
        print(json.dumps(update.msg))
    else:
        session.post(
            JENKINS_URL,
            params=dict(CI_MESSAGE=json.dumps(update.msg)),
            auth=auth,
        )


# Get all bodhi updates we know about
if recheck_datagrepper:
    while not total_pages or curr_page < total_pages:
        get_bodhi_updates(page=curr_page)
        curr_page = curr_page + 1

    with CACHE_FILE.open("wt") as f:
        json.dump(bodhi_updates, f, cls=CustomJSONEncoder)

if not bodhi_updates:
    logger.info(f"No new updates were made in the past {search_window}")
    exit(0)

for updateid, update_info in bodhi_updates.items():
    if isinstance(update_info, dict):
        bodhi_updates[updateid] = UpdateInfo(
            msg=update_info["msg"],
            state=CacheState[update_info["state"].removeprefix("CacheState.")],
        )

for updateid, update_info in bodhi_updates.items():
    if update_info.state == CacheState.ALL_GREEN:
        logger.info(f"Skipping {updateid} (cached)")
        continue
    logger.info(f"Checking update: {updateid}")
    test_status = bodhi_client.get_test_status(updateid)
    update_info.state = CacheState.ALL_GREEN
    if not test_status.decisions:
        logger.warning(f"Could not get test_status of {updateid}!")
        continue
    if len(test_status.decisions) > 1:
        logger.warning(
            f"We found more than 1 decision with the same updateid={updateid} :/"
        )
    for decision in test_status.decisions:
        missing_tests_res: list[tuple[str, str]] = []
        for res in decision.unsatisfied_requirements:
            if not res.testcase.startswith(
                ("fedora-ci.koji-build./", "fedora-ci.koji-build.tier0")
            ):
                continue
            if res.type == "test-result-missing":
                missing_tests_res.append((res.testcase, res.subject_identifier))
        for res in decision.results:
            if not res.testcase.name.startswith(
                ("fedora-ci.koji-build./", "fedora-ci.koji-build.tier0")
            ):
                continue
            if res.outcome not in ("RUNNING", "PASSED"):
                if res.outcome == "FAILED":
                    pass
                else:
                    update_info.state = CacheState.FAILED
            check_tuple = (res.testcase.name, res.data.item)
            if check_tuple in missing_tests_res:
                missing_tests_res.remove(check_tuple)
        if missing_tests_res:
            update_info.state = CacheState.FAILED
    if update_info.state == CacheState.FAILED:
        logger.info("Retriggering Fedora-CI")
        retigger_fedora_ci(update_info)
    else:
        update_info.msg = None
        logger.info("All good, moving on")
    with CACHE_FILE.open("wt") as f:
        json.dump(bodhi_updates, f, cls=CustomJSONEncoder)
