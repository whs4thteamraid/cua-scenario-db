# Modified from xlang-ai/OSWorld (commit 091f5ef, Apache License 2.0) for cua-scenario-db.
# The changes are listed in the repository NOTICE file.
import logging
import os
import platform
import re
import subprocess
import time
import unicodedata

from desktop_env.providers.base import Provider

logger = logging.getLogger("desktopenv.providers.vmware.VMwareProvider")
logger.setLevel(logging.INFO)

WAIT_TIME = 3

# vmrun getGuestIPAddress 의 반환이 IP 인지 검증할 때 쓴다. 아래 get_ip_address 참조.
_IPV4_RE = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")

# How long start_emulator may keep retrying before giving up. The loop used to
# have no bound at all, so a path that never compares equal (see _same_path)
# span forever with no output.
START_TIMEOUT = 300


def _same_path(a: str, b: str) -> bool:
    """Compare two filesystem paths, Unicode normalization included.

    macOS stores filenames decomposed (NFD) and hands them back that way, while
    a path typed in Python source or read from a config is usually composed
    (NFC). For an ASCII path the two are identical, so a plain ``==`` works and
    nobody notices --- until the repository lives under a directory with
    non-ASCII characters. Then ``vmrun list`` returns the NFD spelling, the
    comparison never matches, and start_emulator relaunches the VM forever.
    """
    def norm(p: str) -> str:
        return unicodedata.normalize("NFC", os.path.abspath(os.path.normpath(p.strip())))
    return norm(a) == norm(b)


def get_vmrun_type(return_list=False):
    if platform.system() == 'Windows' or platform.system() == 'Linux':
        if return_list:
            return ['-T', 'ws']
        else:
            return '-T ws'
    elif platform.system() == 'Darwin':  # Darwin is the system name for macOS
        if return_list:
            return ['-T', 'fusion']
        else:
            return '-T fusion'
    else:
        raise Exception("Unsupported operating system")


class VMwareProvider(Provider):
    @staticmethod
    def _execute_command(command: list, return_output=False):
        """Run a vmrun command and **always wait for it to finish**.

        Previously the ``return_output=False`` branch returned without calling
        ``communicate()``, so the child process was never waited for. Every
        state-changing vmrun call goes through that branch --- ``start``,
        ``stop``, ``snapshot``, ``revertToSnapshot`` --- and each is followed
        only by ``time.sleep(WAIT_TIME)`` (3s). A snapshot revert takes far
        longer than that, so the next vmrun call would be issued while the
        revert was still in flight. Two observed failures:

        * ``revertToSnapshot`` still running when ``start`` powers the VM on and
          ``getGuestIPAddress`` is issued --- vmrun prints ``Error: ...`` which
          the caller then used as a hostname (``host='error'``).
        * ``stop`` not finished when the next session opens, so it attaches to
          the IP of a VM that is shutting down (``:5000 connect timeout``).

        The exit code was discarded as well, so failures passed silently.
        """
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8"
        )
        out, err = process.communicate()
        if process.returncode != 0:
            logger.error("vmrun failed (rc=%s): %s\n%s%s",
                         process.returncode, " ".join(command), out or "", err or "")
        return (out or "").strip() if return_output else None

    def start_emulator(self, path_to_vm: str, headless: bool, os_type: str):
        print("Starting VMware VM...")
        logger.info("Starting VMware VM...")

        deadline = time.time() + START_TIMEOUT
        while True:
            if time.time() > deadline:
                raise RuntimeError(
                    f"VM did not appear in `vmrun list` within {START_TIMEOUT}s: {path_to_vm}")
            try:
                output = subprocess.check_output(f"vmrun {get_vmrun_type()} list", shell=True, stderr=subprocess.STDOUT)
                output = output.decode()
                output = output.splitlines()

                if any(_same_path(line, path_to_vm) for line in output):
                    logger.info("VM is running.")
                    break
                else:
                    logger.info("Starting VM...")
                    _command = ["vmrun"] + get_vmrun_type(return_list=True) + ["start", path_to_vm]
                    if headless:
                        _command.append("nogui")
                    VMwareProvider._execute_command(_command)
                    time.sleep(WAIT_TIME)

            except subprocess.CalledProcessError as e:
                logger.error(f"Error executing command: {e.output.decode().strip()}")

    def get_ip_address(self, path_to_vm: str) -> str:
        """Return the guest IP, retrying until vmrun actually yields one.

        ``vmrun getGuestIPAddress`` prints ``Error: ...`` on stdout when the
        guest has no address yet (tools still starting, or another vmrun
        operation in flight). The previous version returned that string as if it
        were an address, so it ended up as the HTTP host --- surfacing much later
        as ``NameResolutionError(host='error')`` with no hint of the real cause.
        Validating the shape here turns a silent corruption into the retry this
        loop was already written to do.
        """
        logger.info("Getting VMware VM IP address...")
        while True:
            try:
                output = VMwareProvider._execute_command(
                    ["vmrun"] + get_vmrun_type(return_list=True) + ["getGuestIPAddress", path_to_vm, "-wait"],
                    return_output=True
                )
                if _IPV4_RE.fullmatch((output or "").strip()):
                    logger.info(f"VMware VM IP address: {output}")
                    return output
                logger.warning(
                    "getGuestIPAddress returned a non-IP value: %r --- retrying", output)
            except Exception as e:
                logger.error(e)
            time.sleep(WAIT_TIME)
            logger.info("Retrying to get VMware VM IP address...")

    def save_state(self, path_to_vm: str, snapshot_name: str):
        logger.info("Saving VMware VM state...")
        VMwareProvider._execute_command(
            ["vmrun"] + get_vmrun_type(return_list=True) + ["snapshot", path_to_vm, snapshot_name])
        time.sleep(WAIT_TIME)  # Wait for the VM to save

    def revert_to_snapshot(self, path_to_vm: str, snapshot_name: str):
        logger.info(f"Reverting VMware VM to snapshot: {snapshot_name}...")
        VMwareProvider._execute_command(
            ["vmrun"] + get_vmrun_type(return_list=True) + ["revertToSnapshot", path_to_vm, snapshot_name])
        time.sleep(WAIT_TIME)  # Wait for the VM to revert
        return path_to_vm

    def stop_emulator(self, path_to_vm: str, region=None, *args, **kwargs):
        # Note: region parameter is ignored for VMware provider
        # but kept for interface consistency with other providers
        logger.info("Stopping VMware VM...")
        VMwareProvider._execute_command(["vmrun"] + get_vmrun_type(return_list=True) + ["stop", path_to_vm])
        time.sleep(WAIT_TIME)  # Wait for the VM to stop
