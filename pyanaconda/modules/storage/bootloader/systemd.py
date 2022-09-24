#
# Copyright (C) 2022 Arm
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Systemd-boot is dead simple it basically provides a second boot menu
# and injects the kernel parms into an efi stubbed kernel, which in turn
# loads its initrd. As such there aren't any filesystem or drivers to worry
# about as everything needed is provided by UEFI. Even the console remains
# on the UEFI framebuffer, or serial as selected by UEFI. Basically
# rather than trying to be another mini-os (like grub) and duplicate much of
# what uefi provides, it simply utilizes the uefi services.
#
# further, while we could keep stage1 (ESP) and stage2 (/boot) seperate it
# simplifies things just to merge them and place the kernel/initrd on the
# ESP. This requires a larger than normal ESP, but for now we assume that
# this linux installer is creating the partitions, so where the space
# is allocated doesn't matter.

import os
import re

#from blivet.devicelibs import raid

from pyanaconda.modules.storage.bootloader.base import BootLoader, BootLoaderError
from pyanaconda.core import util
from pyanaconda.core.configuration.anaconda import conf
from pyanaconda.core.i18n import _
from pyanaconda.core.path import open_with_perm
from pyanaconda.product import productName

from pyanaconda.anaconda_loggers import get_module_logger
log = get_module_logger(__name__)

__all__ = ["SYSTEMD"]

class SYSTEMD(BootLoader):
    """Systemd-boot.

    - configuration
        - password (insecure), password_pbkdf2
          http://www.gnu.org/software/grub/manual/grub.html#Invoking-grub_002dmkpasswd_002dpbkdf2
        - users per-entry specifies which users can access, otherwise entry is unrestricted
        - /boot/efi/loader/loader.conf
        - /boot/efi/loader/entries/image_specific_.conf
    """
    name = "SYSTEMD"
    # oddly systemd-boot files are part of the systemd-udev package
    # and in /usr/lib/systemd/boot/efi/systemd-boot[aa64].efi
    # and the systemd stubs are in /usr/lib/systemd/linuxaa64.efi.stub
    _config_file = "loader.conf"
    _config_dir = "efi/loader/"
    stage2_max_end = None

#    _device_map_file = "device.map"

    stage2_is_valid_stage1 = True
    stage2_bootable = True
    stage2_must_be_primary = False

    # requirements for boot devices
    stage2_device_types = ["partition"]

    def __init__(self):
        super().__init__()
        self.encrypted_password = ""

    #
    # configuration
    #

    @property
    def config_dir(self):
        """ Full path to configuration directory. """
        log.info("systemd.py: config_dir")
        return "/boot/" + self._config_dir

    @property
    def config_file(self):
        """ Full path to configuration file. """
        log.info("systemd.py: config_file")
        return "%s/%s" % (self.config_dir, self._config_file)

#    @property
#    def device_map_file(self):
#        """ Full path to device.map file. """
#        log.info("systemd.py: device_map_file")
#        return "%s/%s" % (self.config_dir, self._device_map_file)


    def write_config_images(self, config):
        log.info("systemd.py: write_config_images")
        return True

    # todo dump this, no stage2 needed
    @property
    def stage2_format_types(self):
        log.info("systemd.py: stage2_format_types")
        if productName.startswith("Red Hat "): # pylint: disable=no-member
            return ["xfs", "ext4", "ext3", "ext2"]
        else:
            return ["ext4", "ext3", "ext2", "btrfs", "xfs"]


    def write_device_map(self):
        """Write out a device map containing all supported devices."""
        log.info("systemd.py: write_device_map")
        map_path = os.path.normpath(conf.target.system_root + self.device_map_file)
        if os.access(map_path, os.R_OK):
            os.rename(map_path, map_path + ".anacbak")

        devices = self.disks
        if self.stage1_device not in devices:
            devices.append(self.stage1_device)

        for disk in self.stage2_device.disks:
            if disk not in devices:
                devices.append(disk)

        devices = [d for d in devices if d.is_disk]

        if len(devices) == 0:
            return

    # copy console update from grub2.py
    def write_config_console(self, config):
        log.info("systemd.py: write_config_console")
        if not self.console:
            return

        console_arg = "console=%s" % self.console
        if self.console_options:
            console_arg += ",%s" % self.console_options
        self.boot_args.add(console_arg)



    def write_config(self):
        log.info("systemd.py: write_config systemd start")
        # So at this point, all this is pretty much redundant
        self.write_config_console(None)

        # just rewrite the loader.conf
        #cfg_file = config_file(self)
        config_path = "%s%s" % (conf.target.system_root, "/boot/efi/loader/loader.conf")
        log.info("systemd.py: write_config systemd loader conf : %s ", config_path)

        # outside of resetting the default, this file should probably be moved to
        # stubby as well?
        config = open(config_path, "w")
        config.write("timeout 3\n")
        # create a default entry? No need right now..
        # config.write("default 4142287a09f64398a50ac387bf9e1fca-*\n")
        config.write("#console-mode keep\n")
        config.close()

        # do the bls command line here?
        # update /etc/kernel/cmdline
        # should look something like "root=UUID=45b931b7-592a-46dc-9c33-d38d5901ec29 ro  resume=/dev/sda3"
        config_path = "%s%s" % (conf.target.system_root, "/etc/kernel/cmdline")
        log.info("systemd.py: write_config systemd commandline : %s ", config_path)
        config = open(config_path, "w")
        args = " ".join(list(self.boot_args._arguments))
        log.info("systemd.py: systemd used boot args: %s ", args)
        # should run this through blkid to get UUID... but what is going on with the above args...
        args += " root=/dev/mapper/fedora_fedora-root"
        config.write(args)
        config.close()
        # rather than creating a mess in python lets just
        # write the options above, and run a script which will merge the
        # boot cmdline (after stripping inst. and BOOT_) with the anaconda settings
        rc = util.execWithRedirect(
            "/usr/sbin/updateloaderentries.sh",
            [" "],
            root=conf.target.system_root

        )
        if rc:
            raise BootLoaderError("failed to write boot loader configuration")
    #
    # installation
    #

