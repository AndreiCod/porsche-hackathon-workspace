# DistUpgradeQuirks.py
#
#  Copyright (c) 2004-2010 Canonical
#
#  Author: Michael Vogt <michael.vogt@ubuntu.com>
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation; either version 2 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307
#  USA

import apt
import atexit
import distro_info
import glob
import logging
import os
import re
import hashlib
import subprocess
from subprocess import PIPE, Popen

from .utils import get_arch

from .DistUpgradeGettext import gettext as _


class DistUpgradeQuirks(object):
    """
    This class collects the various quirks handlers that can
    be hooked into to fix/work around issues that the individual
    releases have
    """

    def __init__(self, controller, config):
        self.controller = controller
        self._view = controller._view
        self.config = config
        self.uname = Popen(["uname", "-r"], stdout=PIPE,
                           universal_newlines=True).communicate()[0].strip()
        self.arch = get_arch()
        self.extra_snap_space = 0
        self._poke = None
        self._snapstore_reachable = False
        self._snap_list = None
        self._from_version = None
        self._to_version = None

    # the quirk function have the name:
    #  $Name (e.g. PostUpgrade)
    #  $todist$Name (e.g. intrepidPostUpgrade)
    #  $from_$fromdist$Name (e.g. from_dapperPostUpgrade)
    def run(self, quirksName):
        """
        Run the specific quirks handler, the follow handlers are supported:
        - PreCacheOpen: run *before* the apt cache is opened the first time
                        to set options that affect the cache
        - PostInitialUpdate: run *before* the sources.list is rewritten but
                             after an initial apt-get update
        - PreDistUpgradeCache: run *right before* the dist-upgrade is
                               calculated in the cache
        - PostDistUpgradeCache: run *after* the dist-upgrade was calculated
                                in the cache
        - StartUpgrade: before the first package gets installed (but the
                        download is finished)
        - PostUpgrade: run *after* the upgrade is finished successfully and
                       packages got installed
        - PostCleanup: run *after* the cleanup (orphaned etc) is finished
        """
        # we do not run any quirks in partialUpgrade mode
        if self.controller._partialUpgrade:
            logging.info("not running quirks in partialUpgrade mode")
            return
        to_release = self.config.get("Sources", "To")
        from_release = self.config.get("Sources", "From")

        # run the handler that is common to all dists
        funcname = "%s" % quirksName
        func = getattr(self, funcname, None)
        if func is not None:
            logging.debug("quirks: running %s" % funcname)
            func()

        # run the quirksHandler to-dist
        funcname = "%s%s" % (to_release, quirksName)
        func = getattr(self, funcname, None)
        if func is not None:
            logging.debug("quirks: running %s" % funcname)
            func()

        # now run the quirksHandler from_${FROM-DIST}Quirks
        funcname = "from_%s%s" % (from_release, quirksName)
        func = getattr(self, funcname, None)
        if func is not None:
            logging.debug("quirks: running %s" % funcname)
            func()

    # individual quirks handler that run *before* the cache is opened
    def PreCacheOpen(self):
        """ run before the apt cache is opened the first time """
        logging.debug("running Quirks.PreCacheOpen")

    # individual quirks handler that run *after* the cache is opened
    def jammyPostInitialUpdate(self):
        # PreCacheOpen would be better but controller.abort fails terribly
        """ run after the apt cache is opened the first time """
        logging.debug("running Quirks.jammyPostInitialUpdate")
        self._get_from_and_to_version()
        self._test_and_fail_on_i386()
        self._test_and_fail_on_aufs()
        self._test_and_fail_on_power8()
        self._test_and_fail_on_pam_tally()

        cache = self.controller.cache
        self._test_and_warn_if_ros_installed(cache)
        self._fix_missing_nvidia_metapackage()

        if 'snapd' not in cache:
            logging.debug("package required for Quirk not in cache")
            return
        if cache['snapd'].is_installed and \
                (os.path.exists('/run/snapd.socket') or
                 os.path.exists('/run/snapd-snap.socket')):
            self._checkStoreConnectivity()
        # If the snap store is accessible, at the same time calculate the
        # extra size needed by to-be-installed snaps.  This also prepares
        # the snaps-to-install list for the actual upgrade.
        if self._snapstore_reachable:
            self._calculateSnapSizeRequirements()

    def jammyPostUpgrade(self):
        logging.debug("running Quirks.jammyPostUpgrade")
        cache = self.controller.cache
        if 'snapd' not in cache:
            logging.debug("package required for Quirk not in cache")
            return
        if cache['snapd'].is_installed and \
                self._snap_list:
            self._replaceDebsAndSnaps()
        if 'ubuntu-desktop-raspi' in cache:
            if cache['ubuntu-desktop-raspi'].is_installed:
                self._replace_fkms_overlay()
        if 'linux-firmware-raspi2' in cache:
            if cache['linux-firmware-raspi2'].is_installed:
                self._remove_uboot_on_rpi()
                self._remove_netplan_match_rpi()

    # individual quirks handler when the dpkg run is finished ---------
    def PostCleanup(self):
        " run after cleanup "
        logging.debug("running Quirks.PostCleanup")

    # run right before the first packages get installed
    def StartUpgrade(self):
        logging.debug("running Quirks.StartUpgrade")
        self._applyPatches()
        self._removeOldApportCrashes()
        self._killUpdateNotifier()
        self._killKBluetooth()
        self._pokeScreensaver()
        self._stopDocvertConverter()

    # individual quirks handler that run *right before* the dist-upgrade
    # is calculated in the cache
    def PreDistUpgradeCache(self):
        """ run right before calculating the dist-upgrade """
        logging.debug("running Quirks.PreDistUpgradeCache")
        # self._install_python_is_python2()

    # individual quirks handler that run *after* the dist-upgrade was
    # calculated in the cache
    def PostDistUpgradeCache(self):
        """ run after calculating the dist-upgrade """
        logging.debug("running Quirks.PostDistUpgradeCache")
        self._install_linux_metapackage()

    # helpers
    def _get_pci_ids(self):
        """ return a set of pci ids of the system (using lspci -n) """
        lspci = set()
        try:
            p = subprocess.Popen(["lspci", "-n"], stdout=subprocess.PIPE,
                                 universal_newlines=True)
        except OSError:
            return lspci
        for line in p.communicate()[0].split("\n"):
            if line:
                lspci.add(line.split()[2])
        return lspci

    def _get_from_and_to_version(self):
        di = distro_info.UbuntuDistroInfo()
        try:
            self._from_version = \
                di.version('%s' % self.controller.fromDist).split()[0]
            self._to_version = \
                di.version('%s' % self.controller.toDist).split()[0]
        # Ubuntu 18.04's python3-distro-info does not have version
        except AttributeError:
            self._from_version = next(
                (r.version for r in di.get_all("object")
                 if r.series == self.controller.fromDist),
                self.controller.fromDist).split()[0]
            self._to_version = next(
                (r.version for r in di.get_all("object")
                 if r.series == self.controller.toDist),
                self.controller.toDist).split()[0]

    def _test_and_warn_for_unity_3d_support(self):
        UNITY_SUPPORT_TEST = "/usr/lib/nux/unity_support_test"
        if (not os.path.exists(UNITY_SUPPORT_TEST) or
                "DISPLAY" not in os.environ):
            return
        # see if there is a running unity, that service is used by both 2d,3d
        return_code = subprocess.call(
            ["ps", "-C", "unity-panel-service"], stdout=open(os.devnull, "w"))
        if return_code != 0:
            logging.debug(
                "_test_and_warn_for_unity_3d_support: no unity running")
            return
        # if we are here, we need to test and warn
        return_code = subprocess.call([UNITY_SUPPORT_TEST])
        logging.debug(
            "_test_and_warn_for_unity_3d_support '%s' returned '%s'" % (
                UNITY_SUPPORT_TEST, return_code))
        if return_code != 0:
            res = self._view.askYesNoQuestion(
                _("Your graphics hardware may not be fully supported in "
                  "Ubuntu 14.04."),
                _("Running the 'unity' desktop environment is not fully "
                  "supported by your graphics hardware. You will maybe end "
                  "up in a very slow environment after the upgrade. Our "
                  "advice is to keep the LTS version for now. For more "
                  "information see "
                  "https://wiki.ubuntu.com/X/Bugs/"
                  "UpdateManagerWarningForUnity3D "
                  "Do you still want to continue with the upgrade?")
            )
            if not res:
                self.controller.abort()

    def _test_and_warn_on_i8xx(self):
        I8XX_PCI_IDS = ["8086:7121",  # i810
                        "8086:7125",  # i810e
                        "8086:1132",  # i815
                        "8086:3577",  # i830
                        "8086:2562",  # i845
                        "8086:3582",  # i855
                        "8086:2572",  # i865
                        ]
        lspci = self._get_pci_ids()
        if set(I8XX_PCI_IDS).intersection(lspci):
            res = self._view.askYesNoQuestion(
                _("Your graphics hardware may not be fully supported in "
                  "Ubuntu 12.04 LTS."),
                _("The support in Ubuntu 12.04 LTS for your Intel "
                  "graphics hardware is limited "
                  "and you may encounter problems after the upgrade. "
                  "For more information see "
                  "https://wiki.ubuntu.com/X/Bugs/UpdateManagerWarningForI8xx "
                  "Do you want to continue with the upgrade?")
            )
            if not res:
                self.controller.abort()

    def _test_and_warn_on_dropped_fglrx_support(self):
        """
        Some cards are no longer supported by fglrx. Check if that
        is the case and warn
        """
        # this is to deal with the fact that support for some of the cards
        # that fglrx used to support got dropped
        if (self._checkVideoDriver("fglrx") and
                not self._supportInModaliases("fglrx")):
            res = self._view.askYesNoQuestion(
                _("Upgrading may reduce desktop "
                  "effects, and performance in games "
                  "and other graphically intensive "
                  "programs."),
                _("This computer is currently using "
                  "the AMD 'fglrx' graphics driver. "
                  "No version of this driver is "
                  "available that works with your "
                  "hardware in Ubuntu 10.04 LTS.\n\n"
                  "Do you want to continue?"))
            if not res:
                self.controller.abort()
            # if the user wants to continue we remove the fglrx driver
            # here because its no use (no support for this card)
            removals = [
                "xorg-driver-fglrx",
                "xorg-driver-fglrx-envy",
                "fglrx-kernel-source",
                "fglrx-amdcccle",
                "xorg-driver-fglrx-dev",
                "libamdxvba1"
            ]
            logging.debug("remove %s" % ", ".join(removals))
            postupgradepurge = self.controller.config.getlist(
                "Distro",
                "PostUpgradePurge")
            for remove in removals:
                postupgradepurge.append(remove)
            self.controller.config.set("Distro", "PostUpgradePurge",
                                       ",".join(postupgradepurge))

    def _test_and_fail_on_i386(self):
        """
        Test and fail if the package architecture is i386 as we
        have dropped support for this architecture.
        """
        if self._from_version == '18.04':
            updates_end = 'April 2023'
        elif self._from_version == '19.04':
            updates_end = 'January 2020'
        # check on i386 only
        if self.arch == "i386":
            logging.error("apt architecture is i386")
            summary = _("Sorry, no more upgrades for this system")
            msg = _("There will not be any further Ubuntu releases "
                    "for this system's 'i386' architecture.\n\n"
                    "Updates for Ubuntu %s will continue until %s." %
                    (self._from_version, updates_end))
            self._view.error(summary, msg)
            self.controller.abort()

    def _test_and_fail_on_non_arm_v6(self):
        """
        Test and fail if the cpu is not a arm v6 or greater,
        from 9.10 on we do no longer support those CPUs
        """
        if self.arch == "armel":
            if not self._checkArmCPU():
                self._view.error(
                    _("No ARMv6 CPU"),
                    _("Your system uses an ARM CPU that is older "
                      "than the ARMv6 architecture. "
                      "All packages in karmic were built with "
                      "optimizations requiring ARMv6 as the "
                      "minimal architecture. It is not possible to "
                      "upgrade your system to a new Ubuntu release "
                      "with this hardware."))
                self.controller.abort()

    def _test_and_fail_on_aufs(self):
        """
        Test and fail if docker has aufs storage driver available
        as it is deprecated after 20.04. Even if no containers are
        currently running aufs, the upgrade could break existing
        container images.
        """
        for aufs_dir in ("/var/snap/docker/common/var-lib-docker/aufs",
                         "/var/lib/docker/aufs"):
            if (os.path.exists(aufs_dir)):
                logging.error("Docker config uses aufs")
                summary = _("Sorry, this storage driver is not supported "
                            "in kernels for newer releases")
                msg = _("There will not be any further Ubuntu releases "
                        "that provide kernel support for the aufs "
                        "storage driver.\n\n"
                        "Please ensure that none of your containers are "
                        "using the aufs storage driver, remove the directory "
                        "%s and try again." % aufs_dir)
                self._view.error(summary, msg)
                self.controller.abort()

    def _test_and_fail_on_pam_tally(self):
        """
        Test and fail if pam_tally or pam_tally2 appears in the system's
        PAM config for any service.  These modules have been dropped as
        obsolete, so references to them in the config will break services
        on upgrade.  The libpam-modules package has a preinst that will also
        enforce this, but we want to enforce at the start of the upgrade
        before we get halfway through an apt transaction.  LP: #1977493
        """

        for f in os.listdir('/etc/pam.d'):
            if f in ('common-account', 'common-auth', 'common-password',
                     'common-session', 'common-session-noninteractive'):
                # managed by pam-auth-updates, and any references to
                # pam_tally* will be handled by libpam-modules on upgrade
                # without breaking
                continue
            with open(os.path.join('/etc/pam.d', f)) as f:
                content = f.read()
                if re.search('^[^#]*pam_tally', content, re.MULTILINE):
                    logging.error("pam_tally* in use")
                    # from libpam-modules.templates
                    summary = _("You are using pam_tally or pam_tally2 in "
                                "your configuration.")
                    msg = _("The pam_tally and pam_tally2 modules have been "
                            "removed from PAM. You are using one of these "
                            "modules in your PAM configuration in /etc/pam.d. "
                            "You must remove the uses of these modules before "
                            "PAM can be upgraded; including these modules in "
                            "your PAM configuration after the upgrade will "
                            "stop users from being able to log into the "
                            "system.") + "\n\n" + \
                        _("Consider the pam_faillock module as a "
                          "replacement for pam_tally.")
                    self._view.error(summary, msg)
                    self.controller.abort()
                    return

    def _test_and_fail_on_power8(self):
        """
        Test and fail if running on a POWER8 processor. Starting with Ubuntu
        22.04, ppc64el is compiled for POWER9 processors. Prior to 22.04 it
        was/is compiled for POWER8 processors. Hence POWER8 processors are not
        able to run, install or upgrade to jammy.
        """
        if self.arch != "ppc64el":
            return

        updates_end = ""
        if self._from_version == "20.04":
            updates_end = "April 2025"
        elif self._from_version == "21.10":
            updates_end = "July 2022"

        with open("/proc/cpuinfo") as f:
            cpuinfo = f.read()

            if re.search("^cpu\s*:\s*POWER8", cpuinfo, re.MULTILINE):
                logging.error("POWER8 processor detected")
                summary = _("Sorry, no more upgrades for this system")
                msg = _("There will not be any further Ubuntu releases "
                        "for this system's POWER8 processor.\n\n"
                        "Updates for Ubuntu %s will continue until %s." %
                        (self._from_version, updates_end))
                self._view.error(summary, msg)
                self.controller.abort()

    def _test_and_warn_if_vserver(self):
        """
        upstart and vserver environments are not a good match, warn
        if we find one
        """
        # verver test (LP: #454783), see if there is a init around
        try:
            os.kill(1, 0)
        except OSError:
            logging.warning("no init found")
            res = self._view.askYesNoQuestion(
                _("No init available"),
                _("Your system appears to be a virtualised environment "
                  "without an init daemon, e.g. Linux-VServer. "
                  "Ubuntu 10.04 LTS cannot function within this type of "
                  "environment, requiring an update to your virtual "
                  "machine configuration first.\n\n"
                  "Are you sure you want to continue?"))
            if not res:
                self.controller.abort()
            self._view.processEvents()

    def _test_and_warn_if_ros_installed(self, cache):
        """
        Test and warn if ROS is installed. A given ROS release only
        supports specific Ubuntu releases, and can cause the upgrade
        to fail in an overly-cryptic manner.
        """

        # These are the root ROS 1 and 2 dependencies as of 07/27/2020
        ros_package_patterns = set()
        for package_name in (
                "catkin",
                "rosboost-cfg",
                "rosclean",
                "ros-environment",
                "ros-workspace"):
            ros_package_patterns.add(
                re.compile("ros-[^\-]+-%s" % package_name))

        ros_is_installed = False
        for pkg in cache:
            if ros_is_installed:
                break

            for pattern in ros_package_patterns:
                if pattern.match(pkg.name):
                    if pkg.is_installed or pkg.marked_install:
                        ros_is_installed = True
                    break

        if ros_is_installed:
            res = self._view.askYesNoQuestion(
                _("The Robot Operating System (ROS) is installed"),
                _("It appears that ROS is currently installed. Each ROS "
                  "release is very strict about the versions of Ubuntu "
                  "it supports, and Ubuntu upgrades can fail if that "
                  "guidance isn't followed. Before continuing, please "
                  "either uninstall ROS, or ensure the ROS release you "
                  "have installed supports the version of Ubuntu to "
                  "which you're upgrading.\n\n"
                  "For ROS 1 releases, refer to REP 3:\n"
                  "https://www.ros.org/reps/rep-0003.html\n\n"
                  "For ROS 2 releases, refer to REP 2000:\n"
                  "https://www.ros.org/reps/rep-2000.html\n\n"
                  "Are you sure you want to continue?"))
            if not res:
                self.controller.abort()

    def _checkArmCPU(self):
        """
        parse /proc/cpuinfo and search for ARMv6 or greater
        """
        logging.debug("checking for ARM CPU version")
        if not os.path.exists("/proc/cpuinfo"):
            logging.error("cannot open /proc/cpuinfo ?!?")
            return False
        with open("/proc/cpuinfo") as f:
            cpuinfo = f.read()
        if re.search("^Processor\s*:\s*ARMv[45]", cpuinfo,
                     re.MULTILINE):
            return False
        return True

    def _readDMIVendor(self):
        """
        read /sys/class/dmi/id/sys_vendor in case there are
        system specific issues with upgrading e.g LP: #1928434
        """
        logging.debug("checking for system vendor")
        if not os.path.exists("/sys/class/dmi/id/sys_vendor"):
            logging.error("cannot open /sys/class/dmi/id/sys_vendor")
            return ''
        with open("/sys/class/dmi/id/sys_vendor") as f:
            vendor = f.read()
        return vendor

    def _stopApparmor(self):
        """ /etc/init.d/apparmor stop (see bug #559433)"""
        if os.path.exists("/etc/init.d/apparmor"):
            logging.debug("/etc/init.d/apparmor stop")
            subprocess.call(["/etc/init.d/apparmor", "stop"])

    def _stopDocvertConverter(self):
        " /etc/init.d/docvert-converter stop (see bug #450569)"
        if os.path.exists("/etc/init.d/docvert-converter"):
            logging.debug("/etc/init.d/docvert-converter stop")
            subprocess.call(["/etc/init.d/docvert-converter", "stop"])

    def _killUpdateNotifier(self):
        "kill update-notifier"
        # kill update-notifier now to suppress reboot required
        if os.path.exists("/usr/bin/killall"):
            logging.debug("killing update-notifier")
            subprocess.call(["killall", "-q", "update-notifier"])

    def _killKBluetooth(self):
        """killall kblueplugd kbluetooth (riddel requested it)"""
        if os.path.exists("/usr/bin/killall"):
            logging.debug("killing kblueplugd kbluetooth4")
            subprocess.call(["killall", "-q", "kblueplugd", "kbluetooth4"])

    def _pokeScreensaver(self):
        if (os.path.exists("/usr/bin/xdg-screensaver") and
                os.environ.get('DISPLAY')):
            logging.debug("setup poke timer for the screensaver")
            cmd = "while true;"
            cmd += " do /usr/bin/xdg-screensaver reset >/dev/null 2>&1;"
            cmd += " sleep 30; done"
            try:
                self._poke = subprocess.Popen(cmd, shell=True)
                atexit.register(self._stopPokeScreensaver)
            except (OSError, ValueError):
                logging.exception("failed to setup screensaver poke")

    def _stopPokeScreensaver(self):
        res = False
        if self._poke is not None:
            try:
                self._poke.terminate()
                res = self._poke.wait()
            except OSError:
                logging.exception("failed to stop screensaver poke")
            self._poke = None
        return res

    def _removeOldApportCrashes(self):
        " remove old apport crash files and whoopsie control files "
        try:
            for ext in ['.crash', '.upload', '.uploaded']:
                for f in glob.glob("/var/crash/*%s" % ext):
                    logging.debug("removing old %s file '%s'" % (ext, f))
                    os.unlink(f)
        except Exception as e:
            logging.warning("error during unlink of old crash files (%s)" % e)

    def _checkStoreConnectivity(self):
        """ check for connectivity to the snap store to install snaps"""
        res = False
        snap_env = os.environ.copy()
        snap_env["LANG"] = "C.UTF-8"
        connected = Popen(["snap", "debug", "connectivity"], stdout=PIPE,
                          stderr=PIPE, env=snap_env,
                          universal_newlines=True).communicate()
        if re.search("^ \* PASS", connected[0], re.MULTILINE):
            self._snapstore_reachable = True
            return
        # can't connect
        elif re.search("^ \*.*unreachable", connected[0], re.MULTILINE):
            logging.error("No snap store connectivity")
            old_lxd_deb_installed = False
            cache = self.controller.cache
            if 'lxd' in cache:
                # epoch 1 is the transitional deb
                if cache['lxd'].is_installed and not \
                        cache['lxd'].candidate.version.startswith("1:"):
                    logging.error("lxd is installed")
                    old_lxd_deb_installed = True
            if old_lxd_deb_installed:
                summary = _("Connection to the Snap Store failed")
                msg = _("You have the package lxd installed but your "
                        "system is unable to reach the Snap Store. "
                        "lxd is now provided via a snap and the release "
                        "upgrade will fail if snapd is not functional. "
                        "Please make sure you're connected to the "
                        "Internet and update any firewall or proxy "
                        "settings as needed so that you can reach "
                        "api.snapcraft.io. If you are an enterprise "
                        "with a firewall setup you may want to configure "
                        "a Snap Store proxy."
                        )
                self._view.error(summary, msg)
                self.controller.abort()
            else:
                res = self._view.askYesNoQuestion(
                    _("Connection to Snap Store failed"),
                    _("Your system does not have a connection to the Snap "
                      "Store. For the best upgrade experience make sure "
                      "that your system can connect to api.snapcraft.io.\n"
                      "Do you still want to continue with the upgrade?")
                )
        # debug command not available
        elif 'error: unknown command' in connected[1]:
            logging.error("snap debug command not available")
            res = self._view.askYesNoQuestion(
                _("Outdated snapd package"),
                _("Your system does not have the latest version of snapd. "
                  "Please update the version of snapd on your system to "
                  "improve the upgrade experience.\n"
                  "Do you still want to continue with the upgrade?")
            )
        # not running as root
        elif 'error: access denied' in connected[1]:
            res = False
            logging.error("Not running as root!")
        else:
            logging.error("Unhandled error connecting to the snap store.")
        if not res:
            self.controller.abort()

    def _calculateSnapSizeRequirements(self):
        import json
        import urllib.request
        from urllib.error import URLError

        # first fetch the list of snap-deb replacements that will be needed
        # and store them for future reference, along with other data we'll
        # need in the process
        self._prepare_snap_replacement_data()
        # now perform direct API calls to the store, requesting size
        # information for each of the snaps needing installation
        self._view.updateStatus(_("Calculating snap size requirements"))
        for snap, snap_object in self._snap_list.items():
            if snap_object['command'] != 'install':
                continue
            action = {
                "instance-key": "upgrade-size-check",
                "action": "download",
                "snap-id": snap_object['snap-id'],
                "channel": snap_object['channel'],
            }
            data = {
                "context": [],
                "actions": [action],
            }
            req = urllib.request.Request(
                url='https://api.snapcraft.io/v2/snaps/refresh',
                data=bytes(json.dumps(data), encoding='utf-8'))
            req.add_header('Snap-Device-Series', '16')
            req.add_header('Content-type', 'application/json')
            req.add_header('Snap-Device-Architecture', self.arch)
            try:
                response = urllib.request.urlopen(req).read()
                info = json.loads(response)
                size = int(info['results'][0]['snap']['download']['size'])
            except (KeyError, URLError, ValueError):
                logging.debug("Failed fetching size of snap %s" % snap)
                continue
            self.extra_snap_space += size

    def _replaceDebsAndSnaps(self):
        """ install a snap and mark its corresponding package for removal """
        self._view.updateStatus(_("Processing snap replacements"))
        # _snap_list should be populated by the earlier
        # _calculateSnapSizeRequirements call.
        for snap, snap_object in self._snap_list.items():
            command = snap_object['command']
            if command == 'refresh':
                self._view.updateStatus(_("refreshing snap %s" % snap))
                popenargs = ["snap", command,
                             "--channel", snap_object['channel'], snap]
            elif command == 'remove':
                self._view.updateStatus(_("removing snap %s" % snap))
                popenargs = ["snap", command, snap]
            else:
                self._view.updateStatus(_("installing snap %s" % snap))
                popenargs = ["snap", command,
                             "--channel", snap_object['channel'], snap]
            try:
                self._view.processEvents()
                proc = subprocess.run(
                    popenargs,
                    stdout=subprocess.PIPE,
                    check=True)
                self._view.processEvents()
            except subprocess.CalledProcessError:
                logging.debug("%s of snap %s failed" % (command, snap))
                continue
            if proc.returncode == 0:
                logging.debug("%s of snap %s succeeded" % (command, snap))
            if command == 'install' and snap_object['deb']:
                self.controller.forced_obsoletes.append(snap_object['deb'])

    def _checkPae(self):
        " check PAE in /proc/cpuinfo "
        # upgrade from Precise will fail if PAE is not in cpu flags
        logging.debug("_checkPae")
        pae = 0
        with open('/proc/cpuinfo') as f:
            cpuinfo = f.read()
        if re.search("^flags\s+:.* pae ", cpuinfo, re.MULTILINE):
            pae = 1
        if not pae:
            logging.error("no pae in /proc/cpuinfo")
            summary = _("PAE not enabled")
            msg = _("Your system uses a CPU that does not have PAE enabled. "
                    "Ubuntu only supports non-PAE systems up to Ubuntu "
                    "12.04. To upgrade to a later version of Ubuntu, you "
                    "must enable PAE (if this is possible) see:\n"
                    "http://help.ubuntu.com/community/EnablingPAE")
            self._view.error(summary, msg)
            self.controller.abort()

    def _checkVideoDriver(self, name):
        " check if the given driver is in use in xorg.conf "
        XORG = "/etc/X11/xorg.conf"
        if not os.path.exists(XORG):
            return False
        with open(XORG) as f:
            lines = f.readlines()
        for line in lines:
            s = line.split("#")[0].strip()
            # check for fglrx driver entry
            if (s.lower().startswith("driver") and
                    s.endswith('"%s"' % name)):
                return True
        return False

    def _applyPatches(self, patchdir="./patches"):
        """
        helper that applies the patches in patchdir. the format is
        _path_to_file.md5sum and it will apply the diff to that file if the
        md5sum matches
        """
        if not os.path.exists(patchdir):
            logging.debug("no patchdir")
            return
        for f in os.listdir(patchdir):
            # skip, not a patch file, they all end with .$md5sum
            if "." not in f:
                logging.debug("skipping '%s' (no '.')" % f)
                continue
            logging.debug("check if patch '%s' needs to be applied" % f)
            (encoded_path, md5sum, result_md5sum) = f.rsplit(".", 2)
            # FIXME: this is not clever and needs quoting support for
            #        filenames with "_" in the name
            path = encoded_path.replace("_", "/")
            logging.debug("target for '%s' is '%s' -> '%s'" % (
                f, encoded_path, path))
            # target does not exist
            if not os.path.exists(path):
                logging.debug("target '%s' does not exist" % path)
                continue
            # check the input md5sum, this is not strictly needed as patch()
            # will verify the result md5sum and discard the result if that
            # does not match but this will remove a misleading error in the
            # logs
            md5 = hashlib.md5()
            with open(path, "rb") as fd:
                md5.update(fd.read())
            if md5.hexdigest() == result_md5sum:
                logging.debug("already at target hash, skipping '%s'" % path)
                continue
            elif md5.hexdigest() != md5sum:
                logging.warning("unexpected target md5sum, skipping: '%s'"
                                % path)
                continue
            # patchable, do it
            from .DistUpgradePatcher import patch
            try:
                patch(path, os.path.join(patchdir, f), result_md5sum)
                logging.info("applied '%s' successfully" % f)
            except Exception:
                logging.exception("ed failed for '%s'" % f)

    def _supportInModaliases(self, pkgname, lspci=None):
        """
        Check if pkgname will work on this hardware

        This helper will check with the modaliasesdir if the given
        pkg will work on this hardware (or the hardware given
        via the lspci argument)
        """
        # get lspci info (if needed)
        if not lspci:
            lspci = self._get_pci_ids()
        # get pkg
        if (pkgname not in self.controller.cache or
                not self.controller.cache[pkgname].candidate):
            logging.warning("can not find '%s' in cache")
            return False
        pkg = self.controller.cache[pkgname]
        for (module, pciid_list) in \
                self._parse_modaliases_from_pkg_header(pkg.candidate.record):
            for pciid in pciid_list:
                m = re.match("pci:v0000(.+)d0000(.+)sv.*", pciid)
                if m:
                    matchid = "%s:%s" % (m.group(1), m.group(2))
                    if matchid.lower() in lspci:
                        logging.debug("found system pciid '%s' in modaliases"
                                      % matchid)
                        return True
        logging.debug("checking for %s support in modaliases but none found"
                      % pkgname)
        return False

    def _parse_modaliases_from_pkg_header(self, pkgrecord):
        """ return a list of (module1, (pciid, ...), ...)"""
        if "Modaliases" not in pkgrecord:
            return []
        # split the string
        modules = []
        for m in pkgrecord["Modaliases"].split(")"):
            m = m.strip(", ")
            if not m:
                continue
            (module, pciids) = m.split("(")
            modules.append((module, [x.strip() for x in pciids.split(",")]))
        return modules

    def _add_extras_repository(self):
        logging.debug("_add_extras_repository")
        cache = self.controller.cache
        if "ubuntu-extras-keyring" not in cache:
            logging.debug("no ubuntu-extras-keyring, no need to add repo")
            return
        if not (cache["ubuntu-extras-keyring"].marked_install or
                cache["ubuntu-extras-keyring"].installed):
            logging.debug("ubuntu-extras-keyring not installed/marked_install")
            return
        try:
            import aptsources.sourceslist
            sources = aptsources.sourceslist.SourcesList()
            for entry in sources:
                if "extras.ubuntu.com" in entry.uri:
                    logging.debug("found extras.ubuntu.com, no need to add it")
                    break
            else:
                logging.info("no extras.ubuntu.com, adding it to sources.list")
                sources.add("deb", "http://extras.ubuntu.com/ubuntu",
                            self.controller.toDist, ["main"],
                            "Third party developers repository")
                sources.save()
        except Exception:
            logging.exception("error adding extras.ubuntu.com")

    def _gutenprint_fixup(self):
        """ foomatic-db-gutenprint get removed during the upgrade,
            replace it with the compressed ijsgutenprint-ppds
            (context is foomatic-db vs foomatic-db-compressed-ppds)
        """
        try:
            cache = self.controller.cache
            if ("foomatic-db-gutenprint" in cache and
                    cache["foomatic-db-gutenprint"].marked_delete and
                    "ijsgutenprint-ppds" in cache):
                logging.info("installing ijsgutenprint-ppds")
                cache.mark_install(
                    "ijsgutenprint-ppds",
                    "foomatic-db-gutenprint -> ijsgutenprint-ppds rule")
        except Exception:
            logging.exception("_gutenprint_fixup failed")

    def _enable_multiarch(self, foreign_arch="i386"):
        """ enable multiarch via /etc/dpkg/dpkg.cfg.d/multiarch """
        cfg = "/etc/dpkg/dpkg.cfg.d/multiarch"
        if not os.path.exists(cfg):
            try:
                os.makedirs("/etc/dpkg/dpkg.cfg.d/")
            except OSError:
                pass
            with open(cfg, "w") as f:
                f.write("foreign-architecture %s\n" % foreign_arch)

    def _is_greater_than(self, term1, term2):
        """ copied from ubuntu-drivers common """
        # We don't want to take into account
        # the flavour
        pattern = re.compile('(.+)-([0-9]+)-(.+)')
        match1 = pattern.match(term1)
        match2 = pattern.match(term2)
        if match1 and match2:
            term1 = '%s-%s' % (match1.group(1),
                               match1.group(2))
            term2 = '%s-%s' % (match2.group(1),
                               match2.group(2))

        logging.debug('Comparing %s with %s' % (term1, term2))
        return apt.apt_pkg.version_compare(term1, term2) > 0

    def _get_linux_metapackage(self, cache, headers):
        """ Get the linux headers or linux metapackage
            copied from ubuntu-drivers-common
        """
        suffix = headers and '-headers' or ''
        pattern = re.compile('linux-image-(.+)-([0-9]+)-(.+)')
        source_pattern = re.compile('linux-(.+)')

        metapackage = ''
        version = ''
        for pkg in cache:
            if ('linux-image' in pkg.name and 'extra' not in pkg.name and
                    (pkg.is_installed or pkg.marked_install)):
                match = pattern.match(pkg.name)
                # Here we filter out packages such as
                # linux-generic-lts-quantal
                if match:
                    source = pkg.candidate.record['Source']
                    current_version = '%s-%s' % (match.group(1),
                                                 match.group(2))
                    # See if the current version is greater than
                    # the greatest that we've found so far
                    if self._is_greater_than(current_version,
                                             version):
                        version = current_version
                        match_source = source_pattern.match(source)
                        # Set the linux-headers metapackage
                        if '-lts-' in source and match_source:
                            # This is the case of packages such as
                            # linux-image-3.5.0-18-generic which
                            # comes from linux-lts-quantal.
                            # Therefore the linux-headers-generic
                            # metapackage would be wrong here and
                            # we should use
                            # linux-headers-generic-lts-quantal
                            # instead
                            metapackage = 'linux%s-%s-%s' % (
                                           suffix,
                                           match.group(3),
                                           match_source.group(1))
                        else:
                            # The scheme linux-headers-$flavour works
                            # well here
                            metapackage = 'linux%s-%s' % (
                                           suffix,
                                           match.group(3))
        return metapackage

    def _install_linux_metapackage(self):
        """ Ensure the linux metapackage is installed for the newest_kernel
            installed. (LP: #1509305)
        """
        cache = self.controller.cache
        linux_metapackage = self._get_linux_metapackage(cache, False)
        # Seen on errors.u.c with linux-rpi2 metapackage
        # https://errors.ubuntu.com/problem/994bf05fae85fbcd44f721495db6518f2d5a126d
        if linux_metapackage not in cache:
            logging.info("linux metapackage (%s) not available" %
                         linux_metapackage)
            return
        # install the package if it isn't installed
        if not cache[linux_metapackage].is_installed:
            logging.info("installing linux metapackage: %s" %
                         linux_metapackage)
            reason = "linux metapackage may have been accidentally uninstalled"
            cache.mark_install(linux_metapackage, reason)

    def _install_python_is_python2(self):
        """
        Ensure python is removed, before it can produce a conflict with any
        other package and the python-is-python2 package is installed instead,
        if python-minimal was installed.
        """
        # python-dbg must come first for reasons unknown
        replacements = (('python-dbg', 'python2-dbg'),
                        ('python-doc', 'python2-doc'),
                        ('python-minimal', 'python-is-python2'),
                        ('python-dev', 'python-dev-is-python2'),
                        ('libpython-dev', None),
                        ('libpython-stdlib', None),
                        ('libpython-dbg', None))
        cache = self.controller.cache

        # We run with auto_inst=False first to mark our explicit choices so it
        # can guide the code with auto_inst=True when it makes decisions
        for auto_inst in False, True:
            for old, new in replacements:
                logging.info("checking for %s (auto_inst=%s)" %
                             (old, auto_inst))
                if old in cache and cache[old].is_installed:
                    if new:
                        logging.info("installing %s because %s was installed" %
                                     (new, old))
                        reason = "%s was installed on the system" % old
                        if not cache.mark_install(new, reason, auto_fix=False,
                                                  auto_inst=auto_inst):
                            logging.info("failed to install %s" % new)
                    logging.info("removing %s because %s is being installed" %
                                 (old, new))
                    reason = "%s is being installed on the system" % new
                    if not cache.mark_remove(old, reason, auto_fix=False):
                        logging.info("failed to remove %s", old)

        solver = apt.cache.ProblemResolver(cache)

        for old, new in replacements:
            if old in cache and cache[old].is_installed:
                if new:
                    if new not in cache:
                        old_inst = [old for old, new in replacements if old
                                    in cache and cache[old].is_installed]
                        summary = _("universe component not enabled")
                        msg = _("You have the package %s installed which "
                                "is a python2 package. python2 has been "
                                "deprecated in Ubuntu 20.04 LTS and is now "
                                "available from the universe component of "
                                "the Ubuntu archive. To ensure any existing "
                                "third party code you have installed "
                                "continues to work the release upgrade "
                                "process would install %s for you. However, "
                                "the universe component of the archive is not "
                                "enabled on this system. For the upgrade "
                                "process to proceed you should either enable "
                                "the universe component in "
                                "/etc/apt/sources.list or remove %s"
                                % (old, new, ', '.join(old_inst))
                                )
                        logging.info(summary)
                        # necessary to make the error text available again on
                        # stdout for the text frontend
                        cache._stopAptResolverLog()
                        self._view.error(summary, msg)
                        self.controller.abort()
                    else:
                        solver.clear(cache[new])
                        solver.protect(cache[new])
                solver.clear(cache[old])
                solver.remove(cache[old])

        solver.resolve()

    def ensure_recommends_are_installed_on_desktops(self):
        """ ensure that on a desktop install recommends are installed
            (LP: #759262)
        """
        if not self.controller.serverMode:
            if not apt.apt_pkg.config.find_b("Apt::Install-Recommends"):
                msg = "Apt::Install-Recommends was disabled,"
                msg += " enabling it just for the upgrade"
                logging.warning(msg)
                apt.apt_pkg.config.set("Apt::Install-Recommends", "1")

    def _is_deb2snap_metapkg_installed(self, deb2snap_entry):
        """ Helper function that checks if the given deb2snap entry
            has at least one metapkg which is installed on the system.
        """
        metapkg_list = deb2snap_entry.get("metapkg", None)
        if not isinstance(metapkg_list, list):
            metapkg_list = [metapkg_list]

        for metapkg in metapkg_list:
            if metapkg not in self.controller.cache:
                continue
            if metapkg and \
                    self.controller.cache[metapkg].is_installed is False:
                continue

            return True

        return False

    def _prepare_snap_replacement_data(self):
        """ Helper function fetching all required info for the deb-to-snap
            migration: version strings for upgrade (from and to) and the list
            of snaps (with actions).
        """
        import json
        self._snap_list = {}
        from_channel = "stable/ubuntu-%s" % self._from_version
        to_channel = "stable/ubuntu-%s" % self._to_version
        seeded_snaps = {}
        unseeded_snaps = {}

        try:
            current_path = os.path.dirname(os.path.abspath(__file__))
            d2s_file = open(current_path + '/deb2snap.json', 'r')
            d2s = json.load(d2s_file)
            d2s_file.close()

            for snap in d2s["seeded"]:
                seed = d2s["seeded"][snap]
                if not self._is_deb2snap_metapkg_installed(seed):
                    continue
                deb = seed.get("deb", None)
                from_chan = seed.get("from_channel", from_channel)
                to_chan = seed.get("to_channel", to_channel)
                seeded_snaps[snap] = (deb, from_chan, to_chan)

            for snap in d2s["unseeded"]:
                unseed = d2s["unseeded"][snap]
                deb = unseed.get("deb", None)
                if not self._is_deb2snap_metapkg_installed(unseed):
                    continue
                from_chan = unseed.get("from_channel", from_channel)
                unseeded_snaps[snap] = (deb, from_chan)
        except Exception as e:
            logging.warning("error reading deb2snap.json file (%s)" % e)

        snap_list = ''
        # list the installed snaps and add them to seeded ones
        snap_list = subprocess.Popen(["snap", "list"],
                                     universal_newlines=True,
                                     stdout=subprocess.PIPE).communicate()
        if snap_list:
            # first line of output is a header and the last line is empty
            snaps_installed = [line.split()[0]
                               for line in snap_list[0].split('\n')[1:-1]]

            for snap in snaps_installed:
                if snap in seeded_snaps or snap in unseeded_snaps:
                    continue
                else:
                    seeded_snaps[snap] = (None, from_channel, to_channel)

        self._view.updateStatus(_("Checking for installed snaps"))
        for snap, (deb, from_channel, to_channel) in seeded_snaps.items():
            snap_object = {}
            # check to see if the snap is already installed
            snap_info = subprocess.Popen(["snap", "info", snap],
                                         universal_newlines=True,
                                         stdout=subprocess.PIPE).communicate()
            self._view.processEvents()
            if re.search("^installed: ", snap_info[0], re.MULTILINE):
                logging.debug("Snap %s is installed" % snap)
                # its not tracking the release channel so don't refresh
                if not re.search(r"^tracking:.*%s" % from_channel,
                                 snap_info[0], re.MULTILINE):
                    logging.debug("Snap %s is not tracking the release channel"
                                  % snap)
                    continue
                snap_object['command'] = 'refresh'
            else:
                # Do not replace packages not installed
                cache = self.controller.cache
                if (deb and (deb not in cache or not cache[deb].is_installed)):
                    logging.debug("Deb package %s is not installed. Skipping "
                                  "snap package %s installation" % (deb, snap))
                    continue

                match = re.search(r"snap-id:\s*(\w*)", snap_info[0])
                if not match:
                    logging.debug("Could not parse snap-id for the %s snap"
                                  % snap)
                    continue
                snap_object['command'] = 'install'
                snap_object['deb'] = deb
                snap_object['snap-id'] = match[1]
            snap_object['channel'] = to_channel
            self._snap_list[snap] = snap_object
        for snap, (deb, from_channel) in unseeded_snaps.items():
            snap_object = {}
            # check to see if the snap is already installed
            snap_info = subprocess.Popen(["snap", "info", snap],
                                         universal_newlines=True,
                                         stdout=subprocess.PIPE).communicate()
            self._view.processEvents()
            if re.search("^installed: ", snap_info[0], re.MULTILINE):
                logging.debug("Snap %s is installed" % snap)
                # its not tracking the release channel so don't remove
                if not re.search(r"^tracking:.*%s" % from_channel,
                                 snap_info[0], re.MULTILINE):
                    logging.debug("Snap %s is not tracking the release channel"
                                  % snap)
                    continue

                snap_object['command'] = 'remove'

                # check if this snap is being used by any other snaps
                conns = subprocess.Popen(["snap", "connections", snap],
                                         universal_newlines=True,
                                         stdout=subprocess.PIPE).communicate()
                self._view.processEvents()

                for conn in conns[0].split('\n'):
                    conn_cols = conn.split()
                    if len(conn_cols) != 4:
                        continue
                    plug = conn_cols[1]
                    slot = conn_cols[2]

                    if slot.startswith(snap + ':'):
                        plug_snap = plug.split(':')[0]
                        if plug_snap != '-' and \
                           plug_snap not in unseeded_snaps:
                            logging.debug("Snap %s is being used by %s. "
                                          "Switching it to stable track"
                                          % (snap, plug_snap))
                            snap_object['command'] = 'refresh'
                            snap_object['channel'] = 'stable'
                            break

                self._snap_list[snap] = snap_object
        return self._snap_list

    def _replace_fkms_overlay(self, boot_dir='/boot/firmware'):
        failure_action = (
            "You may need to replace the vc4-fkms-v3d overlay with "
            "vc4-kms-v3d in config.txt on your boot partition")

        try:
            boot_config_filename = os.path.join(boot_dir, 'config.txt')
            with open(boot_config_filename, 'r', encoding='utf-8') as f:
                boot_config = f.read()
        except FileNotFoundError:
            logging.error("failed to open boot configuration in %s; %s",
                          boot_config_filename, failure_action)
            return

        new_config = ''.join(
            # startswith and replace used to cope with (and preserve) any
            # trailing d-t parameters, and any use of the -pi4 suffix
            '# changed by do-release-upgrade (LP: #1923673)\n#' + line +
            line.replace('dtoverlay=vc4-fkms-v3d', 'dtoverlay=vc4-kms-v3d')
            if line.startswith('dtoverlay=vc4-fkms-v3d') else
            # camera firmware disabled due to incompatibility with "full" kms
            # overlay; without the camera firmware active it's also better to
            # disable gpu_mem leaving the default (64MB) to allow as much as
            # possible for the KMS driver
            '# disabled by do-release-upgrade (LP: #1923673)\n#' + line
            if line.startswith('gpu_mem=') or line.rstrip() == 'start_x=1' else
            line
            for line in boot_config.splitlines(keepends=True)
        )

        if new_config == boot_config:
            logging.warning("no fkms overlay or camera firmware line found "
                            "in %s", boot_config_filename)
            return

        try:
            boot_backup_filename = os.path.join(
                boot_dir, 'config.txt.distUpgrade')
            with open(boot_backup_filename, 'w', encoding='utf-8') as f:
                f.write(boot_config)
        except IOError as exc:
            logging.error("unable to write boot config backup to %s: %s; %s",
                          boot_backup_filename, exc, failure_action)
            return
        try:
            with open(boot_config_filename, 'w', encoding='utf-8') as f:
                f.write(new_config)
        except IOError as exc:
            logging.error("unable to write new boot config to %s: %s; %s",
                          boot_config_filename, exc, failure_action)

    def _remove_uboot_on_rpi(self, boot_dir='/boot/firmware'):
        kernel_line = 'kernel=vmlinuz'
        initramfs_line = 'initramfs initrd.img followkernel' 
        failure_action = (
            "You may need to replace u_boot_* with vmlinuz, and add "
            "{initramfs_line!r} to config.txt on your boot "
            "partition; see LP: #1936401 for further details")
        failure_action = failure_action.format(initramfs_line=initramfs_line)
        change_prefix = '# commented by do-release-upgrade (LP: #1936401)'
        added_prefix = '# added by do-release-upgrade (LP: #1936401)'
        merge_prefix = '# merged from {} by do-release-upgrade (LP: #1936401)'

        try:
            boot_config_filename = os.path.join(boot_dir, 'config.txt')
            with open(boot_config_filename, 'r', encoding='utf-8') as f:
                boot_config = f.read()
        except FileNotFoundError:
            logging.error("failed to open boot configuration in %s; %s",
                          boot_config_filename, failure_action)
            return

        def replace_uboot(lines):
            result = []
            removed_uboot = added_kernel = False
            for line in lines:
                if line == '[all]':
                    # Add the vmlinuz kernel and initrd.img to the first
                    # encountered [all] section, just in case the user has any
                    # custom kernel overrides later in the sequence
                    result.append(line)
                    if not added_kernel:
                        result.append(added_prefix)
                        result.append(kernel_line)
                        result.append(initramfs_line)
                        added_kernel = True
                elif line.startswith('device_tree_address='):
                    # Disable any device_tree_address= line (leave the boot
                    # firmware to place this rather than risk trampling over it
                    # with kernel/initrd)
                    result.append(change_prefix)
                    result.append('#' + line)
                elif line.startswith('kernel=uboot_rpi_'):
                    # Disable all kernel=uboot_rpi_* lines found in the
                    # configuration
                    removed_uboot = True
                    result.append(change_prefix)
                    result.append('#' + line)
                else:
                    result.append(line)
            # We don't *want* to touch the config unless we absolutely have to,
            # and the user may have already performed this conversion (e.g. to
            # take advantage of USB MSD boot), or otherwise customized their
            # boot configuration. Hence, if we didn't find (and remove) any
            # u-boot entries, assume the kernel/initrd config was already fine
            # and return the verbatim config
            if removed_uboot:
                if not added_kernel:
                    result.append(added_prefix)
                    result.append('[all]')
                    result.append(kernel_line)
                    result.append(initramfs_line)
                return result
            else:
                return lines

        def merge_includes(lines):
            result = []
            skip_comments = True
            found_includes = False
            for line in lines:
                # Skip the initial comment block warning that config.txt is not
                # to be edited (the usercfg.txt and syscfg.txt files were
                # merged in the groovy release, but not for upgraders)
                if line.startswith('#') and skip_comments:
                    continue
                skip_comments = False
                if line in ('include syscfg.txt', 'include usercfg.txt'):
                    # Merge the usercfg.txt and syscfg.txt configuration files
                    # into config.txt, skipping the initial comments. Note that
                    # we don't bother with other includes the user has added
                    # themselves (as they presumably want to keep those)
                    found_includes = True
                    included_filename = line.split(maxsplit=1)[1]
                    result.append(merge_prefix.format(included_filename))
                    included_filename = os.path.join(boot_dir,
                                                     included_filename)
                    skip_comments = True
                    with open(included_filename, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.startswith('#') and skip_comments:
                                continue
                            skip_comments = False
                            result.append(line.rstrip())
                    target_filename = included_filename + '.distUpgrade'
                    try:
                        os.rename(included_filename, target_filename)
                    except IOError as exc:
                        logging.error("failed to move included configuration "
                                      "from %s to %s; %s", included_filename,
                                      target_filename, exc)
                else:
                    result.append(line)
            # Again, if we found no includes, return the original verbatim
            # (i.e. with initial comments intact)
            if found_includes:
                return result
            else:
                return lines

        lines = [line.rstrip() for line in boot_config.splitlines()]
        lines = replace_uboot(merge_includes(lines))
        new_config = ''.join(line + '\n' for line in lines)

        if new_config == boot_config:
            logging.warning("no u-boot removal performed in %s",
                            boot_config_filename)
            return

        try:
            boot_backup_filename = boot_config_filename + '.distUpgrade'
            with open(boot_backup_filename, 'w', encoding='utf-8') as f:
                f.write(boot_config)
        except IOError as exc:
            logging.error("unable to write boot config backup to %s: %s; %s",
                          boot_backup_filename, exc, failure_action)
            return
        try:
            with open(boot_config_filename, 'w', encoding='utf-8') as f:
                f.write(new_config)
        except IOError as exc:
            logging.error("unable to write new boot config to %s: %s; %s",
                          boot_config_filename, exc, failure_action)

    def _remove_netplan_match_rpi(self, netplan_dir='/etc/netplan'):
        failure_action = (
            "You may need to manually edit your netplan config "
            "and remove the line \"driver: bcmgenet smsc95xx lan78xx\". "
            "See LP: #1970761 for further details")

        try:
            import yaml
        except ImportError:
            logging.error("failed to import yaml library. %s", failure_action)
            return

        for netplan_config_file in glob.glob("%s/*.yaml" % netplan_dir):
            try:
                netplan_config_filename = os.path.join(netplan_dir,
                                                       netplan_config_file)
                with open(netplan_config_filename, 'r', encoding='utf-8') as f:
                    orig_content = f.read()
                    netplan_yaml = yaml.load(orig_content,
                                             Loader=yaml.SafeLoader)

            except FileNotFoundError:
                logging.error("failed to open netplan configuration in %s; %s",
                              netplan_config_filename, failure_action)
                return

            file_modified = False
            try:
                for eth in netplan_yaml["network"]["ethernets"].values():
                    if eth["match"]["driver"] == "bcmgenet smsc95xx lan78xx":
                        file_modified = True
                        del eth["match"]
                        if "set-name" in eth:
                            del eth["set-name"]
            except KeyError:
                continue

            if not file_modified:
                continue

            try:
                netplan_backup_filename = (netplan_config_filename +
                                           '.distUpgrade')
                with open(netplan_backup_filename, 'w', encoding='utf-8') as f:
                    f.write(orig_content)
            except IOError as exc:
                logging.error("unable to write netplan config backup to "
                              "%s: %s; %s",
                              netplan_backup_filename, exc, failure_action)
                return
            try:
                with open(netplan_config_filename, 'w', encoding='utf-8') as f:
                    yaml.dump(netplan_yaml, f, default_flow_style=False)
            except IOError as exc:
                logging.error("unable to write new netplan config to "
                              "%s: %s; %s",
                              netplan_config_filename, exc, failure_action)
                return

    def _fix_missing_nvidia_metapackage(self):
        # LP: #1955047
        # Desktop installs for 20.04.3 on systems with nvidia graphics don't
        # have the driver metapackage installed
        logging.debug("running "
                      "Quirks._test_and_fix_missing_nvidia_metapackage")
        cache = self.controller.cache
        if 'ubuntu-drivers-common' not in cache:
            logging.error("ubuntu-drivers-common not be available")
            return
        elif not cache['ubuntu-drivers-common'].is_installed:
            logging.error("ubuntu-drivers-common not installed")
            return
        try:
            from NvidiaDetector.nvidiadetector import NvidiaDetection
        except (ImportError) as e:
            logging.error("NvidiaDetection can not be imported %s" % e)
            return
        nv = NvidiaDetection()
        versions = nv.drivers.keys()
        # Early exit if there's a driver metapackage installed
        for version in versions:
            driver = 'nvidia-driver-{}'.format(version)
            if driver in cache and cache[driver].is_installed:
                logging.debug("package {} detected, exit.".format(driver))
                return
        version_to_fix = None
        # If we find an autoremovable libnvidia-gl package, this probably
        # means the user hit LP: #1955047
        for version in versions:
            nvidia_gl = 'libnvidia-gl-{}'.format(version)
            if nvidia_gl in cache and cache[nvidia_gl].is_installed \
               and cache[nvidia_gl].is_auto_removable:
                version_to_fix = version
                logging.debug("Found autoremovable package {}, assuming "
                              "we're missing nvidia-driver-{}"
                              .format(nvidia_gl, version))
                break
        if version_to_fix is None:
            logging.debug("No autoremovable libnvidia-gl found, exiting.")
            return
        missing_metapackage = "nvidia-driver-{}".format(version_to_fix)
        if missing_metapackage not in cache:
            logging.error("Package {} not available in the APT cache!"
                          .format(missing_metapackage))
            summary = _("NVIDIA driver metapackage unavailable")
            msg = _("Your system has the package libnvidia-gl-%s installed "
                    "but the corresponding metapackage nvidia-driver-%s is "
                    "not installed and is not available to be installed. "
                    "The upgrade process was not able to automatically fix "
                    "this issue and consequently the upgrade will now exit." %
                    (version_to_fix, version_to_fix))
            self._view.error(summary, msg)
            self.controller.abort()
            return
        logging.debug("Installing missing nvidia driver metapackage {}"
                      .format(missing_metapackage))
        cache[missing_metapackage].mark_install()
        cache.commit(None, None)
