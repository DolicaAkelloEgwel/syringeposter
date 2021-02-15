import logging
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import cothread
import numpy as np
from cothread.catools import caput
from softioc import alarm, builder
from softioc.pythonSoftIoc import RecordWrapper

from hamiltonmicrolab.commands.command import Command
from hamiltonmicrolab.commands.instrument_information_request import (
    AST_INFO_RESPONSE,
    N_INFO_RESPONSE,
    Y_INFO_RESPONSE,
)
from hamiltonmicrolab.commands.side import Side
from hamiltonmicrolab.commands.syringe_move import (
    MIN_SPEED,
    MIN_SYRINGE_MOVE,
    SyringeAbsoluteMove,
    SyringeDispense,
    SyringePickup,
    _syringe_speed_in_valid_range,
)
from hamiltonmicrolab.commands.valve_position import (
    ValveToDefaultInput,
    ValveToDefaultOutput,
)
from hamiltonmicrolab.microlab import Microlab
from hamiltonmicrolab.side_parameters_group import SideParametersGroup

SYRINGE_SIZES = [
    "10 uL",
    "25 uL",
    "50 uL",
    "100 uL",
    "250 uL",
    "500 uL",
    "1 mL",
    "2.5 mL",
    "5 mL",
    "10 mL",
    "25 mL",
    "50 mL",
]
SIZE_MAPPING = [(index, size) for size, index in enumerate(SYRINGE_SIZES)]
MAX_VOLUME_STEPS = 48000
INITIAL_MAX_VOLUME = 10.0
SYRINGE_VOL_LOPR = "SyringeVolume_RBV.LOPR"
VALVE_POSITIONS = ["Inlet", "Outlet"]


def _get_last_n_bits(byte: int, n: int) -> int:
    """Gets the last n bits from a byte.

    Args:
        byte (int): The byte returned from the information/status/error request.
        n (int): The last n bits to get from the byte.

    Returns:
        int: The last n bits of the given byte.
    """
    return byte & ((1 << n) - 1)


def _convert_steps_to_volume(current_steps: int, maximum_volume: float) -> float:
    """Converts syringe steps to a volume.

    Args:
        target_steps (int): The number of steps.
        maximum_volume (float): The maximum syringe volume.

    Returns:
        float: The equivalent volume of liquid.
    """
    if current_steps == 1:
        return 0.0
    return maximum_volume * (current_steps / MAX_VOLUME_STEPS)


def _convert_volume_to_steps(target_volume: float, maximum_volume: float) -> int:
    """Converts the target volume to a number of syringe steps.

    Args:
        target_volume (float): The desired liquid volume.
        maximum_volume (float): The maximum syringe volume.

    Returns:
        int: The closest equivalent volume in terms of steps.
    """
    if target_volume == 0.0:
        return 1
    return int(round(MAX_VOLUME_STEPS * (target_volume / maximum_volume)))


def _get_volume_string_as_float(idx: int) -> float:
    """Gets the float value of the volume from its string. Units are not taken into
    account.

    Args:
        idx (int): The index of the volume from the string list.

    Returns:
        float: The float value of the selected volume.
    """
    return float(SYRINGE_SIZES[idx].split()[0])