# OK, so this whole thing is a bit hard to follow given its a bunch of
# tasks triggering, and the order isn't clear/etc
# so here is the task trigger order:

#INFO:anaconda.modules.common.task.task:Scan all devices
#INFO:anaconda.modules.common.task.task:Configure the partitioning
#INFO:anaconda.modules.common.task.task:Validate a storage model
#INFO:anaconda.modules.common.task.task:Create storage layout
#INFO:anaconda.modules.common.task.task:Mount filesystems
#INFO:anaconda.modules.common.task.task:Write the storage configuration
# should really update the kernel command line here.. that will fix the later mess
#   alternativly we can use the stubby package to set the commandline?
#INFO:anaconda.modules.common.task.task:Create rescue images
#INFO:anaconda.modules.common.task.task:Configure the bootloader
#   utils.py: configure_boot_loader()
#       should write /etc/sysconfig/kernel to select default kernel update
#       but fails because it has hardcoded kernel/boot paths

#INFO:anaconda.modules.common.task.task:Install the bootloader
#   base.py: prepare() <-- that should get all the boot args in place, but where do they go?
#    efi.py: efibase.write()
#     systemd.py: install()
#     systemd.py: write_config()

#INFO:anaconda.modules.common.task.task:Create the BLS entries
# doesn't need to do anything except for live payloads when it calls
#   create_bls_entries()
#INFO:anaconda.modules.common.task.task:Recreate the initrds
#INFO:anaconda.modules.common.task.task:Fix the bootloader on BTRFS
#INFO:anaconda.modules.common.task.task:Rerun zipl



    @property
    def install_targets(self):
        """ List of (stage1, stage2) tuples representing install targets. """
        log.info("systemd.py: install_targets")
        targets = []

        # make sure we have stage1 and stage2 installed with redundancy
        # so that boot can succeed even in the event of failure or removal
        # of some of the disks containing the member partitions of the
        # /boot array. If the stage1 is not a disk, it probably needs to
        # be a partition on a particular disk (biosboot, prepboot), so only
        # add the redundant targets if installing stage1 to a disk that is
        # a member of the stage2 array.

        # Look for both mdraid and btrfs raid
        stage2_raid = False

        targets.append((self.stage1_device, self.stage2_device))

        return targets

    def installbootmgr(self, args=None):
        log.info("systemd.py: install")
        if args is None:
            args = []

        log.info("systemd.py: install systemd boot install (root=%s)", conf.target.system_root)

        rc = util.execWithRedirect("bootctl", [ "install", "--esp-path=/boot/efi" ],
                                   root=conf.target.system_root,
                                   env_prune=['MALLOC_PERTURB_'])
        if rc:
            raise BootLoaderError("boot loader install failed")

    def write(self):
        """Write the bootloader configuration and install the bootloader."""
        log.info("systemd.py: write")
        try:
            self.write_device_map()
            self.stage2_device.format.sync(root=conf.target.physical_root)
            os.sync()
            log.info("systemd.py: write, install")
            self.install()
            os.sync()
            self.stage2_device.format.sync(root=conf.target.physical_root)
        finally:
            log.info("systemd.py: write, write_config")
            self.write_config()
            os.sync()
            self.stage2_device.format.sync(root=conf.target.physical_root)

    #
    # miscellaneous
    #

    def has_windows(self, devices):
        """ Potential boot devices containing non-linux operating systems. """
        # make sure we don't clobber error/warning lists
        errors = self.errors[:]
        warnings = self.warnings[:]
        ret = [d for d in devices if self.is_valid_stage2_device(d, linux=False, non_linux=True)]
        self.errors = errors
        self.warnings = warnings
        return bool(ret)

    # Add a warning about certain RAID situations to is_valid_stage2_device
    def is_valid_stage2_device(self, device, linux=True, non_linux=False):
        valid = super().is_valid_stage2_device(device, linux, non_linux)

        return valid

