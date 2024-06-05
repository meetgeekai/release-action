import os
import re
import sys
import time
import logging
from jenkins import Jenkins
from urllib.parse import urlparse, urlunparse, ParseResult


logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s][%(asctime)s] %(name)s :: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)


def _get_private_console_url(build_url, build_number):
    parsed_url: ParseResult = urlparse(build_url)

    new_scheme = "http"
    new_netloc = "jenkins.jenkins.svc.cluster.local:8080"
    new_path = re.sub(r"/build$", rf"/{build_number}/console", parsed_url.path)

    return urlunparse(
        (
            new_scheme,
            new_netloc,
            new_path,
            parsed_url.params,
            parsed_url.query,
            parsed_url.fragment,
        )
    )


def _parse_params(params_string: str):
    if not params_string:
        return {}

    try:
        output = {}
        params_pairs = params_string.split(",")
        for pair in params_pairs:
            var, val = pair.split("=")
            output[var] = val
        return output
    except Exception as e:
        logger.error(f"Could not parse the build parameters: {e}")
        sys.exit(1)


class JenkinsServer:
    def __init__(
        self,
        server_url=os.getenv("JENKINS_URL"),
        username=os.getenv("JENKINS_USER"),
        token=os.getenv("JENKINS_TOKEN"),
        job_name=os.getenv("JENKINS_JOB_NAME"),
        poll_interval_seconds=os.getenv("POLL_INTERVAL_SECONDS", 45),
        build_timeout_minutes=os.getenv("BUILD_TIMEOUT_MINUTES", 60),
    ):
        self.server_url = server_url
        self.username = username
        self.token = token
        self.server = Jenkins(
            url=self.server_url,
            username=self.username,
            password=self.token,
        )
        self.job_name = job_name
        self.poll_interval_seconds = int(poll_interval_seconds)
        self.build_timeout_minutes = int(build_timeout_minutes) * 60

        self._test_connection()

    def _test_connection(self):
        user = self.server.get_whoami()
        version = self.server.get_version()
        logger.info(
            f"Connected as user {user['fullName']} on Jenkins with version {version}"
        )

    def launch_parametrized_build(self, params):
        return self.server.build_job(self.job_name, parameters=params)

    def _get_build_number(self, queue_item_number: int):
        attempts = 0
        while attempts < 240:
            try:
                queue_item = self.server.get_queue_item(queue_item_number)
                build_number = int(queue_item["executable"]["number"])
                logger.info(f"Build #{build_number} launched")
                return build_number
            except (KeyError, TypeError):
                logger.info("Waiting for build to launch...")
                time.sleep(5)

            attempts += 1

    def poll_for_result(self, build_number: int):
        start_time = time.time()

        while True:
            build = self.server.get_build_info(self.job_name, build_number)
            result = build["result"]

            if result == "SUCCESS":
                logger.info(f"Build successful for job {self.job_name} #{build_number}")
                break
            elif result in ["FAILURE", "ABORTED", "UNSTABLE"]:
                build_url = self.server.build_job_url(self.job_name)
                console_url = _get_private_console_url(build_url, build_number)
                logger.error(f"Build failed. Check console logs: {console_url}")
                sys.exit(1)
            else:
                logger.info(
                    f"Build is still running. Polling again in {self.poll_interval_seconds} seconds..."
                )

            elapsed_time = time.time() - start_time
            if elapsed_time > self.build_timeout_minutes:
                logger.error(
                    f"Build #{build_number} for job {self.job_name} has timed out after {elapsed_time/60:.1f} minutes"
                )
                sys.exit(1)
            else:
                time.sleep(self.poll_interval_seconds)

    def run(self, params_string=os.getenv("BUILD_PARAMETERS", "")):
        params = _parse_params(params_string)
        queue_item_number = self.launch_parametrized_build(params)

        build_number = self._get_build_number(queue_item_number)
        if not build_number:
            logger.error(f"Could not fetch build number for job {self.job_name}")
            sys.exit(1)

        self.poll_for_result(build_number)


if __name__ == "__main__":
    jenkins = JenkinsServer()
    jenkins.run()
