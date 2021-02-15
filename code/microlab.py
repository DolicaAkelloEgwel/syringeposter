import logging
import logging.config
import sys
import threading
from time import sleep
from typing import List

from hamiltonmicrolab.commands.command import Command
from hamiltonmicrolab.commands.helpers import FIRST_ADDRESS
from hamiltonmicrolab.commands.instrument_information_request import (
    Y_INFO_RESPONSE,
    InstrumentInformationRequest,
)
from hamiltonmicrolab.commands.instrument_status_request import (
    InstrumentBusyStatus,
    InstrumentErrorRequest,
    InstrumentErrorStatus,
    InstrumentStatusRequest,
    TimerStatus,
)
from hamiltonmicrolab.commands.side import Side
from hamiltonmicrolab.comms import Comms
from hamiltonmicrolab.side_parameters_group import SideParametersGroup

INSTRUMENT_DONE = "F"


class Microlab:

    """A class for controlling a Hamilton Microlab syringe pump"""

    def __init__(self, ip: str, port: int):
        """
        Args:
            ip (str): IP address to connect to
            port (int): Port ...
        """
        self._log = logging.getLogger(self.__class__.__name__)
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s.%(msecs)03d::%(levelname)s::%(module)s::%(message)s",
            datefmt="%H:%M:%S",
        )

        self._ip = ip
        self._port = port

        self._initialised = False
        self._stop_requested = False

        self._comms = Comms(self._ip, self._port)
        self._comms.connect()
        self._configure_parameters()

        self._threads: List[threading.Thread] = []

    def disconnect(self):
        self._comms.disconnect()

    def _configure_parameters(self):

        self.right = SideParametersGroup(Side.RIGHT, self._comms)
        self.left = SideParametersGroup(Side.LEFT, self._comms)

        self.instrument_done = InstrumentInformationRequest(
            self._comms,
            INSTRUMENT_DONE,
            "Instrument is idle and command buffer is empty",
            "Instrument is idle and command buffer is not empty",
        )
        self.syringe_error = InstrumentInformationRequest(
            self._comms,
            "Z",
            "Syringe overload or initialisation error",
            "No syringe error",
        )
        self.valve_error = InstrumentInformationRequest(
            self._comms,
            "G",
            "Valve overload or initialisation error",
            "No valve error",
        )
        self.instrument_configuration = InstrumentInformationRequest(
            self._comms, "H", "Single syringe instrument", "Dual syringe instrument",
        )
        self.hand_probe_foot_switch_status = InstrumentInformationRequest(
            self._comms, "Q", "Switch is pressed", "Switch is not pressed"
        )

        self.timer_busy_status = TimerStatus(self._comms)
        self.instrument_error_status = InstrumentErrorStatus(self._comms)
        self.instrument_busy_status = InstrumentBusyStatus(self._comms)
        self.instrument_status_request = InstrumentStatusRequest(self._comms)
        self.instrument_error_request = InstrumentErrorRequest(self._comms)

    def auto_address(self) -> bool:
        """Assigns automatic addresses to the instruments.

        Returns:
            bool: True if auto-address was successful, False otherwise.
        """
        response = self._comms.send_auto_address_message()
        # TODO: Only seem to get 1b after power cycle, then 1a?
        if response in ["1b", "1a"]:
            self._log.debug("Auto-address sequence successful")
            return True

        self._log.error("Auto-address sequence failed")
        return False

    def initialise(self):
        """Initialise the device"""
        success, _ = self._comms.send_receive("aXR")

        if not success:
            self._log.error("Initialise failed")
            return

        self._log.debug("Initialise successful")
        self._initialised = True

    def get_firmware_version(self) -> str:
        """Read the firmware version.

        Returns:
            Optional[str]: The firmware version if successful, None otherwise.
        """
        success, firmware_version = self._comms.send_receive("aU")
        if success:
            self._log.debug(f"Firmware version: {firmware_version}")
            return firmware_version  # type: ignore

        self._log.error("Failed to get firmware version")
        return ""

    def send_command(self, command: Command, address: str = FIRST_ADDRESS):
        """Sends a command to the syringe.

        Args:
            command (Command): A command.
            address (str, optional): The target address for the command. Defaults to
                FIRST_ADDRESS.
        """
        self._comms.send_receive(address + command.string)

    def halt_execution(self, address: str = FIRST_ADDRESS):
        """Sends the halt execution command to a given instrument address.

        Args:
            address (str, optional): The address to send the halt execution instruction
                to. Defaults to FIRST_ADDRESS.
        """
        success, _ = self._comms.send_receive(address + "K")
        if success:
            self._log.debug("Successfully halted execution")
            return
        self._log.error("Failed to halt execution")

    def resume_execution(self, address: str = FIRST_ADDRESS):
        """Sends the resume execution command to a given instrument address.

        Args:
            address (str, optional): The address to send the resume execution
                instruction to. Defaults to FIRST_ADDRESS.
        """
        success, _ = self._comms.send_receive(address + "$")
        if success:
            self._log.debug("Successfully resumed execution")
            return
        self._log.error("Failed to resume execution")

    def clear_all_buffered_commands(self, address: str = FIRST_ADDRESS):
        """Clears all buffered commands.

        Args:
            address (str, optional): The address to send the clear all buffered commands
                instruction to. Defaults to FIRST_ADDRESS.
        """
        success, _ = self._comms.send_receive(address + "V")
        if success:
            self._log.debug("Successfully cleared buffered commands")
            return
        self._log.error("Failed to clear buffered commands")

    def _reset_cycle(self, address: str):
        """Calls the halt execution command and resets the `_stop_requested` flag so
        the cycle commands method can be used again.
        """
        self.halt_execution(address)
        self._stop_requested = False
        self._threads.clear()

    def _cycle_commands(
        self, commands: List[Command], address: str,
    ):
        """Cycles through lists of commands. Stops when the `stop_cycle` method is
        called.

        Args:
            command_lists (List[Command]): The list of commands.
            address (str): The target address for the commands.
        """
        # Avoid getting lots of log messages every time `send_receive` is called
        logging.getLogger(self._comms.__class__.__name__).setLevel(logging.ERROR)
        while not self._stop_requested:
            for command in commands:
                self.send_command(command, address)
                while (
                    self._comms.send_receive(address + INSTRUMENT_DONE)[1]
                    != Y_INFO_RESPONSE
                ):
                    if self._stop_requested:
                        self._reset_cycle(address)
                        return
                    sleep(0.1)
        self._reset_cycle(address)

    def cycle_commands(
        self, commands: List[Command], address: str = FIRST_ADDRESS,
    ):
        """Cycles through a list of commands in a dedicated thread.

        Args:
            commands (List[Command]): The list of commands.
            address (str, optional): The target address for the commands. Defaults to
                FIRST_ADDRESS.
        """
        if self._threads:
            self._log.error(
                "Attempted to start a command cycle when one is already running."
            )
            return
        self._threads.append(
            threading.Thread(target=self._cycle_commands, args=(commands, address))
        )
        self._threads[0].start()

    def stop_cycle(self, enable_logging=True):
        """Halts the execution of the cycling commands.

        Args:
            enable_logging (bool, optional): Determines if the previous logging level
                should be restored. Defaults to True.
        """
        if not self._threads:
            return
        if enable_logging:
            logging.getLogger(self._comms.__class__.__name__).setLevel(logging.DEBUG)
        self._stop_requested = True
        self._threads[0].join()

    def total_system_reset(self, address: str = FIRST_ADDRESS):
        """Sends the instruction to power the instrument off and back on then exits the
        program.

        Args:
            address (str, optional): The address of the instrument to reset. Defaults
                to FIRST_ADDRESS.
        """
        if self._comms.send_receive(f"{address}!")[0]:
            self._log.debug("Resetting instrument.")
            sys.exit()
        else:
            self._log.error(f"Total system reset for instrument {address} failed.")