class Wrapper:

    POLL_PERIOD = 0.1
    RETRY_PERIOD = 5

    def __init__(self, ip: str, port: int, builder: builder, device_name: str):

        self._log = logging.getLogger(self.__class__.__name__)

        self.microlab = Microlab(ip, port)
        if not self.microlab.auto_address():
            exit()

        self.device_name = device_name

        self.status = builder.WaveformIn("Status", length=128, datatype="b")

        self.firmware_version = builder.stringIn("FirmwareVersion")

        self.right_syringe_maximum_volume = builder.longIn("Right:MaximumSyringeVolume")
        self.right_syringe_maximum_volume.set(INITIAL_MAX_VOLUME)
        self.left_syringe_maximum_volume = builder.longIn("Left:MaximumSyringeVolume")
        self.left_syringe_maximum_volume.set(INITIAL_MAX_VOLUME)
        self.minimum_volume = builder.longIn("MinimumVolume")
        self.minimum_volume.set(0)

        # Status/Error/Information Requests
        self.instrument_idle = builder.boolIn("InstrumentBusyRequest")
        self.command_buffer_empty = builder.boolIn("CommandBufferBusyRequest")
        self.syringe_error = builder.boolIn("SyringeError")
        self.valve_error = builder.boolIn("ValveError")
        self.timer_busy_status = builder.boolIn("TimerBusyStatus")
        self.instrument_error_status = builder.longIn("InstrumentErrorStatus")
        self.instrument_busy_status = builder.longIn("InstrumentBusyStatus")
        self.instrument_status_request = builder.longIn("InstrumentStatusRequest")

        self.detailed_rsyringe_error = builder.longIn("Right:Syringe:ErrorRequest")
        self.detailed_lsyringe_error = builder.longIn("Left:Syringe:ErrorRequest")

        self.detailed_rvalve_error = builder.longIn("Right:Valve:ErrorRequest")
        self.detailed_lvalve_error = builder.longIn("Left:Valve:ErrorRequest")

        self.right_max_vol = self.left_max_vol = INITIAL_MAX_VOLUME

        # Right Syringe Position
        self.right_syringe_volume_in = builder.aIn(
            "Right:SyringeVolume_RBV", HOPR=0, LOPR=INITIAL_MAX_VOLUME
        )
        self.right_syringe_volume_out = builder.aOut(
            "Right:SyringeVolume", on_update=self.change_right_liquid_volume,
        )

        # Left Syringe Position
        self.left_syringe_volume_in = builder.aIn(
            "Left:SyringeVolume_RBV", HOPR=0, LOPR=INITIAL_MAX_VOLUME
        )
        self.left_syringe_volume_out = builder.aOut(
            "Left:SyringeVolume", on_update=self.change_left_liquid_volume,
        )

        # Valve Position
        self.right_valve_position_in = builder.longIn("Right:ValvePosition_RBV")
        self.left_valve_position_in = builder.longIn("Left:ValvePosition_RBV")

        # Right Syringe Default Speed
        self.right_syringe_speed_in = builder.longIn("Right:SyringeDefaultSpeed_RBV")
        self.right_syringe_speed_out = builder.longOut(
            "Right:SyringeDefaultSpeed",
            on_update=self.microlab.right.syringe_default_speed.set,
        )

        # Left Syringe Default Speed
        self.left_syringe_speed_in = builder.longIn("Left:SyringeDefaultSpeed_RBV")
        self.left_syringe_speed_out = builder.longOut(
            "Left:SyringeDefaultSpeed",
            on_update=self.microlab.left.syringe_default_speed.set,
        )

        # Right Valve Speed
        self.right_valve_speed_in = builder.longIn("Right:ValveSpeed_RBV")
        self.right_valve_speed_out = builder.longOut(
            "Right:ValveSpeed", on_update=self.microlab.right.valve_speed.set,
        )

        # Left Valve Speed
        self.left_valve_speed_in = builder.longIn("Left:ValveSpeed_RBV")
        self.left_valve_speed_out = builder.longOut(
            "Left:ValveSpeed", on_update=self.microlab.left.valve_speed.set,
        )

        # Right Syringe Default Return Steps
        self.right_syringe_return_steps_in = builder.longIn(
            "Right:SyringeDefaultReturnSteps_RBV"
        )
        self.right_syringe_return_steps_out = builder.longOut(
            "Right:SyringeDefaultReturnSteps",
            on_update=self.microlab.right.syringe_default_return_steps.set,
        )

        # Left Syringe Default Return Steps
        self.left_syringe_return_steps_in = builder.longIn(
            "Left:SyringeDefaultReturnSteps_RBV"
        )
        self.left_syringe_return_steps_out = builder.longOut(
            "Left:SyringeDefaultReturnSteps",
            on_update=self.microlab.left.syringe_default_return_steps.set,
        )

        # Right Syringe Default Back Off Steps
        self.right_syringe_backoff_steps_in = builder.longIn(
            "Right:SyringeDefaultBackOffSteps_RBV"
        )
        self.right_syringe_back_off_steps_out = builder.longOut(
            "Right:SyringeDefaultBackOffSteps",
            on_update=self.microlab.right.syringe_default_back_off_steps.set,
        )

        # Left Syringe Default Back Off Steps
        self.left_syringe_backoff_steps_in = builder.longIn(
            "Left:SyringeDefaultBackOffSteps_RBV"
        )
        self.left_syringe_back_off_steps_out = builder.longOut(
            "Left:SyringeDefaultBackOffSteps",
            on_update=self.microlab.left.syringe_default_back_off_steps.set,
        )

        # Halt Execution
        self.halt_execution_out = builder.aOut(
            "HaltExecution", on_update=self.halt_execution
        )

        # Initialise
        self.initialise_out = builder.aOut("Initialise", on_update=self.initialise)
        self.initialised = builder.boolIn("DeviceInitialised")
        self.initialised.set(False)

        # Right Valve To Input/Output
        self.right_valve_input = builder.aOut(
            "Right:ValveToInput",
            on_update=lambda _: self._move_valve_to_input(Side.RIGHT),
        )
        self.right_valve_output = builder.aOut(
            "Right:ValveToOutput",
            on_update=lambda _: self._move_valve_to_output(Side.RIGHT),
        )

        # Left Valve To Input/Output
        self.left_valve_input = builder.aOut(
            "Left:ValveToInput",
            on_update=lambda _: self._move_valve_to_input(Side.LEFT),
        )
        self.left_valve_output = builder.aOut(
            "Left:ValveToOutput",
            on_update=lambda _: self._move_valve_to_output(Side.LEFT),
        )

        # Syringe Movements
        self.right_liquid_volume_increasing = builder.longIn("Right:VolumeIncreasing")
        self.right_liquid_volume_decreasing = builder.longIn("Right:VolumeDecreasing")

        self.left_liquid_volume_increasing = builder.longIn("Left:VolumeIncreasing")
        self.left_liquid_volume_decreasing = builder.longIn("Left:VolumeDecreasing")

        # Syringe Error
        self.right_syringe_error = builder.stringIn("Right:SyringeError")
        self.left_syringe_error = builder.stringIn("Left:SyringeError")

        # Change Maximum Syringe Volume
        self.change_right_syringe_scale = builder.mbbOut(
            "Right:ChangeSyringeScale",
            *SIZE_MAPPING,
            on_update=self._change_right_syringe_scale,
        )
        self.change_left_syringe_scale = builder.mbbOut(
            "Left:ChangeSyringeScale",
            *SIZE_MAPPING,
            on_update=self._change_left_syringe_scale,
        )

        # Change Left Maximum Syringe Volume
        self.change_right_valve_position = builder.mbbOut(
            "Right:ChangeValvePosition",
            *VALVE_POSITIONS,
            on_update=self._change_right_valve_position,
        )
        self.change_left_valve_position = builder.mbbOut(
            "Left:ChangeValvePosition",
            *VALVE_POSITIONS,
            on_update=self._change_left_valve_position,
        )

        # Syringe Pickup
        self.right_syringe_pickup_out = builder.aOut(
            "Right:SyringePickup", on_update=self.right_syringe_pickup,
        )
        self.left_syringe_pickup_out = builder.aOut(
            "Left:SyringePickup", on_update=self.left_syringe_pickup,
        )

        # Syringe Dispense
        self.right_syringe_dispense_out = builder.aOut(
            "Right:SyringeDispense", on_update=self.right_syringe_dispense
        )
        self.left_syringe_dispense_out = builder.aOut(
            "Left:SyringeDispense", on_update=self.left_syringe_dispense
        )

        self.right_syringe_pickup_dispense_value = builder.aOut(
            "Right:SyringePickupDispenseValue"
        )
        self.left_syringe_pickup_dispense_value = builder.aOut(
            "Left:SyringePickupDispenseValue"
        )

        # Cycle Buttons
        self.start_cycle_out = builder.aOut("StartCycle", on_update=self.start_cycle)
        self.stop_cycle_out = builder.aOut("StopCycle", on_update=self.stop_cycle)
        self.cycle_active_in = builder.boolIn("CycleActive")
        self.cycle_active_in.set(False)

        # Fill and Flow Speeds
        self.cycle_rfill_lflow_speed_out = builder.longOut(
            "RFillLFlowSpeed", on_update=self.change_rfill_lflow_speed
        )
        self.cycle_rfill_lflow_speed_in = builder.longIn("RFillLFlowSpeed_RBV")

        self.cycle_rflow_lfill_speed_out = builder.longOut(
            "RFlowLFillSpeed", on_update=self.change_rflow_lfill_speed
        )
        self.cycle_rflow_lfill_speed_in = builder.longIn("RFlowLFillSpeed_RBV")

        self._parameter_map = {
            self.right_valve_position_in: self.get_right_valve_position,
            self.left_valve_position_in: self.get_left_valve_position,
            self.right_syringe_speed_in: self.get_right_syringe_speed,
            self.left_syringe_speed_in: self.get_left_syringe_speed,
            self.right_valve_speed_in: self.get_right_valve_speed,
            self.left_valve_speed_in: self.get_left_valve_speed,
            self.right_syringe_return_steps_in: self.get_right_syringe_return_steps,
            self.left_syringe_return_steps_in: self.get_left_syringe_return_steps,
            self.right_syringe_backoff_steps_in: self.get_right_syringe_backoff_steps,
            self.left_syringe_backoff_steps_in: self.get_left_syringe_backoff_steps,
            self.syringe_error: self.get_combined_syringe_error_status,
            self.valve_error: self.get_combined_valve_error_status,
            self.instrument_error_status: self.get_instrument_error_status,
            self.right_syringe_error: self.get_right_syringe_error_status,
            self.left_syringe_error: self.get_left_syringe_error_status,
            self.instrument_busy_status: self.get_instrument_busy_status,
            self.detailed_rsyringe_error: lambda: self.get_detailed_syringe_valve_error(
                2
            ),
            self.detailed_lsyringe_error: lambda: self.get_detailed_syringe_valve_error(
                0
            ),
            self.detailed_rvalve_error: lambda: self.get_detailed_syringe_valve_error(
                3
            ),
            self.detailed_lvalve_error: lambda: self.get_detailed_syringe_valve_error(
                1
            ),
            self.instrument_status_request: self.get_instrument_status_request,
        }

        self._busy_parameters = {
            self.timer_busy_status: self.get_timer_busy_status,
            self.command_buffer_empty: self.get_command_buffer_busy_status,
            self.instrument_idle: self.get_instrument_idle_status,
        }

        # Hide non-error log messages from the parameter/information request/etc objects
        logging.getLogger(self.microlab._comms.__class__.__name__).setLevel(
            logging.ERROR
        )
        logging.getLogger(self.microlab.instrument_done.__class__.__name__).setLevel(
            logging.ERROR
        )
        logging.getLogger(self.microlab.timer_busy_status.__class__.__name__).setLevel(
            logging.ERROR
        )
        logging.getLogger(
            self.microlab.instrument_error_status.__class__.__name__
        ).setLevel(logging.ERROR)
        logging.getLogger(
            self.microlab.instrument_busy_status.__class__.__name__
        ).setLevel(logging.ERROR)
        logging.getLogger(
            self.microlab.instrument_status_request.__class__.__name__
        ).setLevel(logging.ERROR)
        logging.getLogger(
            self.microlab.right.syringe_position.__class__.__name__
        ).setLevel(logging.ERROR)
        logging.getLogger(
            self.microlab.instrument_error_request.__class__.__name__
        ).setLevel(logging.ERROR)

        self._r_volume_recent_values = deque([0, 0], 2)
        self._l_volume_recent_values = deque([0, 0], 2)
        self.monitor_loop_active = builder.boolIn("MonitorActive")
        self._parameter_thread = cothread.Spawn(self._parameter_loop)
        self._volume_thread = cothread.Spawn(self._syringe_volume_loop)
        self._busy_thread = cothread.Spawn(self._check_busy_loop)
        self._right_movement_direction_thread = cothread.Spawn(
            lambda: self._syringe_movement_loop(
                self.microlab.right,
                self._r_volume_recent_values,
                self.right_liquid_volume_increasing,
                self.right_liquid_volume_decreasing,
            )
        )
        self.left_movement_direction_thread = cothread.Spawn(
            lambda: self._syringe_movement_loop(
                self.microlab.left,
                self._l_volume_recent_values,
                self.left_liquid_volume_increasing,
                self.left_liquid_volume_decreasing,
            )
        )

    def set_status(self, message: str, level: str = "info"):
        """Changes the status. Used for the monitor loop.

        Args:
            message (str): The status message.
            level (str, optional): The logging level to use. Defaults to "info".
        """
        char_array = np.frombuffer(message.encode(), dtype="uint8")
        if not np.array_equal(char_array, self.status.get()):
            self.status.set(char_array)
            self._log.__getattribute__(level)(message)

    def _values_increasing(self, volumes: Deque[int]) -> bool:
        """Used to check if the syringe position is increasing.

        Args:
            volumes (Deque[int]): A deque containing the two latest syringe position
                values.

        Returns:
            bool: True if the position is increasing, False otherwise.
        """
        return volumes[0] < volumes[1]

    def _values_decreasing(self, volumes: Deque[int]) -> bool:
        """Used to check if the syringe position is decreasing.

        Args:
            volumes (Deque[int]): A deque containing the two latest syringe position
                values.

        Returns:
            bool: True if the position is decreasing, False otherwise.
        """
        return volumes[0] > volumes[1]

    def _set_pv_and_alarm(
        self, pv: RecordWrapper, value: Optional[Any], alarm_level: int,
    ):
        """Sets a value and alarm level for a PV.

        Args:
            pv (RecordWrapper): The record.
            value (Optional[Any]): The new value. Can be None if the information request
                failed.
            alarm_level (int): The new alarm level.
        """
        if value is not None:
            pv.set(value, alarm_level, alarm.STATE_ALARM)
        else:
            pv.set_alarm(alarm_level, alarm.READ_ALARM)

    def _monitor_loop(
        self,
        parameter_map: Dict[RecordWrapper, Callable],
        error_message: str,
        poll_period: float,
    ):
        """Creates a monitor loop with a given PV dictionary.

        Args:
            parameter_map (Dict[RecordWrapper, Callable]): The dictionary of PVs and a
                method for getting the current value.
            error_message (str): The message to print when the loop encouters an
                exception.
            poll_period (float): The poll period to use after every PV has been updated.
        """
        while True:
            try:
                cothread.Sleep(poll_period)
                for pv, getter in parameter_map.items():
                    value, alarm_level = getter()
                    self._set_pv_and_alarm(pv, value, alarm_level)
                    cothread.Sleep(0.001)
            except Exception as exception:
                self.set_status(f"{error_message}: {exception}", level="warning")
                cothread.Sleep(self.RETRY_PERIOD)

    def _parameter_loop(self):
        """Monitors "non-urgent" parameters.
        """
        self.monitor_loop_active.set(True)
        self.set_firmware_version()
        self.change_rfill_lflow_speed(MIN_SPEED)
        self.change_rflow_lfill_speed(MIN_SPEED)

        self._monitor_loop(
            self._parameter_map, "Error in parameter monitor thread", self.POLL_PERIOD
        )

    def _check_busy_loop(self):
        """Monitors the instrument busy status, timer busy status, and command buffer
        busy status in a devoted thread.
        """
        self._monitor_loop(
            self._busy_parameters, "Error raised in busy status monitor thread", 0,
        )

    def _wait_for_syringe_position(self, syringe_side: SideParametersGroup) -> int:
        """Asks for the syringe position until a response is given.

        Args:
            syringe_side (SideParametersGroup): The right/left side parameters group.

        Returns:
            int: The syringe position in steps.
        """
        while True:
            syringe_position = syringe_side.syringe_position.get()
            if syringe_position is None:
                cothread.Sleep(self.RETRY_PERIOD)
                continue
            return syringe_position

    def _get_right_syringe_speed(self) -> Optional[int]:
        """Gets the right syringe speed. If the cycle is running, then it returns
        the slowest of the two cycle speeds (fill or flow). If the cycle isn't running,
        then it returns the current default syringe speed.

        Returns:
            Optional[int]: The cycle or default syringe speed. Returns None if the
            syringe default speed request failed.
        """
        if not self.cycle_active_in.get():
            return self.microlab.right.syringe_default_speed.get()
        return self.right_cycle_speed

    def _get_left_syringe_speed(self) -> Optional[int]:
        """Gets the left syringe speed. If the cycle is running, then it returns the
        slowest of the two cycle speeds (fill or flow). If the cycle isn't running, then
        it returns the current default syringe speed.

        Returns:
            Optional[int]: The cycle or default syringe speed. Returns None if the
            syringe default speed request failed.
        """
        if not self.cycle_active_in.get():
            return self.microlab.left.syringe_default_speed.get()
        return self.left_cycle_speed

    def _syringe_movement_loop(
        self,
        side: SideParametersGroup,
        recent_positions: deque,
        increasing_record: RecordWrapper,
        decreasing_record: RecordWrapper,
    ):
        """Monitors changes in the syringe movement direction.

        Args:
            side (SideParametersGroup): The right/left side parameters group that is
                used to access the syringe position.
            recent_positions (deque): A deque of recent syringe positions.
            increasing_record (RecordWrapper): The PV that should be set to true if the
                position is increasing, and set to false if the position is decreasing
                or not changing.
            decreasing_record (RecordWrapper): The PV that should be set to true if the
                position is decreasing, and set to false if the position is increasing
                or not changing.
        """
        while True:
            try:
                position = side.syringe_position.get()
                if position is None:
                    cothread.Sleep(self.RETRY_PERIOD)
                    continue

                recent_positions.append(position)
                increasing_record.set(self._values_increasing(recent_positions))
                decreasing_record.set(self._values_decreasing(recent_positions))
                cothread.Sleep(self.POLL_PERIOD)

            except Exception as error:
                self.set_status(
                    "Error raised in syringe direction imonitor thread: %s" % error,
                    level="warning",
                )
                cothread.Sleep(self.RETRY_PERIOD)

    def _syringe_volume_loop(self):
        """Monitors changes in the syringe volume.
        """
        while True:
            try:
                r_volume, r_alarm_level = self.get_right_syringe_volume()
                self._set_pv_and_alarm(
                    self.right_syringe_volume_in, r_volume, r_alarm_level
                )
                l_volume, l_alarm_level = self.get_left_syringe_volume()
                self._set_pv_and_alarm(
                    self.left_syringe_volume_in, l_volume, l_alarm_level
                )
                cothread.Sleep(self.POLL_PERIOD)
            except Exception as error:
                self.set_status(
                    "Error raised in syringe volume imonitor thread: %s" % error,
                    level="warning",
                )
                cothread.Sleep(self.RETRY_PERIOD)

    def set_firmware_version(self):
        """Sets the firmware version.
        """
        self.firmware_version.set(self.microlab.get_firmware_version())

    def initialise(self, arg: Any):
        """Initialises the device and starts threads for checking if the syringes are
        currently moving.

        Args:
            arg (Any): An argument that is sent from the EDM interface when the
                initialise button is pushed. This isn't used for anything.
        """
        self.microlab.initialise()
        self.initialised.set(True)

    def halt_execution(self, arg: Any):
        """Halts command execution and clears the command buffer.

        Args:
            arg (Any): An argument that is sent from the EDM interface when the STOP
                button is pushed. This isn't used for anything.
        """
        if arg == 0:
            return
        self.microlab.halt_execution()
        self.microlab.clear_all_buffered_commands()
        # Set all the volume movement records to 0/False
        self.right_liquid_volume_increasing.set(0)
        self.right_liquid_volume_decreasing.set(0)
        self.left_liquid_volume_increasing.set(0)
        self.left_liquid_volume_decreasing.set(0)
        self.halt_execution_out.set(0)

    def _return_invalid_alarm_when_request_is_none(
        self,
        response: str,
        return_true_if_match: List[str],
        return_alarm_if_true: bool = False,
    ) -> Tuple[Optional[bool], int]:
        """Returns a state from an instrument information request and an alarm level.

        Args:
            response (str): The response string.
            return_true_if_match (List[str]): The state should be true if the response
                string is in this list.
            return_alarm_if_true (bool): Indicates if the state being true means an
                alarm should be returned.

        Returns:
            Tuple[Optional[bool], int]: The matching state bool and a corresponding
            alarm level.
        """
        if response is None:
            return None, alarm.INVALID_ALARM

        state = response in return_true_if_match

        if return_alarm_if_true and state:
            return state, alarm.MAJOR_ALARM
        return state, alarm.NO_ALARM

    def get_instrument_idle_status(self) -> Tuple[Optional[bool], int]:
        """Checks if the instrument is idle.

        Returns:
            Tuple[Optional[bool], int]: True + no alarm level if the instrument is idle,
            False + no alarm level if the instrument is busy, None + an invalid
            alarm level is if the request failed.
        """
        return self._return_invalid_alarm_when_request_is_none(
            self.microlab.instrument_done.request(), [AST_INFO_RESPONSE],
        )

    def get_command_buffer_busy_status(self) -> Tuple[Optional[bool], int]:
        """Checks if the command buffer is empty.

        Returns:
            Tuple[Optional[bool], int]: True + no alarm level if the command buffer is
            not empty, False + no alarm level if the command buffer is empty, None +
            an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_request_is_none(
            self.microlab.instrument_done.request(),
            [N_INFO_RESPONSE, AST_INFO_RESPONSE],
        )

    def get_combined_syringe_error_status(self) -> Tuple[Optional[bool], int]:
        """Checks if the instrument is reporting any syringe errors.

        Returns:
            Tuple[Optional[bool], int]: True + a major alarm level if a syringe error
            has been reported, False + no alarm level if a syringe error has not
            been reported, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_request_is_none(
            self.microlab.syringe_error.request(), [Y_INFO_RESPONSE], True
        )

    def _get_individual_syringe_error_status(self, error: int) -> Tuple[str, int]:
        """Checks if the instrument is reporting an error on a specific syringe.

        Args:
            error (int): A byte in which the bit of a specific error is set to true.

        Returns:
            Tuple[str, int]: "Syringe Error" + a major alarm level if an error was
            reported, "Ready" + no alarm level if no error was reported,
            "Request Error" + an invalid alarm level if the request failed.
        """
        response = self.microlab.instrument_error_status.request()
        if response is None:
            return "Request Error", alarm.INVALID_ALARM
        if response & error:
            return "Syringe Error", alarm.MAJOR_ALARM
        return "Ready", alarm.NO_ALARM

    def get_right_syringe_error_status(self) -> Tuple[str, int]:
        """Checks if the instrument is reporting a right syringe error.

        Returns:
            Tuple[str, int]: A string indicating the syringe error status and a
            corresponding alarm level.
        """
        return self._get_individual_syringe_error_status(8)

    def get_left_syringe_error_status(self) -> Tuple[str, int]:
        """Checks if the instrument is reporting a left syringe error.

        Returns:
            Tuple[str, int]: A string indicating the syringe error status and a
            corresponding alarm level.
        """
        return self._get_individual_syringe_error_status(2)

    def get_combined_valve_error_status(self) -> Tuple[Optional[bool], int]:
        """Checks if the instrument is reporting any valve errors.

        Returns:
            Tuple[Optional[bool], int]: True + a major alarm level if a valve error has
            been reported, False + no alarm level if a valve error has been
            reported, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_request_is_none(
            self.microlab.valve_error.request(), [Y_INFO_RESPONSE], True
        )

    def _return_invalid_alarm_when_parameter_is_none(
        self, response: Optional[int]
    ) -> Tuple[Optional[int], int]:
        """Returns a response from a parameter request and an alarm level.

        Args:
            response (Optional[int]): The response from the request.

        Returns:
            Tuple[Optional[int], int]: The response and an alarm level. An invalid alarm
            level is only returned if the response was None, otherwise the alarm
            level is 0.
        """
        if response is None:
            return None, alarm.INVALID_ALARM
        return response, alarm.NO_ALARM

    def _get_syringe_volume(
        self, syringe_position: Optional[int], syringe_max_vol: float
    ) -> Tuple[Optional[float], int]:
        """Gets the current current volume of the syringe by converting from the its
        position.

        Args:
            syringe_position (Optional[int]): The syringe position in steps.
            syringe_max_vol (float): The maximum volume of the syringe.

        Returns:
            Tuple[Optional[int], int]: The current syringe volume and a corresponding
            alarm level.
        """
        position, alarm_level = self._return_invalid_alarm_when_parameter_is_none(
            syringe_position
        )
        if position is not None:
            return (
                _convert_steps_to_volume(position, syringe_max_vol),
                alarm_level,
            )
        return None, alarm_level

    def get_right_syringe_volume(self) -> Tuple[Optional[float], int]:
        """Checks for the right syringe volume. Returns the response and an alarm level
        related to the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The position + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._get_syringe_volume(
            self.microlab.right.syringe_position.get(), self.right_max_vol
        )

    def get_left_syringe_volume(self) -> Tuple[Optional[float], int]:
        """Checks for the left syringe volume. Returns the response and an alarm level
        related to the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The position + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._get_syringe_volume(
            self.microlab.left.syringe_position.get(), self.left_max_vol
        )

    def get_right_valve_position(self) -> Tuple[Optional[int], int]:
        """Checks for the right valve position value. Returns the response and an alarm
        level related to the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The position + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.right.valve_position.get()
        )

    def get_left_valve_position(self) -> Tuple[Optional[int], int]:
        """Checks for the left valve position value. Returns the response and an alarm
        level related to the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The position + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.left.valve_position.get()
        )

    def _return_major_alarm_when_bit_is_true(
        self, response: int, alarm_byte: int, response_subbyte: int
    ) -> Tuple[int, int]:
        """Returns a response from an instrument status request and an alarm level.

        Args:
            response (int): The byte response.
            alarm_byte (int): A byte in which the only true bits signify relevant
                alarms.
            response_subbyte (int): The trimmed byte containing only the bits in the
                response that have information we want to display.

        Returns:
            Tuple[int, int]: The response and an alarm level: A major alarm level is
            returned if the response indicated errors, otherwise no alarm level is
            returned.
        """
        if response & alarm_byte:
            return response_subbyte, alarm.MAJOR_ALARM
        return response_subbyte, alarm.NO_ALARM

    def get_instrument_error_status(self) -> Tuple[Optional[int], int]:
        """Checks the instrument error status. Returns the response and the appropriate
        alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The response + no alarm level if no errors have
            been reported, the response + a major alarm level if one or more errors
            have been reported, None + an invalid alarm level if the request failed.
        """
        response = self.microlab.instrument_error_status.request()
        if response is None:
            return None, alarm.INVALID_ALARM
        return self._return_major_alarm_when_bit_is_true(
            response, 15, _get_last_n_bits(response, 4)
        )

    def get_instrument_busy_status(self) -> Tuple[Optional[int], int]:
        """Checks the instrument busy status. Returns the response and the appropriate
        alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The response + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        response = self.microlab.instrument_busy_status.request()
        if response is None:
            return None, alarm.INVALID_ALARM
        return self._return_major_alarm_when_bit_is_true(
            response, 0, _get_last_n_bits(response, 2)
        )

    def get_instrument_status_request(self) -> Tuple[Optional[int], int]:
        """Checks the instrument status. Returns the response and the appropriate alarm
        level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The response + no alarm level if no errors were
            reported, the response + a major alarm level if one or more errors were
            reported, None + an invalid level alarm if the request failed.
        """
        response = self.microlab.instrument_status_request.request()
        if response is None:
            return None, alarm.INVALID_ALARM
        return self._return_major_alarm_when_bit_is_true(
            response, 30, _get_last_n_bits(response, 5) >> 3
        )

    def get_timer_busy_status(self) -> Tuple[Optional[bool], int]:
        """Checks if the timer is busy. Returns a response and the appropriate alarm
        level depending on the outcome of the request.

        Returns:
            Tuple[Optional[bool], int]: True + no alarm level if the timer is busy,
            False + no alarm level if the timer is not busy, None + an invalid alarm
            level if the request failed.
        """
        response = self.microlab.timer_busy_status.request()
        if response is None:
            return None, alarm.INVALID_ALARM
        return response, alarm.NO_ALARM

    def get_right_syringe_speed(self) -> Tuple[Optional[int], int]:
        """Checks for the right syringe speed value. Returns the response and the
        appropriate alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The speed + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.right.syringe_default_speed.get()
        )

    def get_left_syringe_speed(self) -> Tuple[Optional[int], int]:
        """Checks for the left syringe speed value. Returns the response and the
        appropriate alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The speed + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.left.syringe_default_speed.get()
        )

    def get_right_valve_speed(self) -> Tuple[Optional[int], int]:
        """Checks for the right valve speed value. Returns the response and the
        appropriate alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The speed + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.right.valve_speed.get()
        )

    def get_left_valve_speed(self) -> Tuple[Optional[int], int]:
        """Checks for the left valve speed value. Returns the response and the
        appropriate alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The speed + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.left.valve_speed.get()
        )

    def get_right_syringe_return_steps(self) -> Tuple[Optional[int], int]:
        """Checks for the right syringe return steps value. Returns the response and the
        appropriate alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The steps + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.right.syringe_default_return_steps.get()
        )

    def get_left_syringe_return_steps(self) -> Tuple[Optional[int], int]:
        """Checks for the left syringe return steps value. Returns the response and the
        appropriate alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The steps + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.left.syringe_default_return_steps.get()
        )

    def get_right_syringe_backoff_steps(self) -> Tuple[Optional[int], int]:
        """Checks for the right syringe back off steps value. Returns the response and
        the appropriate alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The steps + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.right.syringe_default_back_off_steps.get()
        )

    def get_left_syringe_backoff_steps(self) -> Tuple[Optional[int], int]:
        """Checks for the left syringe back off steps value. Returns the response and
        the appropriate alarm level depending on the outcome of the request.

        Returns:
            Tuple[Optional[int], int]: The steps + no alarm level if the request
            succeeded, None + an invalid alarm level if the request failed.
        """
        return self._return_invalid_alarm_when_parameter_is_none(
            self.microlab.left.syringe_default_back_off_steps.get()
        )

    def _move_syringe_by_absolute_steps(self, side: Side, value: int):
        """Moves a syringe a given number of steps.

        Args:
            side (Side): Determines if the movement instruction is sent to the right or
                left syringe.
            value (int): The number of movement steps.
        """
        subcommand = SyringeAbsoluteMove(side=side, value=value)
        self.microlab.send_command(Command([subcommand]))

    def change_right_liquid_volume(self, target_volume: float):
        """Changes the position of the right syringe by converting a volume to steps.

        Args:
            target_volume (float): The desired volume.
        """
        self._move_syringe_by_absolute_steps(
            Side.RIGHT, _convert_volume_to_steps(target_volume, self.right_max_vol)
        )

    def change_left_liquid_volume(self, target_volume: float):
        """Changes the position of the left syringe by converting a volume to steps.

        Args:
            target_volume (float): The desired volume.
        """
        self._move_syringe_by_absolute_steps(
            Side.LEFT, _convert_volume_to_steps(target_volume, self.left_max_vol)
        )

    def _move_valve_to_input(self, side: Side):
        """Moves a valve to the input position.

        Args:
            side (Side): Determines if the movement instruction is sent to the right or
                left valve.
        """
        subcommand = ValveToDefaultInput(side)
        self.microlab.send_command(Command([subcommand]))
        self._log.info(f"Moving {side.name.lower()} valve to input")

    def _move_valve_to_output(self, side: Side):
        """Moves a valve to the output position.

        Args:
            side (Side): Determines if the movement instruction is sent to the right or
                left valve.
        """
        subcommand = ValveToDefaultOutput(side)
        self.microlab.send_command(Command([subcommand]))
        self._log.info(f"Moving {side.name.lower()} valve to output")

    def _change_right_syringe_scale(self, idx: int):
        """Changes the scale of the right syringe.

        Args:
            idx (int): The index of the new syringe volume.
        """
        self.right_max_vol = _get_volume_string_as_float(idx)
        caput(self.device_name + ":Right:" + SYRINGE_VOL_LOPR, self.right_max_vol)

    def _change_left_syringe_scale(self, idx: int):
        """Changes the scale of the left syringe.

        Args:
            idx (int): The index of the new syringe volume.
        """
        self.left_max_vol = _get_volume_string_as_float(idx)
        caput(self.device_name + ":Left:" + SYRINGE_VOL_LOPR, self.left_max_vol)

    def get_detailed_syringe_valve_error(self, idx: int) -> Tuple[Optional[int], int]:
        """Gets the instrument error request information for a given syringe/valve.

        Args:
            idx (int): The index for the byte in the response that corresponds with the
                left/right syringe/valve.

        Returns:
            Tuple[Optional[int], int]: The response + no alarm level if no errors were
            reported, the response + major alarm level if one or more errors were
            reported, None + the invalid alarm if the request failed.
        """
        response = self.microlab.instrument_error_request.request()
        if response is None:
            return None, alarm.INVALID_ALARM
        return self._return_major_alarm_when_bit_is_true(
            response[idx], 31, _get_last_n_bits(response[idx], 5)
        )

    def _change_right_valve_position(self, idx: int):
        """Changes the right valve position.

        Args:
            idx (int): The index of the new valve position.
        """
        if VALVE_POSITIONS[idx] == "Inlet":
            self._move_valve_to_input(Side.RIGHT)
        else:
            self._move_valve_to_output(Side.RIGHT)

    def _change_left_valve_position(self, idx: int):
        """Changes the left valve position.

        Args:
            idx (int): The index of the new valve position.
        """
        if VALVE_POSITIONS[idx] == "Inlet":
            self._move_valve_to_input(Side.LEFT)
        else:
            self._move_valve_to_output(Side.LEFT)

    def _syringe_pickup(self, side: Side, steps: int):
        """Sends a syringe pickup command using a given volume and number of steps.

        Args:
            side (Side): Whether the command should be sent to the right/left syringe.
            steps (int): The desired pickup steps.
        """
        subcommand = SyringePickup(side=side, value=steps)
        self.microlab.send_command(Command([subcommand]))

    def right_syringe_pickup(self, arg: Any):
        """Sends a right syringe pickup command using a given volume.

        Args:
            arg (Any): The message argument from the EDM button. Not used for anything.
        """
        if arg == 0:
            return
        volume = self.right_syringe_pickup_dispense_value.get()
        self._syringe_pickup(
            Side.RIGHT, _convert_volume_to_steps(volume, self.right_max_vol)
        )

    def left_syringe_pickup(self, arg: Any):
        """Sends a left syringe pickup command using a given volume.

        Args:
            arg (Any): The message argument from the EDM button. Not used for anything.
        """
        if arg == 0:
            return
        volume = self.left_syringe_pickup_dispense_value.get()
        self._syringe_pickup(
            Side.LEFT, _convert_volume_to_steps(volume, self.left_max_vol)
        )

    def _syringe_dispense(self, side: Side, steps: int):
        """Sends a syringe dispense command using a given volume and number of steps.

        Args:
            side (Side): Whether the command should be sent to the right/left syringe.
            steps (int): The desired dispense steps.
        """
        subcommand = SyringeDispense(side=side, value=steps)
        self.microlab.send_command(Command([subcommand]))

    def right_syringe_dispense(self, arg: Any):
        """Sends a right syringe dispense command using a given volume.

        Args:
            arg (Any): The message argument from the EDM button. Not used for anything.
        """
        if arg == 0:
            return
        volume = self.right_syringe_pickup_dispense_value.get()
        self._syringe_dispense(
            Side.RIGHT, _convert_volume_to_steps(volume, self.right_max_vol)
        )

    def left_syringe_dispense(self, arg: Any):
        """Sends a left syringe dispense command using a given volume.

        Args:
            arg (Any): The message argument from the EDM button. Not used for anything.
        """
        if arg == 0:
            return
        volume = self.left_syringe_pickup_dispense_value.get()
        self._syringe_dispense(
            Side.LEFT, _convert_volume_to_steps(volume, self.left_max_vol)
        )

    def change_rfill_lflow_speed(self, speed: int):
        """Sets the right fill and left flow speeds of the cycling command.

        Args:
            speed (int): The desired right fill and left flow speed.
        """
        if not _syringe_speed_in_valid_range(speed):
            self._log.error(f"Right fill / left flow speed {speed} is not valid.")
            return
        self.cycle_rfill_lflow_speed_in.set(speed)

    def change_rflow_lfill_speed(self, speed: int):
        """Sets the right flow and left fill speeds of the cycling command.

        Args:
            speed (int): The desired right flow and left fill speed.
        """
        if not _syringe_speed_in_valid_range(speed):
            self._log.error(f"Right flow / left fill speed {speed} is not valid.")
            return
        self.cycle_rflow_lfill_speed_in.set(speed)

    def start_cycle(self, arg: Any):
        """Starts the syringe movement cycle.

        Args:
            arg (Any): Argument sent from the message button on the EDM interface. Not
                used for anything.
        """
        if arg == 0:
            return

        rfill_lflow_speed = self.cycle_rfill_lflow_speed_in.get()
        rflow_lfill_speed = self.cycle_rflow_lfill_speed_in.get()

        empty_right_fill_left = [
            ValveToDefaultOutput(Side.RIGHT),
            SyringeAbsoluteMove(
                side=Side.RIGHT, value=MIN_SYRINGE_MOVE, speed=rflow_lfill_speed,
            ),
            ValveToDefaultInput(Side.LEFT),
            SyringeAbsoluteMove(
                side=Side.LEFT, value=MAX_VOLUME_STEPS, speed=rflow_lfill_speed,
            ),
        ]
        empty_left_fill_right = [
            ValveToDefaultInput(Side.RIGHT),
            SyringeAbsoluteMove(
                side=Side.RIGHT, value=MAX_VOLUME_STEPS, speed=rfill_lflow_speed,
            ),
            ValveToDefaultOutput(Side.LEFT),
            SyringeAbsoluteMove(
                side=Side.LEFT, value=MIN_SYRINGE_MOVE, speed=rfill_lflow_speed,
            ),
        ]
        self.microlab.cycle_commands(
            [Command(empty_right_fill_left), Command(empty_left_fill_right)]
        )
        self.cycle_active_in.set(True)
        self.right_cycle_speed = self.left_cycle_speed = max(
            rfill_lflow_speed, rflow_lfill_speed
        )

        self.stop_cycle_out.set(0)

    def stop_cycle(self, arg: Any):
        """Stops the command cycle.

        Args:
            arg (Any): Argument send from the message button on the EDM interface. Not
                used for anything.
        """
        if arg == 0:
            return

        self.microlab.stop_cycle(enable_logging=False)
        self.microlab.clear_all_buffered_commands()
        self.cycle_active_in.set(False)

        self.start_cycle_out.set(0)

    def total_system_reset(self):
        """Sends the instruction to power the instrument off and back on then exits the
        command line interface.
        """
        self.microlab.total_system_reset()

